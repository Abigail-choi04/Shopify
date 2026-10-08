"""
ShopMate AI — FakeStoreAPI Normalizer (Phase 1)

Converts FakeStoreAPI's raw JSON shape into our internal Product
schema (app/schemas/product.py). Every new data source added later
(Phase 4: RapidAPI, MYSTORE, etc.) gets its own normalizer file like
this one — the rest of the app never touches raw source data directly.
"""

from typing import Any

from app.schemas.product import Product


def normalize_fakestore_product(raw: dict[str, Any]) -> Product:
    rating_data = raw.get("rating") or {}

    return Product(
        id=f"fakestore-{raw['id']}",
        source="fakestore",
        title=raw.get("title", "Untitled product"),
        category=raw.get("category", "uncategorized"),
        price=float(raw.get("price", 0)),
        currency="USD",
        image_url=raw.get("image"),
        rating=rating_data.get("rate"),
        rating_count=rating_data.get("count"),
        description=raw.get("description"),
        raw=raw,
    )
