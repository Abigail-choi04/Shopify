"""
ShopMate AI — tests: verifier demo ("inject an error") and compare-two-products

Run from the backend/ folder:   python -m pytest tests -q
Groq and the exchange-rate service are faked; no internet, no keys.
"""

import asyncio
import json

import pytest
from conftest import flipkart_record
from fastapi.testclient import TestClient

from app.agent import graph as graph_module
from app.agent.demo import tamper_one_claim
from app.agent.verifier import verify_claim
from app.main import app
from app.schemas.agent import Claim
from app.services import compare, currency, snapshot_store


def _phone(pid, ram, price, rating=4.3, count=2000, battery="5000 mAh", five_g="5G"):
    return flipkart_record(
        pid, title=f"Model {pid} ({ram} GB)", price=price, rating=rating, rating_count=count,
        sections={"Specs": {"RAM": f"{ram} GB", "Internal Storage": "128 GB", "Network Type": five_g, "Battery Capacity": battery}},
    )


# ---------- verifier demo ----------


def _product(write_snapshot, price=1499):
    write_snapshot({"earphones": [flipkart_record("A", title="Nova Buds", price=price, rating=4.2)]})
    return snapshot_store.load_snapshot(force=True).category("earphones")[0]


def test_tamper_changes_a_price_claim_to_a_believable_lie(write_snapshot):
    product = _product(write_snapshot)
    proposed = {product.id: [Claim(field="price", value=1499, text="Priced at ₹1,499.", source_tool_call_id="call_001")]}
    new, info = tamper_one_claim(proposed, [product])
    altered = new[product.id][0]
    assert altered.value == 900 and altered.text == "Costs ₹900." and info["originalText"] == "Priced at ₹1,499."
    assert proposed[product.id][0].value == 1499  # the original draft is not modified in place


def test_checker_rejects_the_tampered_claim_but_accepts_the_original(write_snapshot):
    product = _product(write_snapshot)
    good = Claim(field="price", value=1499, text="Priced at ₹1,499.", source_tool_call_id="call_001")
    new, _ = tamper_one_claim({product.id: [good]}, [product])
    check = lambda claim: verify_claim(claim, product, 1, None, {"call_001"}, "call_001", "call_002", 1)  # noqa: E731
    assert check(good) is None
    assert "does not match the real rupee price" in check(new[product.id][0])


def test_tamper_falls_back_to_rating_and_does_nothing_without_a_suitable_claim(write_snapshot):
    product = _product(write_snapshot)
    rating = Claim(field="rating", value=4.2, text="Rated 4.2 out of 5.", source_tool_call_id="call_001")
    new, info = tamper_one_claim({product.id: [rating]}, [product])
    assert new[product.id][0].value == 3.2 and info is not None
    other = Claim(field="category", value="earphones", text="It is earphones.", source_tool_call_id="call_001")
    unchanged, none_info = tamper_one_claim({product.id: [other]}, [product])
    assert none_info is None and unchanged[product.id][0].text == "It is earphones."


def _agent(monkeypatch, write_snapshot):
    write_snapshot({"smartphones": [_phone("A", 8, 15000)]})

    async def fixed_rate(cur):
        return currency.FxRate("INR", 1.0, "", "native")

    monkeypatch.setattr(currency, "get_rate", fixed_rate)
    graph_module._compiled_graph = None

    async def fake_groq(system, user):
        if "planning component" in system:
            return {"category_slug": "smartphone", "category_label": "Smartphone", "max_price": None, "must_have_attributes": []}
        facts = json.loads(user.split("\n\n")[0])
        return {"products": [
            {"product_id": item["product_id"], "claims": [
                {"field": "price", "value": item["price"], "text": f"Priced at ₹{item['price']:,.0f}.", "source_tool_call_id": item["fact_call_id"]}
            ]} for item in facts["products"]
        ]}

    monkeypatch.setattr(graph_module, "call_groq_json", fake_groq)


def test_demo_mode_end_to_end_the_checker_catches_it_and_the_model_rewrites(monkeypatch, write_snapshot):
    _agent(monkeypatch, write_snapshot)
    response = asyncio.run(graph_module.run_agent("phone", allow_clarification=False, demo_tamper=True))
    demo = response.demoTamper
    assert demo is not None and demo.caught and demo.rewritten
    assert demo.originalText == "Priced at ₹15,000." and demo.alteredText == "Costs ₹9,000."
    assert "does not match the real rupee price" in demo.verdict
    texts = " ".join(step.text for step in response.trace)
    assert "DEMO MODE" in texts and "The checker rejected the altered claim" in texts
    assert response.verification.retried is True and response.verification.claimsDropped == 0
    assert "Priced at ₹15,000" in response.products[0].reasoning  # the final answer has the correct claim


def test_demo_mode_is_off_by_default(monkeypatch, write_snapshot):
    _agent(monkeypatch, write_snapshot)
    response = asyncio.run(graph_module.run_agent("phone", allow_clarification=False))
    assert response.demoTamper is None and response.verification.retried is False


# ---------- compare two products ----------


@pytest.fixture
def client(write_snapshot):
    write_snapshot({
        "smartphones": [
            _phone("A", 8, 15000, rating=4.4, count=3000, battery="5000 mAh"),
            _phone("B", 12, 18000, rating=4.1, count=500, battery="6000 mAh"),
            _phone("C", 8, 16000, rating=4.4, count=100, battery="5000 mAh", five_g="4G"),
        ],
        "earphones": [flipkart_record("E", title="Nova Buds", price=1499)],
    })
    return TestClient(app)


def _compare(client, a="flipkart-A", b="flipkart-B"):
    return client.post("/compare", json={"product_ids": [a, b]})


def test_compare_names_a_winner_only_where_it_is_clear(client):
    body = _compare(client).json()
    rows = {r["label"]: r for r in body["rows"]}
    assert rows["Price"]["winner"] == "a" and rows["Price"]["a"] == "₹15,000"
    assert rows["Rating"]["winner"] == "a"  # 4.4 vs 4.1
    assert rows["RAM"]["winner"] == "b" and rows["Battery"]["winner"] == "b"
    assert rows["Reviews"]["winner"] is None  # shown, never judged
    assert body["aWins"] + body["bWins"] + body["ties"] == sum(1 for r in body["rows"] if r["winner"])
    assert any("cheaper" in s for s in body["summary"])


def test_equal_ratings_and_values_are_ties_and_missing_facts_decide_nothing(client):
    body = _compare(client, "flipkart-A", "flipkart-C").json()
    rows = {r["label"]: r for r in body["rows"]}
    assert rows["Rating"]["winner"] == "tie" and rows["RAM"]["winner"] == "tie"
    assert rows["5G"]["winner"] == "a"
    other = {r["label"]: r for r in _compare(client).json()["rows"]}
    assert other["Rear camera"]["a"] == "Not listed" and other["Rear camera"]["winner"] is None
    assert "Rear camera" in " ".join(_compare(client).json()["summary"])  # listed as "not compared"


def test_compare_errors_are_plain(client):
    assert _compare(client, "flipkart-A", "flipkart-A").json()["detail"]["code"] == "need_two"
    assert _compare(client, "flipkart-A", "flipkart-ZZZ").status_code == 404
    different = _compare(client, "flipkart-A", "flipkart-E")
    assert different.status_code == 422 and different.json()["detail"]["code"] == "different_categories"
    web = _compare(client, "flipkart-A", "serpapi-1")
    assert web.status_code == 422 and web.json()["detail"]["code"] == "unsupported_source"
    assert client.post("/compare", json={"product_ids": ["flipkart-A"]}).json()["detail"]["code"] == "need_two"