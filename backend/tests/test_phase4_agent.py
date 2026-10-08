"""
ShopMate AI — Phase 4 tests: requirement matching, ranking, verifier spec claims

Run from the backend/ folder:   python -m pytest tests -q
"""

from conftest import flipkart_record

from app.agent.requirements import CONFLICT, MET, NOT_MET, UNKNOWN, UNSUPPORTED, check_requirement
from app.agent.tools import filter_by_requirements, rank_products
from app.agent.verifier import verify_claim
from app.normalizers.flipkart import normalize_flipkart_product
from app.schemas.agent import Claim


def _earbuds(pid="E1", sections=None, **kw):
    return normalize_flipkart_product(flipkart_record(pid, sections=sections or {"General": {}}, **kw), "earphones")


def _phone(pid="P1", sections=None, **kw):
    return normalize_flipkart_product(flipkart_record(pid, sections=sections or {"General": {}}, **kw), "smartphones")


# ---------- requirement matching ----------


def test_anc_met_not_met_unknown_conflict():
    met = _earbuds(sections={"F": {"Noise Cancellation": "Yes"}})
    not_met = _earbuds(sections={"F": {"Noise Cancellation": "No"}})
    silent = _earbuds(sections={"F": {"Connectivity": "Bluetooth"}})
    conflict = _earbuds(sections={"F": {"Noise Cancellation": "Yes", "Active Noise Cancellation": "No"}})
    assert check_requirement("active noise cancellation", met).status == MET
    assert check_requirement("active noise cancellation", not_met).status == NOT_MET
    assert check_requirement("active noise cancellation", silent).status == UNKNOWN
    assert check_requirement("active noise cancellation", conflict).status == CONFLICT


def test_ram_minimum():
    phone = _phone(sections={"S": {"RAM": "6 GB"}})
    assert check_requirement("8GB RAM", phone).status == NOT_MET
    assert check_requirement("4GB RAM", phone).status == MET


def test_unrecognised_requirement_is_unsupported_not_dropped():
    phone = _phone(sections={"S": {"RAM": "8 GB"}})
    assert check_requirement("looks cool in orange", phone).status == UNSUPPORTED


def test_product_without_any_specs_is_unknown_never_not_met():
    assert check_requirement("5G", _phone()).status == UNKNOWN


def test_not_met_products_are_excluded_unknown_are_kept():
    good = _phone("G", sections={"S": {"RAM": "8 GB"}})
    bad = _phone("B", sections={"S": {"RAM": "4 GB"}})
    silent = _phone("S")
    kept, excluded, results = filter_by_requirements([good, bad, silent], ["8GB RAM"])
    assert {p.id for p in kept} == {"flipkart-G", "flipkart-S"}
    assert [p.id for p, _ in excluded] == ["flipkart-B"]
    assert set(results) == {"flipkart-G", "flipkart-B", "flipkart-S"}


# ---------- ranking ----------


def test_many_reviews_beat_a_perfect_score_from_few():
    few = _earbuds("F", rating=5.0, rating_count=3, price=1000)
    many = _earbuds("M", rating=4.5, rating_count=4000, price=1000)
    crowd = [_earbuds(f"X{i}", rating=3.8, rating_count=2000, price=1000) for i in range(6)]  # the pool's average is ~4
    assert rank_products([few, many] + crowd, top_n=1)[0].id == "flipkart-M"


def test_confirmed_requirements_add_to_score():
    plain = _earbuds("A", rating=4.2, rating_count=1000, price=1000)
    anc = _earbuds("B", rating=4.2, rating_count=1000, price=1000, sections={"F": {"Noise Cancellation": "Yes"}})
    _, _, results = filter_by_requirements([plain, anc], ["noise cancellation"])
    assert rank_products([plain, anc], top_n=1, requirement_results=results)[0].id == "flipkart-B"


def test_only_one_variant_per_model_in_top_results():
    a = _phone("A", title="Nova X (Blue, 128 GB)", rating=4.5, rating_count=2000)
    b = _phone("B", title="Nova X (Black, 256 GB)", rating=4.4, rating_count=2000)
    c = _phone("C", title="Nova Y (Blue, 128 GB)", rating=4.0, rating_count=2000)
    ranked = rank_products([a, b, c], top_n=3)
    assert len(ranked) == 2
    assert {p.title.split(" (")[0] for p in ranked} == {"Nova X", "Nova Y"}


# ---------- verifier: spec claims ----------


def _verify(claim, product):
    return verify_claim(claim, product, position=1, max_price=None, valid_call_ids={"call_002", "call_003"},
                        search_call_id="call_002", rank_call_id="call_003", total_ranked=3)


def _spec_claim(key, value, text, call="call_002"):
    return Claim(field="spec", key=key, value=value, text=text, source_tool_call_id=call)


def test_true_spec_claim_passes():
    phone = _phone(sections={"S": {"RAM": "8 GB", "Network Type": "5G"}})
    assert _verify(_spec_claim("ram_gb", 8, "It has 8 GB of RAM."), phone) is None
    assert _verify(_spec_claim("network_5g", True, "It supports 5G."), phone) is None


def test_wrong_spec_value_fails():
    phone = _phone(sections={"S": {"RAM": "8 GB"}})
    assert _verify(_spec_claim("ram_gb", 12, "It has 12 GB of RAM."), phone) is not None


def test_unknown_spec_key_fails():
    assert _verify(_spec_claim("nfc", True, "It has NFC."), _phone()) is not None


def test_conflicting_spec_cannot_be_claimed():
    conflicted = _earbuds(sections={"F": {"Noise Cancellation": "Yes", "Active Noise Cancellation": "No"}})
    assert _verify(_spec_claim("noise_cancellation", True, "It has noise cancellation."), conflicted) is not None


def test_spec_claim_without_key_fails():
    claim = Claim(field="spec", value=8, text="It has 8 GB.", source_tool_call_id="call_002")
    assert _verify(claim, _phone(sections={"S": {"RAM": "8 GB"}})) is not None


def test_wording_must_match_a_false_fact():
    phone = _phone(sections={"S": {"Network Type": "4G"}})
    assert _verify(_spec_claim("network_5g", False, "It has 5G."), phone) is not None
    assert _verify(_spec_claim("network_5g", False, "It does not have 5G."), phone) is None


def test_positive_fact_cannot_be_worded_negatively():
    phone = _phone(sections={"S": {"Network Type": "5G"}})
    assert _verify(_spec_claim("network_5g", True, "It does not support 5G."), phone) is not None


def test_spec_claim_must_cite_the_search_call():
    phone = _phone(sections={"S": {"RAM": "8 GB"}})
    assert _verify(_spec_claim("ram_gb", 8, "It has 8 GB of RAM.", call="call_003"), phone) is not None


def test_number_in_sentence_must_be_a_known_fact():
    phone = _phone(sections={"S": {"RAM": "8 GB"}})
    assert _verify(_spec_claim("ram_gb", 8, "It has 8 GB of RAM and 99 cameras."), phone) is not None