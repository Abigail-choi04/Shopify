"""
ShopMate AI — FakeStoreAPI Client (Phase 1)

Thin wrapper around FakeStoreAPI's HTTP endpoints. No normalization
happens here — this file only knows how to talk to FakeStoreAPI and
hand back raw JSON. Normalization lives in app/normalizers/fakestore.py.

Why keep these separate? In Phase 4 we add real retailer APIs
(RapidAPI, MYSTORE). Each new source gets its own client file (this
pattern) plus its own normalizer file, without touching this one.
"""

import httpx

FAKESTORE_BASE_URL = "https://fakestoreapi.com"
REQUEST_TIMEOUT_SECONDS = 10.0


async def fetch_all_products() -> list[dict]:
    """Fetch every product from FakeStoreAPI, as raw JSON."""
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.get(f"{FAKESTORE_BASE_URL}/products")
        response.raise_for_status()
        return response.json()


async def fetch_product_by_id(product_id: int) -> dict | None:
    """Fetch a single product by its FakeStoreAPI numeric ID. Returns None if not found."""
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.get(f"{FAKESTORE_BASE_URL}/products/{product_id}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()


async def fetch_categories() -> list[str]:
    """Fetch the list of category names FakeStoreAPI supports."""
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.get(f"{FAKESTORE_BASE_URL}/products/categories")
        response.raise_for_status()
        return response.json()
