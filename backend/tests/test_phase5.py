"""
ShopMate AI — Phase 5 tests (no internet, no Groq key needed)

Run from the backend/ folder:   python -m pytest tests -q

Groq is replaced by a fake that returns scripted answers, and the
product API is forced to fail so the offline sample catalog is used.
That makes these tests fast and repeatable, and lets us deliberately
feed the verifier BAD claims to prove it catches them.
"""

import asyncio

import httpx

from app.agent import graph as graph_module
from app.agent.verifier import verify_claim
from app.schemas.agent import Claim
from app.schemas.product import Product
from app.services import currency, fakestore_client, product_catalog


def _product(**overrides) -> Product:
    data = dict(
        id="fakestore-1",
        source="fakestore",
        title="Test Headphones",
        category="electronics",
        price=100.0,
        currency="INR",
        rating=4.5,
        rating_count=200,
        raw={},
    )
    data.update(overrides)
    return Product(**data)


def _check(claim: Claim, product: Product | None = None, max_price=None):
    return verify_claim(
        claim,
        product or _product(),
        position=1,
        max_price=max_price,
        valid_call_ids={"call_001", "call_002", "call_003"},
        search_call_id="call_002",
        rank_call_id="call_003",
        total_ranked=3,
    )


# ---------- unit tests: the verifier itself ----------


def test_correct_claim_passes():
    claim = Claim(field="price", value=100.0, text="Priced at ₹100.00.", source_tool_call_id="call_002")
    assert _check(claim) is None


def test_wrong_value_fails():
    claim = Claim(field="rating", value=4.9, text="Rated 4.9 out of 5.", source_tool_call_id="call_002")
    assert "does not match" in _check(claim)


def test_invented_call_id_fails():
    claim = Claim(field="price", value=100.0, text="Priced at ₹100.", source_tool_call_id="call_999")
    assert "not a tool call" in _check(claim)


def test_wrong_call_id_fails():
    claim = Claim(field="price", value=100.0, text="Priced at ₹100.", source_tool_call_id="call_003")
    assert "must cite call_002" in _check(claim)


def test_unknown_field_fails():
    claim = Claim(field="battery_life", value=30, text="30 hours of battery.", source_tool_call_id="call_002")
    assert "unknown field" in _check(claim)


def test_invented_number_in_text_fails():
    claim = Claim(field="rating", value=4.5, text="Rated 4.5 with 30 hours of battery.", source_tool_call_id="call_002")
    assert "30" in _check(claim)


def test_within_budget_needs_a_budget():
    claim = Claim(field="within_budget", value=True, text="Within your budget.", source_tool_call_id="call_002")
    assert "no budget" in _check(claim, max_price=None)
    assert _check(claim, max_price=150.0) is None
    assert "above the budget" in _check(claim, max_price=50.0)


def test_only_rupee_symbol_is_allowed_in_sentences():
    dollar = Claim(field="price", value=100.0, text="Priced at $100.00.", source_tool_call_id="call_002")
    assert "uses '$'" in _check(dollar)
    rupee = Claim(field="price", value=100.0, text="Priced at ₹100.", source_tool_call_id="call_002")
    assert _check(rupee) is None


def test_price_claim_is_checked_against_the_rupee_price_not_the_listed_price():
    converted = _product(currency="USD", price=100.0, price_inr=9642.0, fx_rate=96.42, fx_as_of="2026-10-06", fx_source="live")
    rupees = Claim(field="price", value=9642.0, text="Priced at about ₹9,642.", source_tool_call_id="call_002")
    listed = Claim(field="price", value=100.0, text="Priced at about ₹100.", source_tool_call_id="call_002")
    assert _check(rupees, product=converted) is None
    assert "does not match the real rupee price" in _check(listed, product=converted)


def test_budget_is_compared_in_rupees_after_conversion():
    claim = Claim(field="within_budget", value=True, text="Within your budget.", source_tool_call_id="call_002")
    converted = _product(currency="USD", price=100.0, price_inr=9642.0, fx_rate=96.42, fx_as_of="2026-10-06", fx_source="live")
    assert _check(claim, product=converted, max_price=10000.0) is None
    assert "above the budget" in _check(claim, product=converted, max_price=5000.0)  # $100 is NOT under "5000"


def test_budget_cannot_be_compared_when_there_is_no_rupee_price():
    claim = Claim(field="within_budget", value=True, text="Within your budget.", source_tool_call_id="call_002")
    no_rate = _product(currency="XYZ")
    assert "cannot be compared" in _check(claim, product=no_rate, max_price=5000.0)


def test_rank_claim():
    ok = Claim(field="rank", value=1, text="Ranked #1 of 3.", source_tool_call_id="call_003")
    bad = Claim(field="rank", value=2, text="Ranked #2.", source_tool_call_id="call_003")
    assert _check(ok) is None
    assert "position" in _check(bad)


# ---------- flow tests: the whole graph with a fake Groq ----------


def _setup(monkeypatch, explain_answers, max_price=None):
    """Forces the offline catalog, fakes Groq, returns a list that records explain calls."""

    async def failing_fetch():
        raise httpx.ConnectError("forced failure for test")

    async def fixed_rate(cur):
        if cur.upper() == "INR":
            return currency.FxRate("INR", 1.0, "", "native")
        return currency.FxRate(cur.upper(), 96.0, "2026-10-06", "live")  # never touch the real FX service in tests

    monkeypatch.setattr(fakestore_client, "fetch_all_products", failing_fetch)
    monkeypatch.setattr(currency, "get_rate", fixed_rate)
    product_catalog._cache.update({"products": None, "fetched_at": 0.0, "ttl": 300, "used_fallback": False})
    graph_module._compiled_graph = None

    explain_prompts: list[str] = []
    answers = list(explain_answers)

    async def fake_groq(system_prompt, user_prompt):
        if "planning component" in system_prompt:
            return {
                "category_slug": "headphones",
                "category_label": "Electronics — Headphones",
                "max_price": max_price,
                "must_have_attributes": ["Active Noise Cancellation"],
            }
        explain_prompts.append(user_prompt)
        answer = answers.pop(0) if answers else {"products": []}
        # Answers may be a function of the facts so they can use the real product IDs.
        return answer(user_prompt) if callable(answer) else answer

    monkeypatch.setattr(graph_module, "call_groq_json", fake_groq)
    return explain_prompts


def _good_answer(facts_json: str) -> dict:
    import json

    facts = json.loads(facts_json.split("\n\n")[0])
    products = []
    for item in facts["products"]:
        products.append(
            {
                "product_id": item["product_id"],
                "claims": [
                    {
                        "field": "price",
                        "value": item["price"],
                        "text": f"Priced at about ₹{item['price']:,.0f}.",
                        "source_tool_call_id": facts["search_call_id"],
                    },
                    {
                        "field": "rank",
                        "value": item["rank"],
                        "text": f"Ranked #{item['rank']} of the candidates.",
                        "source_tool_call_id": facts["rank_call_id"],
                    },
                ],
            }
        )
    return {"products": products}


def _bad_answer(facts_json: str) -> dict:
    """Same as good, but the first product also gets an invented battery claim and a fake call ID."""
    answer = _good_answer(facts_json)
    first = answer["products"][0]["claims"]
    first.append(
        {"field": "rating", "value": 4.99, "text": "Rated 4.99 out of 5.", "source_tool_call_id": "call_002"}
    )
    first.append({"field": "price", "value": 1.0, "text": "Only ₹1.", "source_tool_call_id": "call_777"})
    return answer


def test_clean_run_has_no_retry(monkeypatch):
    prompts = _setup(monkeypatch, [_good_answer])
    response = asyncio.run(graph_module.run_agent("good headphones"))

    assert len(prompts) == 1  # explain ran once
    assert response.verification.retried is False
    assert response.verification.claimsDropped == 0
    assert response.verification.claimsChecked == response.verification.claimsVerified > 0
    assert all(p.claims for p in response.products)
    assert response.products[0].isTopPick
    texts = [step.text for step in response.trace]
    assert any("All" in t and "verified" in t for t in texts)
    assert any("can't be confirmed" in t for t in texts)  # must-have honesty note


def test_bad_claims_trigger_one_retry_then_pass(monkeypatch):
    prompts = _setup(monkeypatch, [_bad_answer, _good_answer])
    response = asyncio.run(graph_module.run_agent("good headphones"))

    assert len(prompts) == 2  # explain ran twice: original + one rewrite
    assert "failed verification" in prompts[1]  # the model was told what went wrong
    assert response.verification.retried is True
    assert response.verification.claimsDropped == 0
    assert any("Asking for one rewrite" in step.text for step in response.trace)


def test_still_bad_after_retry_gets_dropped(monkeypatch):
    prompts = _setup(monkeypatch, [_bad_answer, _bad_answer])
    response = asyncio.run(graph_module.run_agent("good headphones"))

    assert len(prompts) == 2  # never a third try
    assert response.verification.retried is True
    assert response.verification.claimsDropped == 2
    first = response.products[0]
    assert "4.99" not in first.reasoning and "₹1." not in first.reasoning  # bad claims never reach the shopper
    assert all(c.source_tool_call_id != "call_777" for c in first.claims)
    assert any("were dropped" in step.text or "dropped" in step.text for step in response.trace)


def test_malformed_model_output_falls_back_to_data_only(monkeypatch):
    prompts = _setup(monkeypatch, [{"unexpected": "shape"}])
    response = asyncio.run(graph_module.run_agent("good headphones"))

    assert len(prompts) == 1
    assert response.products  # still returns recommendations
    assert all("out of 5" in p.reasoning for p in response.products if p.rating is not None)
    assert any("malformed" in step.text for step in response.trace)


def test_usd_catalog_is_converted_to_rupees_and_disclosed(monkeypatch):
    _setup(monkeypatch, [_good_answer])
    response = asyncio.run(graph_module.run_agent("good headphones"))

    texts = [step.text for step in response.trace]
    assert any("converted to rupees at ₹96.00" in t for t in texts)  # conversion is never silent
    for product in response.products:
        assert product.attributes["Price"].startswith("≈ ₹")  # approximate, in rupees
        assert product.currency == "INR" and product.priceIsApproximate is True
        assert product.listedPrice.startswith("$")  # the original listing is still shown
        assert "₹96.00" in product.priceNote
        assert "$" not in product.reasoning  # claims speak rupees only


def test_budget_in_rupees_filters_converted_prices(monkeypatch):
    _setup(monkeypatch, [_good_answer], max_price=12000.0)
    response = asyncio.run(graph_module.run_agent("headphones under 12000"))

    assert response.parsedIntent.budget == "₹12,000"
    assert response.products
    for product in response.products:
        assert product.price <= 12000.0  # price is the RUPEE price; $329 (= ₹31,584) is correctly excluded
    assert "Sample 27-inch Gaming Monitor" not in [p.title for p in response.products]


def test_budget_claims_survive_verification_after_conversion(monkeypatch):
    def with_budget(facts_json):
        import json

        answer = _good_answer(facts_json)
        facts = json.loads(facts_json.split("\n\n")[0])
        for item, entry in zip(facts["products"], answer["products"]):
            entry["claims"].append(
                {
                    "field": "within_budget",
                    "value": True,
                    "text": "Within your budget.",
                    "source_tool_call_id": facts["search_call_id"],
                }
            )
        return answer

    prompts = _setup(monkeypatch, [with_budget], max_price=12000.0)
    response = asyncio.run(graph_module.run_agent("headphones under 12000"))

    assert len(prompts) == 1  # no rewrite needed
    assert response.verification.claimsDropped == 0
    assert all(any(c.field == "within_budget" for c in p.claims) for p in response.products)