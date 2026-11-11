"""
ShopMate AI — tests: replanning never gives up a brand the shopper named, and the offline replanning measurement

Run from the backend/ folder:   python -m pytest tests -q
"""

import asyncio

from conftest import flipkart_record

from app.agent import replan
from app.agent.requirements import mentions_brand
from app.schemas.intent import ParsedIntent
from app.services import snapshot_store
from evaluation import offline_eval


def _phone(pid, ram, price, brand):
    return flipkart_record(
        pid, title=f"{brand} Model {pid} ({ram} GB)", price=price, brand=brand, rating=4.3, rating_count=2000,
        sections={"Specs": {"RAM": f"{ram} GB", "Internal Storage": "128 GB", "Network Type": "5G", "Brand": brand}},
    )


def _intent(max_price, must_haves):
    return ParsedIntent(category_slug="smartphone", category_label="Smartphone", max_price=max_price,
                        must_have_attributes=list(must_haves), raw_query="q")


def test_brand_requirements_are_recognised():
    assert mentions_brand("Samsung", {"samsung"}) is True
    assert mentions_brand("iPhone", set()) is True  # a well-known model name counts as its brand
    assert mentions_brand("8GB RAM", {"samsung"}) is False


def test_brand_is_never_offered_as_something_to_drop(write_snapshot):
    write_snapshot({"smartphones": [_phone("A", 4, 9000, "Samsung"), _phone("B", 8, 9500, "Acme")]})
    snapshot = snapshot_store.load_snapshot(force=True)
    options = replan.build_options(snapshot.category("smartphones"), _intent(10000, ["Samsung", "8GB RAM"]), snapshot.brands("smartphones"))
    dropped = [o.requirement for o in options if o.kind == "drop_requirement"]
    assert "Samsung" not in dropped
    assert "8GB RAM" in dropped  # the Samsung phone (4GB) comes back if the RAM requirement is given up


def test_offline_replanning_measurement(write_snapshot):
    write_snapshot({"smartphones": [_phone("A", 4, 9000, "Acme"), _phone("B", 8, 10400, "Acme")]})
    queries = [
        {"id": "r1", "type": "impossible", "query": "q", "gold": {"category_slug": "smartphone", "max_price": 10000, "must_haves": ["8GB RAM"]}},  # a small raise fixes it
        {"id": "r2", "type": "impossible", "query": "q", "gold": {"category_slug": "smartphone", "max_price": 5000, "must_haves": ["8GB RAM"]}},  # nothing costs under ₹5,000: nothing to loosen
        {"id": "ok", "type": "easy", "query": "q", "gold": {"category_slug": "smartphone", "max_price": 20000, "must_haves": ["4GB RAM"]}},  # fine already
        {"id": "oos", "type": "out_of_scope", "query": "q", "gold": {"category_slug": "backpack", "max_price": None, "must_haves": []}},
    ]
    rows = [r for r in [asyncio.run(offline_eval.replan_one(q)) for q in queries] if r is not None]
    assert [r["id"] for r in rows] == ["r1", "r2"]  # only the two that came back empty
    assert rows[0]["rescued"] is True and rows[0]["steps"][0]["kind"] == "raise_budget"
    assert rows[1]["rescued"] is False
    summary = offline_eval.summarize_replanning(rows, len(queries))
    assert (summary["needed_replanning"], summary["rescued"], summary["rescued_pct_of_needed"]) == (2, 1, 50.0)
    assert summary["not_rescued_ids"] == ["r2"]