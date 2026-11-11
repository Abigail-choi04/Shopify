"""
ShopMate AI — Verifier demo ("inject an error")

On request (the demo checkbox in the UI), ONE drafted claim is deliberately made wrong before the
checker sees it, so the audience can watch the checker reject it and force a rewrite. Nothing here
runs unless the shopper asks for it, and it only ever alters the FIRST draft; the model's rewrite is
left untouched.

tamper_one_claim(proposed, ranked) -> (new_proposed, info or None)
  info = {"productId", "productTitle", "originalText", "alteredText"}
The claim is changed to a believable lie: a price 40% too low, or a rating a full point off.
"""

from app.schemas.agent import Claim

RUPEE = "₹"


def _altered_claim(claim: Claim) -> Claim | None:
    if isinstance(claim.value, bool) or not isinstance(claim.value, (int, float)):
        return None
    if claim.field == "price" and claim.value > 0:
        altered = round(claim.value * 0.6, -1) if claim.value >= 100 else round(claim.value * 0.6)
        if altered <= 0 or altered == claim.value:
            return None
        return claim.model_copy(update={"value": altered, "text": f"Costs {RUPEE}{altered:,.0f}."})
    if claim.field == "rating":
        altered = round(claim.value + 1.0, 1) if claim.value <= 4.0 else round(claim.value - 1.0, 1)
        return claim.model_copy(update={"value": altered, "text": f"Rated {altered} out of 5."})
    return None


def tamper_one_claim(proposed: dict[str, list[Claim]], ranked: list) -> tuple[dict[str, list[Claim]], dict | None]:
    """Alters the first alterable claim (price first, then rating) of the first product that has one."""
    for field in ("price", "rating"):
        for product in ranked:
            claims = proposed.get(product.id, [])
            for index, claim in enumerate(claims):
                if claim.field != field:
                    continue
                altered = _altered_claim(claim)
                if altered is None:
                    continue
                new_claims = list(claims)
                new_claims[index] = altered
                new_proposed = dict(proposed)
                new_proposed[product.id] = new_claims
                return new_proposed, {
                    "productId": product.id,
                    "productTitle": product.title,
                    "originalText": claim.text,
                    "alteredText": altered.text,
                }
    return proposed, None