"""
ShopMate AI — Phase 4 tests: spec facts, Flipkart normalizer, snapshot store

Run from the backend/ folder:   python -m pytest tests -q
No internet and no real data files needed — tiny fake records are built in the tests.
"""

from conftest import flipkart_record

from app.normalizers.flipkart import SkipProduct, fix_text, normalize_flipkart_product
from app.normalizers.spec_facts import extract_spec_facts
from app.services import snapshot_store

import pytest


# ---------- spec facts ----------


def test_phone_facts_are_typed_numbers():
    facts, conflicts = extract_spec_facts("smartphones", {"RAM": "8 GB", "Internal Storage": "128 GB", "Network Type": "5G, 4G"})
    assert facts["ram_gb"].value == 8.0
    assert facts["storage_gb"].value == 128.0
    assert facts["network_5g"].value is True
    assert conflicts == []


def test_missing_spec_is_absent_not_false():
    facts, _ = extract_spec_facts("smartphones", {"RAM": "8 GB"})
    assert "network_5g" not in facts
    assert "nfc" not in facts


def test_contradicting_listing_becomes_a_conflict_not_a_fact():
    facts, conflicts = extract_spec_facts("earphones", {"Noise Cancellation": "Yes", "Active Noise Cancellation": "No"})
    assert "noise_cancellation" not in facts
    assert "noise_cancellation" in conflicts


def test_battery_hours_conflict_when_play_time_and_battery_life_disagree():
    facts, conflicts = extract_spec_facts("earphones", {"Play Time": "40 Hours", "Battery Life": "10 hours"})
    assert "battery_hours" not in facts
    assert "battery_hours" in conflicts


def test_battery_hours_agree_within_one_hour():
    facts, conflicts = extract_spec_facts("earphones", {"Play Time": "40 Hours", "Battery Life": "40.5 hours"})
    assert facts["battery_hours"].value in (40.0, 40.5)
    assert conflicts == []


def test_laptop_weight_and_processor():
    facts, _ = extract_spec_facts("laptops", {"RAM": "16 GB", "Processor Name": "Core i5", "Weight": "1.4 kg"})
    assert facts["weight_kg"].value == 1.4
    assert facts["processor"].value == "core i5"


# ---------- normalizer ----------


def test_normalizer_builds_a_rupee_product():
    product = normalize_flipkart_product(flipkart_record(price=1499, rating=4.3, rating_count=250), "earphones")
    assert product.id == "flipkart-ACC1"
    assert product.source == "flipkart_snapshot"
    assert product.currency == "INR"
    assert product.price_inr == 1499
    assert product.captured_at == "2026-10-08"
    assert product.mrp == 2998


def test_rating_zero_means_no_rating():
    product = normalize_flipkart_product(flipkart_record(rating=0, rating_count=0), "earphones")
    assert product.rating is None
    assert product.rating_count is None


def test_mrp_is_dropped_when_not_higher_than_price():
    product = normalize_flipkart_product(flipkart_record(price=1000, mrp=1000), "earphones")
    assert product.mrp is None


@pytest.mark.parametrize("override,reason", [({"price": None}, "no price"), ({"price": 0}, "no price"), ({"title": "", "fullTitle": ""}, "no title"), ({"productId": None}, "no product id")])
def test_unusable_records_are_skipped_with_a_reason(override, reason):
    with pytest.raises(SkipProduct) as caught:
        normalize_flipkart_product(flipkart_record(**override), "earphones")
    assert reason in str(caught.value)


def test_tablets_are_skipped_under_laptops():
    record = flipkart_record(sections={"General": {"Is Tablet": "Yes"}})
    with pytest.raises(SkipProduct):
        normalize_flipkart_product(record, "laptops")


def test_garbled_text_is_repaired():
    assert fix_text("Ã¢â‚¬") != "Ã¢â‚¬"
    assert fix_text("plain text") == "plain text"


def test_variants_of_one_model_share_a_group():
    blue = normalize_flipkart_product(flipkart_record("A", title="Nova X (Blue, 128 GB)", item_id="i1"), "smartphones")
    black = normalize_flipkart_product(flipkart_record("B", title="Nova X (Black, 256 GB)", item_id="i2"), "smartphones")
    other = normalize_flipkart_product(flipkart_record("C", title="Nova Y (Blue, 128 GB)", item_id="i3"), "smartphones")
    assert blue.group_id == black.group_id
    assert blue.group_id != other.group_id


# ---------- snapshot store ----------


def test_no_files_means_no_snapshot():
    assert snapshot_store.load_snapshot() is None
    assert snapshot_store.is_active() is False


def test_snapshot_loads_counts_and_skips(write_snapshot):
    write_snapshot({"earphones": [flipkart_record("A"), flipkart_record("B"), flipkart_record("A"), flipkart_record("C", price=None)]})
    snapshot = snapshot_store.load_snapshot()
    assert snapshot is not None
    assert snapshot.counts == {"earphones": 2}
    assert snapshot.skipped["earphones"] == {"duplicate product id": 1, "no price": 1}
    assert snapshot.captured_label == "8 Oct 2026"
    assert snapshot_store.get_product("flipkart-A").id == "flipkart-A"
    assert snapshot_store.get_product("flipkart-nope") is None


def test_data_source_fakestore_switches_snapshot_off(write_snapshot, monkeypatch):
    write_snapshot({"earphones": [flipkart_record("A")]})
    monkeypatch.setenv("DATA_SOURCE", "fakestore")
    snapshot_store.reset_cache()
    assert snapshot_store.load_snapshot() is None


def test_format_date():
    assert snapshot_store.format_date("2026-10-08") == "8 Oct 2026"
    assert snapshot_store.format_date(None) == "an unknown date"