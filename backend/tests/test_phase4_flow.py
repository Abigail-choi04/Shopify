"""
ShopMate AI — Phase 4 tests: SerpAPI client and the whole agent on a tiny fake snapshot

Run from the backend/ folder:   python -m pytest tests -q
Groq, SerpAPI and the exchange-rate service are all faked — no internet, no keys.
"""

import asyncio
import json

import httpx
import pytest
from conftest import flipkart_record

from app.agent import graph as graph_module
from app.schemas.product import Product
from app.services import currency, serpapi_client

# ---------- SerpAPI client ----------

SERP_DATA = {
    "shopping_results": [
        {"title": "Acme Phone 8GB", "extracted_price": 15999, "price": "₹15,999", "rating": 4.4, "reviews": 320,
         "product_link": "https://shop/x", "source": "ShopOne", "thumbnail": "https://img/1.jpg", "product_id": "p1"},
        {"title": "No price item", "price": None},
        {"title": "Acme Phone 8GB", "extracted_price": 15999, "product_id": "p1"},  # duplicate
    ]
}


class _FakeClient:
    calls = 0
    payload = SERP_DATA
    fail = False

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None):
        type(self).calls += 1
        if type(self).fail:
            raise httpx.ConnectError("down")
        request = httpx.Request("GET", url)
        return httpx.Response(200, json=type(self).payload, request=request)


@pytest.fixture
def serp(monkeypatch):
    _FakeClient.calls, _FakeClient.payload, _FakeClient.fail = 0, SERP_DATA, False
    monkeypatch.setenv("SERPAPI_ENABLED", "true")
    monkeypatch.setenv("SERPAPI_KEY", "test-key")
    monkeypatch.setattr(serpapi_client.httpx, "AsyncClient", _FakeClient)
    return _FakeClient


def test_parse_results_skips_priceless_and_duplicates():
    products = serpapi_client.parse_results(SERP_DATA, "smartphones", "2026-10-08")
    assert len(products) == 1
    p = products[0]
    assert (p.id, p.source, p.price, p.currency, p.merchant, p.rating_count) == ("serpapi-p1", "serpapi", 15999.0, "INR", "ShopOne", 320)
    assert p.spec_facts == {}


def test_disabled_without_flag_or_key(monkeypatch):
    monkeypatch.setenv("SERPAPI_ENABLED", "true")
    assert serpapi_client.is_enabled() is False  # key missing
    monkeypatch.setenv("SERPAPI_KEY", "k")
    monkeypatch.setenv("SERPAPI_ENABLED", "false")
    assert serpapi_client.is_enabled() is False


def test_search_is_cached_and_counted_once(serp):
    first = asyncio.run(serpapi_client.search_shopping("phone 8gb", "smartphones", 20000))
    second = asyncio.run(serpapi_client.search_shopping("phone 8gb", "smartphones", 20000))
    assert (first.cached, second.cached) == (False, True)
    assert serp.calls == 1
    assert serpapi_client.searches_used() == 1


def test_monthly_limit_stops_searches(serp, monkeypatch):
    monkeypatch.setenv("SERPAPI_MONTHLY_LIMIT", "1")
    asyncio.run(serpapi_client.search_shopping("one", "smartphones", None))
    with pytest.raises(serpapi_client.SerpQuotaExceeded):
        asyncio.run(serpapi_client.search_shopping("two", "smartphones", None))
    assert serp.calls == 1


def test_failed_request_is_not_counted(serp):
    serp.fail = True
    with pytest.raises(serpapi_client.SerpApiError):
        asyncio.run(serpapi_client.search_shopping("phone", "smartphones", None))
    assert serpapi_client.searches_used() == 0


def test_service_error_message_is_reported(serp):
    serp.payload = {"error": "Invalid API key."}
    with pytest.raises(serpapi_client.SerpApiError, match="Invalid API key"):
        asyncio.run(serpapi_client.search_shopping("phone", "smartphones", None))


# ---------- the whole agent on a fake snapshot ----------


def _phone_record(pid, ram, price, rating=4.3, count=2000, title=None):
    return flipkart_record(
        pid, title=title or f"Model {pid} ({ram} GB)", price=price, rating=rating, rating_count=count,
        sections={"Specs": {"RAM": f"{ram} GB", "Internal Storage": "128 GB", "Network Type": "5G"}},
    )


def _setup(monkeypatch, slug="smartphone", max_price=None, must_haves=("8GB RAM",)):
    async def fixed_rate(cur):
        return currency.FxRate("INR", 1.0, "", "native")

    monkeypatch.setattr(currency, "get_rate", fixed_rate)
    graph_module._compiled_graph = None

    async def fake_groq(system, user):
        if "planning component" in system:
            return {"category_slug": slug, "category_label": slug.title(), "max_price": max_price, "must_have_attributes": list(must_haves)}
        facts = json.loads(user.split("\n\n")[0])
        out = []
        for item in facts["products"]:
            claims = [{"field": "price", "value": item["price"], "text": f"Priced at ₹{item['price']:,.0f}.", "source_tool_call_id": item["fact_call_id"]}]
            if "ram_gb" in item["specs"]:
                claims.append({"field": "spec", "key": "ram_gb", "value": item["specs"]["ram_gb"]["value"],
                               "text": f"It has {item['specs']['ram_gb']['display']} of RAM.", "source_tool_call_id": item["fact_call_id"]})
            out.append({"product_id": item["product_id"], "claims": claims})
        return {"products": out}

    monkeypatch.setattr(graph_module, "call_groq_json", fake_groq)


def _trace_text(response):
    return " | ".join(step.text for step in response.trace)


def test_snapshot_search_filters_ranks_and_verifies(monkeypatch, write_snapshot):
    write_snapshot({"smartphones": [_phone_record("A", 8, 15000), _phone_record("B", 12, 18000), _phone_record("C", 4, 9000), _phone_record("D", 8, 17000, rating=3.9)]})
    _setup(monkeypatch, max_price=20000)
    response = asyncio.run(graph_module.run_agent("8GB RAM phone under 20000"))
    titles = " ".join(p.title for p in response.products)
    assert "Model C" not in titles  # 4 GB: the listing contradicts the requirement
    assert len(response.products) == 3
    assert "Flipkart snapshot" in response.dataSource
    assert response.verification.claimsChecked > 0
    assert response.verification.claimsVerified == response.verification.claimsChecked
    assert all(p.source.startswith("Flipkart") for p in response.products)


def test_requirements_that_remove_everything_are_named(monkeypatch, write_snapshot):
    write_snapshot({"smartphones": [_phone_record("A", 4, 9000), _phone_record("B", 6, 12000)]})
    _setup(monkeypatch)
    response = asyncio.run(graph_module.run_agent("8GB RAM phone"))
    assert response.products == []
    assert "8GB RAM" in _trace_text(response)


def test_category_outside_the_snapshot_says_so(monkeypatch, write_snapshot):
    write_snapshot({"smartphones": [_phone_record("A", 8, 15000)]})
    _setup(monkeypatch, slug="backpack", must_haves=())
    response = asyncio.run(graph_module.run_agent("a laptop backpack"))
    assert response.products == []
    assert "doesn't cover" in _trace_text(response)


def test_web_fallback_adds_unconfirmed_products(monkeypatch, write_snapshot, serp):
    write_snapshot({"smartphones": [_phone_record("A", 8, 15000)]})
    _setup(monkeypatch, max_price=20000)
    response = asyncio.run(graph_module.run_agent("8GB RAM phone under 20000"))
    assert any(p.source.startswith("Flipkart") for p in response.products)
    assert any(p.source.startswith("Google Shopping") for p in response.products)
    assert "Google Shopping" in _trace_text(response)
    web = next(p for p in response.products if p.source.startswith("Google Shopping"))
    assert not web.requirements or all(r.status != "met" for r in web.requirements)


def test_web_fallback_failure_is_reported_not_hidden(monkeypatch, write_snapshot, serp):
    serp.fail = True
    write_snapshot({"smartphones": [_phone_record("A", 8, 15000)]})
    _setup(monkeypatch)
    response = asyncio.run(graph_module.run_agent("8GB RAM phone"))
    assert len(response.products) == 1
    assert "could not be used" in _trace_text(response)


def test_fallback_is_not_used_when_switched_off(monkeypatch, write_snapshot):
    write_snapshot({"smartphones": [_phone_record("A", 8, 15000)]})
    _setup(monkeypatch)
    response = asyncio.run(graph_module.run_agent("8GB RAM phone"))
    assert "switched off" in _trace_text(response)