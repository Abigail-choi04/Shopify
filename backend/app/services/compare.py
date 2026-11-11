"""
ShopMate AI — Compare two products

Builds the comparison from the products' own checked facts (price, rating and the typed spec facts
of app/normalizers/spec_facts.py). No language model is involved, so nothing in a comparison can be
made up: a fact the listing does not state shows as "Not listed" and never decides a winner.

Which way is "better":
  lower is better   price, weight
  higher is better  rating, RAM, storage, battery, camera megapixels
  yes is better     5G, noise cancellation, water resistance, calling, GPS
Everything else (screen size, materials, connectivity type...) is shown without naming a winner.
"""

from app.normalizers.spec_facts import COMPARISON_SPECS
from app.schemas.compare import CompareProduct, CompareResponse, CompareRow
from app.schemas.product import Product
from app.services import currency, product_catalog, snapshot_store
from app.services.currency import format_inr

HIGHER_IS_BETTER = {"ram_gb", "storage_gb", "battery_mah", "battery_hours", "battery_days", "rear_camera_mp"}
LOWER_IS_BETTER = {"weight_kg", "weight_g"}
YES_IS_BETTER = {"network_5g", "noise_cancellation", "water_resistant", "calling", "gps"}

RATING_TIE_MARGIN = 0.05  # ratings closer than this are called a tie


class CompareError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


async def lookup_product(product_id: str) -> Product | None:
    if product_id.startswith("serpapi-"):
        raise CompareError("unsupported_source", "Web-search listings have no checked specs, so they can't be compared.", 422)
    if product_id.startswith("flipkart-"):
        return snapshot_store.get_product(product_id)
    if product_id.startswith("fakestore-"):
        products = await product_catalog.get_all_normalized_products()
        found = next((p for p in products if p.id == product_id), None)
        return (await currency.convert_products([found]))[0] if found else None
    return None


def _price(product: Product) -> float | None:
    return product.price_inr if product.price_inr is not None else None


def _winner(a, b, higher_is_better: bool, margin: float = 0.0) -> str:
    if abs(a - b) <= margin:
        return "tie"
    return "a" if (a > b) == higher_is_better else "b"


def build_rows(a: Product, b: Product) -> list[CompareRow]:
    rows: list[CompareRow] = []

    price_a, price_b = _price(a), _price(b)
    rows.append(
        CompareRow(
            label="Price",
            a=format_inr(price_a) if price_a is not None else "Not listed",
            b=format_inr(price_b) if price_b is not None else "Not listed",
            winner=_winner(price_a, price_b, higher_is_better=False) if price_a is not None and price_b is not None else None,
        )
    )
    rows.append(
        CompareRow(
            label="Rating",
            a=f"{a.rating} / 5" if a.rating is not None else "No rating yet",
            b=f"{b.rating} / 5" if b.rating is not None else "No rating yet",
            winner=_winner(a.rating, b.rating, True, RATING_TIE_MARGIN) if a.rating is not None and b.rating is not None else None,
        )
    )
    rows.append(
        CompareRow(
            label="Reviews",
            a=f"{a.rating_count:,}" if a.rating_count is not None else "—",
            b=f"{b.rating_count:,}" if b.rating_count is not None else "—",
            winner=None,
        )
    )

    for key, label in COMPARISON_SPECS.get(a.category, []):
        fact_a, fact_b = a.spec_facts.get(key), b.spec_facts.get(key)
        winner = None
        if fact_a is not None and fact_b is not None:
            va, vb = fact_a.value, fact_b.value
            if key in HIGHER_IS_BETTER and isinstance(va, (int, float)) and isinstance(vb, (int, float)) and not isinstance(va, bool):
                winner = _winner(va, vb, True)
            elif key in LOWER_IS_BETTER and isinstance(va, (int, float)) and isinstance(vb, (int, float)) and not isinstance(va, bool):
                winner = _winner(va, vb, False)
            elif key in YES_IS_BETTER and isinstance(va, bool) and isinstance(vb, bool):
                winner = "tie" if va == vb else ("a" if va else "b")
        rows.append(
            CompareRow(
                label=label,
                a=fact_a.display if fact_a is not None else "Not listed",
                b=fact_b.display if fact_b is not None else "Not listed",
                winner=winner,
            )
        )
    return rows


def _short(title: str) -> str:
    """The product's name without the bracketed variant details, shortened for a sentence."""
    name = title.split("(")[0].strip() or title
    return name if len(name) <= 45 else name[:42].rstrip() + "…"


def build_summary(a: Product, b: Product, rows: list[CompareRow]) -> list[str]:
    name_a, name_b = _short(a.title), _short(b.title)
    sentences: list[str] = []
    by_label = {row.label: row for row in rows}

    price = by_label["Price"]
    if price.winner in ("a", "b") and _price(a) is not None and _price(b) is not None:
        cheaper, dearer = (name_a, name_b) if price.winner == "a" else (name_b, name_a)
        sentences.append(f"{cheaper} is {format_inr(abs(_price(a) - _price(b)))} cheaper than {dearer}.")
    elif price.winner == "tie":
        sentences.append("Both cost the same.")

    rating = by_label["Rating"]
    if rating.winner in ("a", "b"):
        better = name_a if rating.winner == "a" else name_b
        sentences.append(f"{better} is rated higher ({a.rating} vs {b.rating}).")
    elif rating.winner == "tie":
        sentences.append(f"They are rated about the same ({a.rating} vs {b.rating}).")

    spec_rows = [r for r in rows if r.label not in ("Price", "Rating", "Reviews")]
    for row in spec_rows:
        if row.winner in ("a", "b"):
            better = name_a if row.winner == "a" else name_b
            sentences.append(f"{better} is better on {row.label.lower()} ({row.a} vs {row.b}).")

    missing = [r.label for r in spec_rows if "Not listed" in (r.a, r.b)]
    if missing:
        sentences.append(f"Not stated in one or both listings, so not compared: {', '.join(missing)}.")
    return sentences


async def compare_products(product_ids: list[str]) -> CompareResponse:
    if len(product_ids) != 2 or product_ids[0] == product_ids[1]:
        raise CompareError("need_two", "Pick two different products to compare.", 400)
    a = await lookup_product(product_ids[0])
    b = await lookup_product(product_ids[1])
    if a is None or b is None:
        raise CompareError("product_not_found", "One of those products is no longer in the catalog.", 404)
    if a.category != b.category:
        raise CompareError("different_categories", "These two are different kinds of products, so they can't be compared fairly.", 422)

    rows = build_rows(a, b)
    wins = [r.winner for r in rows]
    as_product = lambda p: CompareProduct(  # noqa: E731
        id=p.id, title=p.title, price=p.price_inr if p.price_inr is not None else p.price, url=p.url, imageUrl=p.image_url
    )
    return CompareResponse(
        category=a.category,
        a=as_product(a),
        b=as_product(b),
        rows=rows,
        summary=build_summary(a, b, rows),
        aWins=wins.count("a"),
        bWins=wins.count("b"),
        ties=wins.count("tie"),
        dataSource="Flipkart snapshot" + (f", captured {a.captured_at}" if a.captured_at else "") if a.source == "flipkart_snapshot" else None,
    )