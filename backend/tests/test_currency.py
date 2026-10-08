"""
ShopMate AI — Currency layer tests (no internet needed)

Run from the backend/ folder:   python -m pytest tests -q

The exchange-rate service is replaced by a fake HTTP transport, so these
tests check OUR behaviour (live rate, caching, stale reuse, fallback,
rounding, disclosure text) without depending on the real service.
"""

import asyncio

import httpx
import pytest

from app.agent.tools import rank_products
from app.schemas.product import Product
from app.services import currency


@pytest.fixture(autouse=True)
def _clean_rate_caches():
    currency._rate_cache.clear()
    currency._last_failure.clear()
    yield
    currency._rate_cache.clear()
    currency._last_failure.clear()


def _fake_service(monkeypatch, handler):
    """Makes currency.py talk to `handler` instead of the real internet."""
    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(currency.httpx, "AsyncClient", factory)


def _product(**overrides) -> Product:
    data = dict(
        id="x-1", source="fakestore", title="Thing", category="electronics",
        price=100.0, currency="USD", rating=4.0, rating_count=10, raw={},
    )
    data.update(overrides)
    return Product(**data)


# ---------- Indian number formatting ----------


def test_format_inr_uses_indian_grouping():
    assert currency.format_inr(0) == "₹0"
    assert currency.format_inr(999) == "₹999"
    assert currency.format_inr(5000) == "₹5,000"
    assert currency.format_inr(109999) == "₹1,09,999"
    assert currency.format_inr(1234567) == "₹12,34,567"
    assert currency.format_inr(10464.4) == "₹10,464"
    assert currency.format_inr(10464.6) == "₹10,465"


def test_format_listed_price_keeps_original_currency():
    assert currency.format_listed_price(109, "USD") == "$109.00"
    assert currency.format_listed_price(5, "JPY") == "5.00 JPY"


# ---------- live rate, caching, failure handling ----------


def test_live_rate_is_fetched_then_cached(monkeypatch):
    calls = []

    def handler(request: httpx.Request):
        calls.append(request.url)
        return httpx.Response(200, json={"amount": 1.0, "base": "USD", "date": "2026-10-06", "rates": {"INR": 96.42}})

    _fake_service(monkeypatch, handler)

    first = asyncio.run(currency.get_rate("USD"))
    second = asyncio.run(currency.get_rate("usd"))

    assert (first.rate, first.as_of, first.source) == (96.42, "2026-10-06", "live")
    assert second == first
    assert len(calls) == 1  # the second lookup came from the cache
    assert "base=USD" in str(calls[0]) and "symbols=INR" in str(calls[0])


def test_inr_needs_no_lookup(monkeypatch):
    def handler(request):
        raise AssertionError("no network call should happen for INR")

    _fake_service(monkeypatch, handler)
    fx = asyncio.run(currency.get_rate("INR"))
    assert fx.rate == 1.0 and fx.source == "native"


def test_failure_without_history_uses_labelled_fallback(monkeypatch):
    _fake_service(monkeypatch, lambda request: httpx.Response(503))
    fx = asyncio.run(currency.get_rate("USD"))
    assert fx.source == "fallback"
    assert fx.rate == currency.FALLBACK_RATES_TO_INR["USD"][0]


def test_failure_with_old_rate_reuses_it_as_stale(monkeypatch):
    good = currency.FxRate("USD", 95.5, "2026-10-01", "live")
    currency._rate_cache["USD"] = (good, 0.0)  # fetched "long ago", so the cache is expired
    _fake_service(monkeypatch, lambda request: httpx.Response(500))

    fx = asyncio.run(currency.get_rate("USD"))
    assert (fx.rate, fx.as_of, fx.source) == (95.5, "2026-10-01", "stale_cache")


def test_garbage_response_is_treated_as_failure(monkeypatch):
    _fake_service(monkeypatch, lambda request: httpx.Response(200, json={"unexpected": True}))
    fx = asyncio.run(currency.get_rate("USD"))
    assert fx.source == "fallback"


def test_unknown_currency_with_no_rate_returns_none(monkeypatch):
    _fake_service(monkeypatch, lambda request: httpx.Response(404))
    assert asyncio.run(currency.get_rate("XYZ")) is None


def test_failed_lookup_is_not_retried_immediately(monkeypatch):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(500)

    _fake_service(monkeypatch, handler)
    asyncio.run(currency.get_rate("USD"))
    asyncio.run(currency.get_rate("USD"))
    assert len(calls) == 1


# ---------- converting products ----------


def test_usd_product_gets_rupee_price_and_records_the_rate():
    fx = currency.FxRate("USD", 96.42, "2026-10-06", "live")
    converted = currency.convert_product(_product(price=109.0), fx)

    assert converted.price == 109.0 and converted.currency == "USD"  # the source's price is untouched
    assert converted.price_inr == pytest.approx(10509.78)
    assert (converted.fx_rate, converted.fx_as_of, converted.fx_source) == (96.42, "2026-10-06", "live")


def test_inr_product_is_not_converted():
    converted = currency.convert_product(_product(price=1299.0, currency="INR"), None)
    assert converted.price_inr == 1299.0
    assert converted.fx_rate is None


def test_product_with_no_rate_has_no_rupee_price():
    converted = currency.convert_product(_product(currency="XYZ"), None)
    assert converted.price_inr is None


def test_inr_product_gets_rupee_price_automatically():
    assert _product(price=250.0, currency="INR").price_inr == 250.0


def test_convert_products_looks_each_currency_up_once(monkeypatch):
    calls = []

    async def fake_get_rate(cur):
        calls.append(cur)
        return currency.FxRate(cur, 96.0, "2026-10-06", "live")

    monkeypatch.setattr(currency, "get_rate", fake_get_rate)
    result = asyncio.run(currency.convert_products([_product(), _product(id="x-2"), _product(id="x-3", currency="INR")]))

    assert calls == ["USD", "INR"]
    assert all(p.price_inr is not None for p in result)


# ---------- disclosure text ----------


def test_describe_conversions_for_each_rate_source():
    live = currency.convert_product(_product(), currency.FxRate("USD", 96.42, "2026-10-06", "live"))
    stale = currency.convert_product(_product(), currency.FxRate("USD", 95.5, "2026-10-01", "stale_cache"))
    fallback = currency.convert_product(_product(), currency.FxRate("USD", 96.0, "2026-10-06", "fallback"))

    assert "₹96.42" in currency.describe_conversions([live])[0] and "approximate" in currency.describe_conversions([live])[0]
    assert "last rate retrieved" in currency.describe_conversions([stale])[0]
    assert "fixed fallback rate" in currency.describe_conversions([fallback])[0]
    assert currency.describe_conversions([_product(currency="INR")]) == []


# ---------- ranking is not drowned out by rupee-sized prices ----------


def test_rating_beats_price_even_with_large_rupee_amounts():
    # Many reviews each, so the ratings are trustworthy (Phase 4 weights ratings by review count).
    cheap_worse = _product(id="cheap", currency="INR", price=1000.0, rating=4.0, rating_count=5000)
    pricey_better = _product(id="pricey", currency="INR", price=100000.0, rating=4.5, rating_count=5000)
    ranked = rank_products([cheap_worse, pricey_better])
    assert ranked[0].id == "pricey"


def test_price_breaks_a_rating_tie():
    cheap = _product(id="cheap", currency="INR", price=1000.0, rating=4.5)
    pricey = _product(id="pricey", currency="INR", price=5000.0, rating=4.5)
    assert [p.id for p in rank_products([pricey, cheap])] == ["cheap", "pricey"]