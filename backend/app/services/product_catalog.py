"""
ShopMate AI — Product Catalog Service (Phase 1, extracted for Phase 3, INR layer added)

Holds the in-memory cache of normalized products shared by the HTTP
router and the agent's search tool.

Fallback behavior (added after FakeStoreAPI returned a 521 outage):
if the live API call fails for any HTTP/network reason, we serve the
offline sample catalog (app/data/offline_catalog.py) instead of
crashing, and record that fact so callers can disclose it. While the
fallback is active the cache retries the live API after only
RETRY_AFTER_FALLBACK_SECONDS rather than waiting the full 5 minutes.

Currency: after normalizing, every product gets a rupee price
(app/services/currency.py) so the rest of the app only ever compares,
ranks and quotes rupees. Products already in INR pass through unchanged.
"""

import logging
import time

import httpx

from app.data.offline_catalog import OFFLINE_RAW_PRODUCTS
from app.normalizers.fakestore import normalize_fakestore_product
from app.schemas.product import Product
from app.services import currency, fakestore_client

logger = logging.getLogger("uvicorn.error")

CACHE_TTL_SECONDS = 300  # 5 minutes
RETRY_AFTER_FALLBACK_SECONDS = 30
_cache: dict = {"products": None, "fetched_at": 0.0, "ttl": CACHE_TTL_SECONDS, "used_fallback": False}


def last_fetch_used_fallback() -> bool:
    """True if the catalog currently being served is the offline sample, not live data."""
    return bool(_cache["used_fallback"])


async def get_all_normalized_products() -> list[Product]:
    """Returns cached normalized products (with rupee prices), refetching if stale; falls back to offline samples on failure."""
    now = time.time()
    is_cache_stale = (now - _cache["fetched_at"]) > _cache["ttl"]

    if _cache["products"] is None or is_cache_stale:
        try:
            raw_products = await fakestore_client.fetch_all_products()
            _cache["used_fallback"] = False
            _cache["ttl"] = CACHE_TTL_SECONDS
        except httpx.HTTPError as error:
            logger.warning("FakeStoreAPI unavailable (%s) — serving offline sample catalog", error)
            raw_products = OFFLINE_RAW_PRODUCTS
            _cache["used_fallback"] = True
            _cache["ttl"] = RETRY_AFTER_FALLBACK_SECONDS

        normalized = [normalize_fakestore_product(p) for p in raw_products]
        _cache["products"] = await currency.convert_products(normalized)
        _cache["fetched_at"] = now

    return _cache["products"]