"""
ShopMate AI — Currency Layer (INR for Indian shoppers)

Everything the shopper sees, and everything the agent compares (budget,
ranking, claims), is in rupees. Two ways a product gets a rupee price:

1. Its source already lists INR (e.g. an Indian retailer's data) —
   nothing to convert, nothing to disclose. This is the preferred path.
2. Its source lists another currency (e.g. FakeStoreAPI in USD) — we
   convert it using a LIVE exchange rate and record exactly which rate
   was used, so the conversion is never silent and never a made-up number.

Exchange rates change, so no rate is hardcoded as "the" rate:
- Live rate: Frankfurter (https://frankfurter.dev, free, no API key,
  central-bank reference rates updated once per working day).
  Request:  GET https://api.frankfurter.dev/v1/latest?base=USD&symbols=INR
  Response: {"amount":1.0,"base":"USD","date":"2026-10-06","rates":{"INR":96.42}}
- Cached for a few hours, so one chat request doesn't mean one rate lookup.
- If the lookup fails: reuse the last good rate ("stale_cache"), else a
  clearly-labelled fixed fallback rate ("fallback"). The trace says which.

Because the reference rate itself moves only once a day, converted prices
are always labelled approximate ("≈") — the shop's real rupee price can
differ by a small amount, and we say so rather than imply exactness.
"""

import logging
import time
from dataclasses import dataclass

import httpx

from app.schemas.product import Product

logger = logging.getLogger("uvicorn.error")

BASE_CURRENCY = "INR"
SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}

FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"
RATE_CACHE_SECONDS = 3 * 60 * 60  # reuse a fetched rate for 3 hours
RETRY_AFTER_FAILURE_SECONDS = 60  # after a failed lookup, don't hammer the service
REQUEST_TIMEOUT_SECONDS = 5.0

# Used ONLY when the live lookup fails and there is no earlier good rate to reuse.
# Rupees per 1 unit of the currency, with the date it was taken from. Update these
# occasionally; they are a safety net, not the normal path.
FALLBACK_RATES_TO_INR: dict[str, tuple[float, str]] = {
    "USD": (96.0, "2026-10-06"),
}


@dataclass(frozen=True)
class FxRate:
    currency: str  # the currency being converted FROM
    rate: float  # rupees per 1 unit of `currency`
    as_of: str  # date of the rate
    source: str  # "live" | "stale_cache" | "fallback"


_rate_cache: dict[str, tuple[FxRate, float]] = {}  # currency -> (rate, time fetched)
_last_failure: dict[str, float] = {}  # currency -> time of last failed lookup


def format_inr(amount: float) -> str:
    """Whole rupees with Indian digit grouping: 109999 -> '₹1,09,999'."""
    whole = int(round(amount))
    sign = "-" if whole < 0 else ""
    digits = str(abs(whole))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups + [tail])
    return f"{sign}₹{digits}"


def format_listed_price(amount: float, currency: str) -> str:
    """A price in its ORIGINAL currency, e.g. '$109.00' (or '109.00 JPY' if we have no symbol)."""
    symbol = SYMBOLS.get(currency.upper())
    return f"{symbol}{amount:,.2f}" if symbol else f"{amount:,.2f} {currency.upper()}"


async def get_rate(currency: str) -> FxRate | None:
    """Rupees per 1 unit of `currency`. Never raises; returns None only if no rate exists at all."""
    currency = currency.upper()
    if currency == BASE_CURRENCY:
        return FxRate(BASE_CURRENCY, 1.0, "", "native")

    now = time.time()
    cached = _rate_cache.get(currency)
    if cached and (now - cached[1]) < RATE_CACHE_SECONDS:
        return cached[0]

    recently_failed = (now - _last_failure.get(currency, 0.0)) < RETRY_AFTER_FAILURE_SECONDS
    if not recently_failed:
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.get(FRANKFURTER_URL, params={"base": currency, "symbols": BASE_CURRENCY})
                response.raise_for_status()
                data = response.json()
            rate = float(data["rates"][BASE_CURRENCY])
            if rate <= 0:
                raise ValueError("non-positive exchange rate")
            fx = FxRate(currency, rate, str(data["date"]), "live")
            _rate_cache[currency] = (fx, now)
            _last_failure.pop(currency, None)
            return fx
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as error:
            logger.warning("Live %s->INR rate unavailable (%s)", currency, error)
            _last_failure[currency] = now

    if cached:  # an older good rate beats a fixed number
        return FxRate(currency, cached[0].rate, cached[0].as_of, "stale_cache")
    if currency in FALLBACK_RATES_TO_INR:
        rate, as_of = FALLBACK_RATES_TO_INR[currency]
        return FxRate(currency, rate, as_of, "fallback")
    return None


def convert_product(product: Product, fx: FxRate | None) -> Product:
    """Returns a copy of the product with its rupee price (and the rate used) filled in."""
    if product.currency.upper() == BASE_CURRENCY:
        return product.model_copy(update={"price_inr": round(product.price, 2)})
    if fx is None:
        return product  # no rate at all: price_inr stays None and callers disclose it
    return product.model_copy(
        update={
            "price_inr": round(product.price * fx.rate, 2),
            "fx_rate": fx.rate,
            "fx_as_of": fx.as_of,
            "fx_source": fx.source,
        }
    )


async def convert_products(products: list[Product]) -> list[Product]:
    """Adds rupee prices to a list of products, looking each currency's rate up once."""
    rates: dict[str, FxRate | None] = {}
    converted = []
    for product in products:
        currency = product.currency.upper()
        if currency not in rates:
            rates[currency] = await get_rate(currency)
        converted.append(convert_product(product, rates[currency]))
    return converted


def describe_conversions(products: list[Product]) -> list[str]:
    """Plain-English trace lines explaining every conversion that was applied (empty if none)."""
    seen: dict[tuple, Product] = {}
    for product in products:
        if product.fx_rate is not None:
            seen[(product.currency.upper(), product.fx_rate, product.fx_as_of, product.fx_source)] = product

    notes = []
    for (currency, rate, as_of, source), _ in seen.items():
        symbol = SYMBOLS.get(currency, currency + " ")
        if source == "live":
            notes.append(
                f"Prices listed in {currency} were converted to rupees at ₹{rate:.2f} per {symbol}1 "
                f"(Frankfurter central-bank rate dated {as_of}). Converted amounts are approximate; "
                "the shop's own rupee price may differ slightly."
            )
        elif source == "stale_cache":
            notes.append(
                f"The live {currency}→INR rate could not be fetched, so the last rate retrieved "
                f"(₹{rate:.2f} per {symbol}1, dated {as_of}) was used. Converted amounts are approximate."
            )
        else:
            notes.append(
                f"The live {currency}→INR rate could not be fetched, so a fixed fallback rate of "
                f"₹{rate:.2f} per {symbol}1 (as of {as_of}) was used. Converted amounts may be off by a few rupees."
            )
    return notes