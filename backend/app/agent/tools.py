"""
ShopMate AI — Agent Tools (Phase 3; saved Flipkart snapshot, requirements and review-weighted ranking in Phase 4)

These are the functions the LangGraph nodes call to actually do
something, as opposed to just generating text. Each call is logged
with a unique tool_call_id by the caller (app/agent/graph.py) — that
ID is what Phase 5's grounding mechanism requires every claim to
cite.

Where products come from (see app/services/snapshot_store.py):
  - the saved Flipkart snapshot, when its files exist (the normal case);
  - otherwise the Phase 3 FakeStoreAPI catalog (toy data, prices in USD).

IMPORTANT HONESTY NOTE: ranking only uses fields that exist in the
data — rating, review count, rupee price, and spec facts that passed
the Phase 4 checks. Nothing is ever filled in by guessing.

Prices: budgets, filtering and ranking all use `price_inr` (see
app/schemas/product.py), so everything is compared in rupees.
"""

from app.agent.ranking import get_fakestore_category, get_snapshot_category
from app.agent.requirements import NOT_MET, RequirementResult, check_requirements
from app.schemas.product import Product
from app.services import product_catalog, snapshot_store

PRIOR_REVIEWS = 50  # how many "average" reviews a product is assumed to start with (see rank_products)
MET_BONUS = 1.0  # ranking bonus for each requirement the specs confirm (worth half a star)


async def search_products(category_slug: str, max_price: float | None) -> list[Product]:
    """
    Searches the catalog for a category (a planner slug such as "headphones"),
    optionally within a maximum price in rupees. Uses the saved Flipkart
    snapshot when it exists, otherwise the FakeStoreAPI catalog.
    """
    snapshot = snapshot_store.load_snapshot()
    if snapshot is not None:
        category = get_snapshot_category(category_slug)
        matches = snapshot.category(category) if category else []
    else:
        fakestore_category = get_fakestore_category(category_slug)
        all_products = await product_catalog.get_all_normalized_products()
        matches = [p for p in all_products if p.category == fakestore_category]

    # The shopper's budget is in INR and every product has a rupee price, so this is a
    # like-for-like comparison. A product with no rupee price at all (no exchange rate
    # existed) is kept rather than silently dropped; the caller tells the shopper.
    if max_price is not None:
        matches = [p for p in matches if p.price_inr is None or p.price_inr <= max_price]

    return matches


def filter_by_requirements(
    products: list[Product], must_haves: list[str], known_brands: set[str] | None = None
) -> tuple[list[Product], list[tuple[Product, RequirementResult]], dict[str, list[RequirementResult]]]:
    """
    Checks every product against the shopper's must-haves.
    Returns (kept, excluded, results) where `excluded` holds each product the listing
    clearly contradicts (with the requirement that failed) and `results` maps
    product id -> every requirement result, for the product's page and the trace.
    """
    results: dict[str, list[RequirementResult]] = {}
    kept: list[Product] = []
    excluded: list[tuple[Product, RequirementResult]] = []
    for product in products:
        product_results = check_requirements(product, must_haves, known_brands)
        results[product.id] = product_results
        failed = next((r for r in product_results if r.status == NOT_MET), None)
        if failed is not None:
            excluded.append((product, failed))
        else:
            kept.append(product)
    return kept, excluded, results


def rank_products(
    products: list[Product],
    top_n: int = 3,
    requirement_results: dict[str, list[RequirementResult]] | None = None,
) -> list[Product]:
    """
    Ranks candidates and returns the top N.

    score = 2 x weighted rating  +  1 per requirement the specs confirm  -  price (scaled 0..1)

    Weighted rating: a plain average lets 5.0 stars from 3 reviews beat 4.5 stars from
    4,000 reviews. So each rating is pulled toward the candidates' average, strongly when
    there are few reviews and hardly at all when there are many (a Bayesian average):
        (reviews x rating + 50 x average) / (reviews + 50)
    If a product's review count is unknown its rating is used as listed.

    The price part is scaled to 0..1 against the priciest candidate, so rupee-sized
    prices can never drown out the 0..5 rating — price only breaks near-ties.

    Variants of one model (colour/storage) share a group id; only the best-scoring variant
    appears, so the top 3 are three different models.
    """
    requirement_results = requirement_results or {}
    rated = [p.rating for p in products if p.rating is not None]
    average = sum(rated) / len(rated) if rated else 0.0
    highest_price = max((p.price_inr or 0.0 for p in products), default=0.0)

    def weighted_rating(product: Product) -> float:
        if product.rating is None:
            return average
        if product.rating_count is None:
            return product.rating
        return (product.rating_count * product.rating + PRIOR_REVIEWS * average) / (product.rating_count + PRIOR_REVIEWS)

    def score(product: Product) -> float:
        met = sum(1 for r in requirement_results.get(product.id, []) if r.status == "met")
        price_component = -((product.price_inr or 0.0) / highest_price) if highest_price else 0.0
        return weighted_rating(product) * 2 + met * MET_BONUS + price_component

    ordered = sorted(products, key=score, reverse=True)

    seen_groups: set[str] = set()
    ranked: list[Product] = []
    for product in ordered:
        if product.group_id:
            if product.group_id in seen_groups:
                continue
            seen_groups.add(product.group_id)
        ranked.append(product)
    return ranked[:top_n]