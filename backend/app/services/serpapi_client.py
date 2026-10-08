"""
ShopMate AI — SerpAPI Fallback (Phase 4)

A backup source for when the saved Flipkart snapshot has too few matches
(or does not cover the category at all). It asks Google Shopping, aimed
at India, through SerpAPI (https://serpapi.com).

What it gives:  title, price, shop name, rating, review count, link, image.
What it does NOT give: any spec data. So products from here can never
confirm a requirement like "noise cancellation"; the agent says so.

The free plan allows 250 searches a month, so this module is careful:
  - OFF unless SERPAPI_ENABLED=true and SERPAPI_KEY is set (in .env)
  - every answer is saved to disk and reused for SERPAPI_CACHE_DAYS days,
    so the same question never costs a second search
  - a monthly counter stops it at SERPAPI_MONTHLY_LIMIT (default 200,
    leaving a safety margin) and the agent tells the shopper it stopped
  - a failed request is not counted

Settings (.env):
  SERPAPI_ENABLED=false          set to true to switch the fallback on
  SERPAPI_KEY=...                from serpapi.com -> Dashboard
  SERPAPI_MONTHLY_LIMIT=200
  SERPAPI_CACHE_DAYS=7

Files it writes (inside the git-ignored data_private folder):
  serpapi_usage.json, serpapi_cache.json
"""

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

from app.schemas.product import Product
from app.services import snapshot_store

logger = logging.getLogger("uvicorn.error")

SERPAPI_URL = "https://serpapi.com/search.json"
REQUEST_TIMEOUT_SECONDS = 20.0
MAX_PRODUCTS = 15

CURRENCY_MARKERS = [("₹", "INR"), ("rs.", "INR"), ("rs ", "INR"), ("inr", "INR"), ("$", "USD"), ("€", "EUR"), ("£", "GBP")]


class SerpApiError(Exception):
    """The web fallback could not be used; the message is safe to show in the trace."""


class SerpQuotaExceeded(SerpApiError):
    pass


@dataclass
class SerpResult:
    products: list[Product]
    cached: bool
    searches_used: int
    searches_limit: int


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def is_enabled() -> bool:
    return _truthy(os.getenv("SERPAPI_ENABLED")) and bool(os.getenv("SERPAPI_KEY"))


def monthly_limit() -> int:
    try:
        return int(os.getenv("SERPAPI_MONTHLY_LIMIT", "200"))
    except ValueError:
        return 200


def cache_days() -> float:
    try:
        return float(os.getenv("SERPAPI_CACHE_DAYS", "7"))
    except ValueError:
        return 7.0


def _folder() -> Path:
    return snapshot_store.snapshot_dir()


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
    except OSError as error:
        logger.warning("Could not save %s (%s)", path.name, error)


def _month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def searches_used() -> int:
    usage = _read_json(_folder() / "serpapi_usage.json", {})
    return int(usage.get("count", 0)) if usage.get("month") == _month() else 0


def _record_search() -> int:
    count = searches_used() + 1
    _write_json(_folder() / "serpapi_usage.json", {"month": _month(), "count": count})
    return count


def _detect_currency(price_text: str) -> str:
    lowered = (price_text or "").lower()
    for marker, currency in CURRENCY_MARKERS:
        if marker in lowered:
            return currency
    return "INR"  # the search is aimed at India (gl=in), so an unmarked price is rupees


def _price_value(item: dict) -> float | None:
    extracted = item.get("extracted_price")
    if isinstance(extracted, (int, float)) and extracted > 0:
        return float(extracted)
    match = re.search(r"\d[\d,]*\.?\d*", str(item.get("price") or ""))
    if match:
        try:
            value = float(match.group(0).replace(",", ""))
            return value if value > 0 else None
        except ValueError:
            return None
    return None


def parse_results(data: dict, category: str, captured_on: str) -> list[Product]:
    products: list[Product] = []
    seen: set[str] = set()
    for item in data.get("shopping_results") or []:
        title = str(item.get("title") or "").strip()
        price = _price_value(item)
        if not title or price is None:
            continue
        link = item.get("product_link") or item.get("link")
        identity = str(item.get("product_id") or hashlib.sha1((link or title).encode("utf-8")).hexdigest()[:12])
        if identity in seen:
            continue
        seen.add(identity)

        reviews = item.get("reviews")
        rating = item.get("rating")
        products.append(
            Product(
                id=f"serpapi-{identity}",
                source="serpapi",
                title=title,
                category=category,
                price=price,
                currency=_detect_currency(str(item.get("price") or "")),
                image_url=item.get("thumbnail"),
                rating=float(rating) if isinstance(rating, (int, float)) and rating > 0 else None,
                rating_count=int(reviews) if isinstance(reviews, (int, float)) and reviews > 0 else None,
                merchant=item.get("source"),
                url=link,
                captured_at=captured_on,
                raw=item,
            )
        )
        if len(products) >= MAX_PRODUCTS:
            break
    return products


async def search_shopping(query: str, category: str, max_price: float | None) -> SerpResult:
    """Google Shopping (India) results as Products. Raises SerpApiError / SerpQuotaExceeded."""
    if not is_enabled():
        raise SerpApiError("the web fallback is switched off")

    today = date.today().isoformat()
    key = f"{query.strip().lower()}|{int(max_price) if max_price else ''}"
    cache_path = _folder() / "serpapi_cache.json"
    cache = _read_json(cache_path, {})
    entry = cache.get(key)
    limit = monthly_limit()

    if entry and (time.time() - float(entry.get("fetched_at", 0))) < cache_days() * 86400:
        return SerpResult(parse_results(entry["data"], category, entry.get("captured_on", today)), True, searches_used(), limit)

    used = searches_used()
    if used >= limit:
        raise SerpQuotaExceeded(f"the monthly limit of {limit} web searches has been reached")

    params = {
        "engine": "google_shopping",
        "q": query,
        "gl": "in",
        "hl": "en",
        "google_domain": "google.co.in",
        "api_key": os.getenv("SERPAPI_KEY", ""),
    }
    if max_price:
        params["max_price"] = int(max_price)

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(SERPAPI_URL, params=params)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise SerpApiError(f"the web search request failed ({type(error).__name__})") from error

    if isinstance(data, dict) and data.get("error") and not data.get("shopping_results"):
        raise SerpApiError(f"the web search service said: {data['error']}")

    used = _record_search()
    cache[key] = {"fetched_at": time.time(), "captured_on": today, "data": {"shopping_results": data.get("shopping_results") or []}}
    _write_json(cache_path, cache)
    return SerpResult(parse_results(data, category, today), False, used, limit)