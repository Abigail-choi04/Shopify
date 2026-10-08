"""
ShopMate AI — Products Router (Phase 1; saved Flipkart snapshot added in Phase 4)

Exposes normalized product data to the frontend over HTTP.

Where the products come from:
  - the saved Flipkart snapshot (backend/data_private/), when its files exist;
  - otherwise the FakeStoreAPI toy catalog (the Phase 1 behaviour).

The fetching + caching logic for FakeStoreAPI lives in
app/services/product_catalog.py; the snapshot loader is
app/services/snapshot_store.py.
"""

from fastapi import APIRouter, HTTPException

from app.normalizers.fakestore import normalize_fakestore_product
from app.schemas.product import Product
from app.services import fakestore_client, product_catalog, snapshot_store

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=list[Product])
async def list_products(category: str | None = None):
    """
    Returns all normalized products, optionally filtered by category.
    Snapshot categories: earphones, smartphones, laptops, running_shoes,
    smartwatches (see GET /products/categories).
    """
    snapshot = snapshot_store.load_snapshot()
    products = snapshot.products if snapshot is not None else await product_catalog.get_all_normalized_products()

    if category:
        products = [p for p in products if p.category == category]

    return products


@router.get("/categories", response_model=list[str])
async def list_categories():
    """Returns the category names available from the current product source."""
    snapshot = snapshot_store.load_snapshot()
    if snapshot is not None:
        return list(snapshot.counts.keys())
    return await fakestore_client.fetch_categories()


@router.get("/{product_id}", response_model=Product)
async def get_product(product_id: str):
    """
    Fetch a single product by its ShopMate-prefixed ID,
    e.g. "flipkart-MOBGTAGPTB3VS24W" or "fakestore-1".
    """
    if product_id.startswith("flipkart-"):
        product = snapshot_store.get_product(product_id)
        if product is None:
            raise HTTPException(status_code=404, detail="Product not found")
        return product

    if not product_id.startswith("fakestore-"):
        raise HTTPException(status_code=404, detail="Unknown product source")

    try:
        numeric_id = int(product_id.removeprefix("fakestore-"))
    except ValueError:
        raise HTTPException(status_code=404, detail="Product not found")

    raw = await fakestore_client.fetch_product_by_id(numeric_id)

    if raw is None:
        raise HTTPException(status_code=404, detail="Product not found")

    return normalize_fakestore_product(raw)