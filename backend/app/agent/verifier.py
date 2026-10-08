"""
ShopMate AI — Claim Verifier (Phase 5)

The "check the answer against the real data" step. Deliberately NOT an
LLM: it is plain Python comparing what the model CLAIMED against what
the tools actually RETURNED, so it cannot be talked into agreeing with
a made-up claim. (An LLM-as-judge verifier is a possible later
comparison for the paper, but the deterministic one is the baseline.)

A claim passes only if ALL of these hold:
  1. Its `field` is one we know how to check.
  2. It cites a tool call ID that really exists in the trace.
  3. It cites the RIGHT tool call (product facts -> the call that
     retrieved that product, rank facts -> the rank call).
  4. Its `value` matches the real product data.
  5. Every number written inside its `text` sentence is a known fact
     about that product (price, rating, review count, budget, rank, or
     the spec value the claim is about). This catches the case where
     `value` is right but the sentence sneaks in an invented number,
     e.g. "20 hours of battery".

Phase 4 adds the "spec" field: {"field": "spec", "key": "ram_gb", "value": 8}
is checked against the product's spec facts (app/normalizers/spec_facts.py).
A spec the listing is silent on, or contradicts itself about, can never be
claimed. A yes/no spec must also be worded the right way round (a claim
that the product HAS noise cancellation may not say "no noise cancellation").

verify_product_claims returns (verified, failures) so callers can both
keep the good claims and tell the model exactly what went wrong.
"""

import re

from app.schemas.agent import Claim
from app.schemas.product import Product
from app.services.currency import BASE_CURRENCY, SYMBOLS

NUMERIC_FIELDS = {"price", "rating", "rating_count"}
SPEC_FIELD = "spec"
PRODUCT_FACT_FIELDS = {"price", "rating", "rating_count", "category", "within_budget", SPEC_FIELD}
RANK_FIELD = "rank"
ALLOWED_FIELDS = PRODUCT_FACT_FIELDS | {RANK_FIELD}

NEGATION = re.compile(r"\b(no|not|without|lacks?|lacking|never|none)\b|n't", re.I)

NUMBER_PATTERN = re.compile(r"\d[\d,]*\.?\d*")
TOLERANCE = 0.01

# The shopper's budget, and every price we quote, is in this currency (rupees).
BUDGET_CURRENCY = BASE_CURRENCY
CURRENCY_SYMBOLS = SYMBOLS


def _to_float(value) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(str(value).replace(",", "").replace("₹", "").replace("$", "").strip())
    except ValueError:
        return None


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= TOLERANCE


def _numbers_in_text(text: str) -> list[float]:
    found = []
    for match in NUMBER_PATTERN.findall(text):
        cleaned = match.replace(",", "").rstrip(".")
        try:
            found.append(float(cleaned))
        except ValueError:
            continue
    return found


def _allowed_numbers(
    product: Product, position: int, max_price: float | None, total_ranked: int, extra: list[float] | None = None
) -> list[float]:
    # rank position, the number of ranked products ("#1 of 3"), the "/ 5" in ratings, and a bare 1
    allowed = [float(position), float(total_ranked), 5.0, 1.0]
    if product.price_inr is not None:
        allowed.append(product.price_inr)
        allowed.append(float(round(product.price_inr)))
    if product.rating is not None:
        allowed.append(product.rating)
        allowed.append(round(product.rating, 1))
    if product.rating_count is not None:
        allowed.append(float(product.rating_count))
    if max_price is not None:
        allowed.append(max_price)
    if extra:
        allowed.extend(extra)
    return allowed


def _check_spec(claim: Claim, product: Product) -> tuple[str | None, list[float]]:
    """Returns (problem or None, numbers the sentence may mention because of this spec)."""
    key = claim.key
    if not key:
        return "a 'spec' claim must name the spec in 'key'", []
    if key in product.spec_conflicts:
        return f"the listing contradicts itself about '{key}', so it cannot be claimed", []
    fact = product.spec_facts.get(key)
    if fact is None:
        return f"there is no verified '{key}' value for this product (the listing does not state it)", []

    real = fact.value
    if isinstance(real, bool):
        claimed = claim.value if isinstance(claim.value, bool) else {"true": True, "false": False}.get(str(claim.value).strip().lower())
        if claimed is None or claimed != real:
            return f"spec '{key}' value {claim.value!r} does not match the real value {real}", []
        negated = bool(NEGATION.search(claim.text))
        if real and negated:
            return f"'{key}' is true for this product, but the sentence is worded as a negative", []
        if not real and not negated:
            return f"'{key}' is false for this product, but the sentence does not say so", []
        return None, []
    if isinstance(real, float):
        value = _to_float(claim.value)
        if value is None or not _close(value, real):
            return f"spec '{key}' value {claim.value!r} does not match the real value {real:g}", []
        return None, [real]
    if str(claim.value).strip().lower() != str(real).strip().lower():
        return f"spec '{key}' value {claim.value!r} does not match the real value {real!r}", []
    return None, []


def verify_claim(
    claim: Claim,
    product: Product,
    position: int,
    max_price: float | None,
    valid_call_ids: set[str],
    search_call_id: str,
    rank_call_id: str,
    total_ranked: int,
) -> str | None:
    """Returns None if the claim passes, otherwise a short plain-English reason it failed."""
    if claim.field not in ALLOWED_FIELDS:
        return f"unknown field '{claim.field}' (allowed: {', '.join(sorted(ALLOWED_FIELDS))})"

    if claim.source_tool_call_id not in valid_call_ids:
        return f"cites '{claim.source_tool_call_id}', which is not a tool call in this run"

    expected_call = rank_call_id if claim.field == RANK_FIELD else search_call_id
    if claim.source_tool_call_id != expected_call:
        return f"'{claim.field}' claims must cite {expected_call}, but this cites {claim.source_tool_call_id}"

    # --- value check ---
    spec_numbers: list[float] = []
    if claim.field == SPEC_FIELD:
        problem, spec_numbers = _check_spec(claim, product)
        if problem:
            return problem
    elif claim.field == "price":
        # Every price we quote is the RUPEE price (converted from the source's currency if needed).
        value = _to_float(claim.value)
        if product.price_inr is None:
            return "no rupee price is available for this product, so a price claim cannot be verified"
        if value is None or not _close(value, product.price_inr):
            return f"price value {claim.value!r} does not match the real rupee price {product.price_inr}"
    elif claim.field == "rating":
        value = _to_float(claim.value)
        if product.rating is None or value is None or not _close(value, product.rating):
            return f"rating value {claim.value!r} does not match the real rating {product.rating}"
    elif claim.field == "rating_count":
        value = _to_float(claim.value)
        if product.rating_count is None or value is None or not _close(value, float(product.rating_count)):
            return f"rating_count value {claim.value!r} does not match the real count {product.rating_count}"
    elif claim.field == "category":
        if str(claim.value).strip().lower() != product.category.strip().lower():
            return f"category value {claim.value!r} does not match the real category {product.category!r}"
    elif claim.field == "within_budget":
        if max_price is None:
            return "claims it is within budget, but the shopper gave no budget"
        if product.price_inr is None:
            return (
                f"the budget is in {BUDGET_CURRENCY} but this product's price could not be converted to "
                f"{BUDGET_CURRENCY}, so it cannot be compared"
            )
        if claim.value not in (True, "true", "True"):
            return f"within_budget value must be true, got {claim.value!r}"
        if product.price_inr > max_price:
            return f"price {product.price_inr} is above the budget {max_price}"
    elif claim.field == RANK_FIELD:
        value = _to_float(claim.value)
        if value is None or not _close(value, float(position)):
            return f"rank value {claim.value!r} does not match the real position {position} of {total_ranked}"

    # --- every price is shown in rupees, so no other currency symbol may appear ---
    rupee_symbol = CURRENCY_SYMBOLS[BUDGET_CURRENCY]
    for symbol in CURRENCY_SYMBOLS.values():
        if symbol in claim.text and symbol != rupee_symbol:
            return f"the sentence uses '{symbol}' but all prices are quoted in {BUDGET_CURRENCY} ({rupee_symbol})"

    # --- every number in the sentence must be a known fact ---
    allowed = _allowed_numbers(product, position, max_price, total_ranked, spec_numbers)
    for number in _numbers_in_text(claim.text):
        if not any(_close(number, known) for known in allowed):
            return f"the sentence mentions {number:g}, which is not a known fact about this product"

    return None


def verify_product_claims(
    claims: list[Claim],
    product: Product,
    position: int,
    max_price: float | None,
    valid_call_ids: set[str],
    search_call_id: str,
    rank_call_id: str,
    total_ranked: int,
) -> tuple[list[Claim], list[tuple[Claim, str]]]:
    verified: list[Claim] = []
    failures: list[tuple[Claim, str]] = []
    for claim in claims:
        reason = verify_claim(
            claim, product, position, max_price, valid_call_ids, search_call_id, rank_call_id, total_ranked
        )
        if reason is None:
            verified.append(claim)
        else:
            failures.append((claim, reason))
    return verified, failures


def unconfirmed_requirements(results_by_product: dict[str, list]) -> list[str]:
    """
    The shopper's requirements that could NOT be confirmed for at least one of the given
    products (the listing was silent, contradicted itself, or we have no rule for it).
    Used for the trace note, so nothing is ever presented as confirmed when it was not.
    """
    names: list[str] = []
    for results in results_by_product.values():
        for result in results:
            if result.status in {"unknown", "conflict", "unsupported"} and result.requirement not in names:
                names.append(result.requirement)
    return names