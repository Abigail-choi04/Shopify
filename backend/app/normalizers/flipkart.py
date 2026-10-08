"""
ShopMate AI — Flipkart Normalizer (Phase 4)

Converts one product record from the Apify Flipkart scrape (the saved
snapshot files) into the shared Product shape. Prices on Flipkart are
already rupees, so no conversion is needed.

What it cleans:
  - garbled text (e.g. 'Ï€' where a symbol should be) from the scrape
  - the nested spec sections are flattened into one list
  - a rating of 0 means "no rating yet", so it becomes None, not 0 stars
Products that cannot be shown honestly (no price, no title, not a real
laptop) are skipped with a reason, which the snapshot loader counts.
"""

import re

from app.normalizers.spec_facts import extract_spec_facts
from app.schemas.product import Product

GARBLE_MARKERS = ("Ã", "â€", "â’", "Ï€", "Â")


class SkipProduct(Exception):
    """This record should not become a Product; str(exception) says why."""


def fix_text(value):
    """Repairs common text-encoding damage; strips what can't be repaired."""
    if not isinstance(value, str) or not any(marker in value for marker in GARBLE_MARKERS):
        return value
    try:
        return value.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        cleaned = value
        for marker in GARBLE_MARKERS:
            cleaned = cleaned.replace(marker, "")
        return cleaned


def flatten_specifications(specifications) -> dict[str, str]:
    """{'General': {'Brand': 'boAt'}, 'Product Details': {...}} -> {'Brand': 'boAt', ...}. First value wins."""
    flat: dict[str, str] = {}
    if not isinstance(specifications, dict):
        return flat
    for section in specifications.values():
        if not isinstance(section, dict):
            continue
        for key, value in section.items():
            key = str(fix_text(key)).strip()
            if key and key not in flat and value is not None:
                flat[key] = str(fix_text(value)).strip()
    return flat


def model_key(title: str, category: str, facts: dict) -> str:
    """
    A key shared by variants of one model (colour / storage / RAM options).
    Flipkart puts the variant in brackets, e.g. 'Phone X (Blue, 128 GB)', so the key is
    the title without bracketed parts. Laptops also add the processor, because many
    laptops share a family title but differ in chip.
    """
    base = re.sub(r"\([^)]*\)", " ", title or "")
    key = re.sub(r"\s+", " ", base).strip().lower()
    if category == "laptops":
        processor = facts.get("processor")
        if processor is not None:
            key += "|" + str(processor.value).lower()
    return key


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_flipkart_product(raw: dict, category: str) -> Product:
    """Raises SkipProduct when the record can't be used."""
    if raw.get("type") not in (None, "product"):
        raise SkipProduct("not a product record")
    product_id = raw.get("productId")
    title = fix_text(raw.get("fullTitle") or raw.get("title"))
    price = _number(raw.get("price"))
    if not product_id:
        raise SkipProduct("no product id")
    if not title or not str(title).strip():
        raise SkipProduct("no title")
    if price is None or price <= 0:
        raise SkipProduct("no price")

    specs = flatten_specifications(raw.get("specifications"))
    if category == "laptops" and specs.get("Is Tablet", "").lower() == "yes":
        raise SkipProduct("tablet listed under laptops")

    facts, conflicts = extract_spec_facts(category, specs)

    rating = _number(raw.get("rating"))
    rating_count = _number(raw.get("ratingCount"))
    mrp = _number(raw.get("mrp"))
    breadcrumb = raw.get("breadcrumb") or []
    in_stock = raw.get("inStock")

    return Product(
        id=f"flipkart-{product_id}",
        source="flipkart_snapshot",
        title=str(title).strip(),
        category=category,
        price=price,
        currency="INR",
        image_url=raw.get("image") or raw.get("mainImage"),
        rating=rating if rating else None,
        rating_count=int(rating_count) if rating_count else None,
        description=fix_text(raw.get("description")) or None,
        brand=fix_text(raw.get("brand")) or specs.get("Brand"),
        subcategory=fix_text(breadcrumb[-2]) if len(breadcrumb) >= 2 else None,
        merchant="Flipkart",
        url=raw.get("url"),
        mrp=mrp if mrp and mrp > price else None,
        in_stock=bool(in_stock) if in_stock is not None else None,
        sponsored=bool(raw.get("sponsored")),
        captured_at=(raw.get("scrapedAt") or "")[:10] or None,
        group_id=model_key(str(title), category, facts) or raw.get("itemId"),
        specs=specs,
        spec_facts=facts,
        spec_conflicts=conflicts,
        raw=raw,
    )