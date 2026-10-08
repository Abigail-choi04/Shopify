"""
ShopMate AI — Agent Response Schemas (Phase 3, extended in Phase 5)

The core shapes are deliberately identical to what frontend/src/data/scenarios.js
already hardcodes. That file was written first (UI prototyping), and
these schemas are the real backend catching up to match it — so when
the frontend is later wired to call POST /chat instead of pickScenario(),
no component needs to change, only where the data comes from.

Phase 5 additions are all OPTIONAL / additive (`claims` on a product,
`verification` on the response), so the existing frontend keeps working
unchanged and can start showing them whenever we choose. The same goes
for the Phase 4 additions (`requirements`, `url`, `source`, ... on a
product, `dataSource` on the response).
"""

from typing import Optional, Union

from pydantic import BaseModel


class TraceStep(BaseModel):
    type: str  # "thought" | "action" | "observation"
    text: str
    toolCallId: Optional[str] = None


class Claim(BaseModel):
    """
    One checkable statement about one product (Phase 5 grounding).

    `field` says WHAT is being claimed (price, rating, rating_count,
    category, within_budget, rank, spec), `value` is the number/text being
    asserted, `text` is the sentence shown to the shopper, and
    `source_tool_call_id` is the tool call the fact came from. For a
    "spec" claim, `key` names the spec (e.g. "ram_gb"). The verifier
    (app/agent/verifier.py) checks all of these against real data.
    """

    field: str
    key: Optional[str] = None  # only for field == "spec"
    value: Optional[Union[float, int, str, bool]] = None
    text: str
    source_tool_call_id: str


class ProductClaims(BaseModel):
    """The explain step's output for one product (what the LLM returns)."""

    product_id: str
    claims: list[Claim]


class ExplainOutput(BaseModel):
    """The explain step's full output (what the LLM returns, validated)."""

    products: list[ProductClaims]


class DroppedClaim(BaseModel):
    productId: str
    text: str
    reason: str


class VerificationSummary(BaseModel):
    claimsChecked: int
    claimsVerified: int
    claimsDropped: int
    retried: bool
    dropped: list[DroppedClaim]


class RequirementOut(BaseModel):
    """How one of the shopper's must-haves fared for one product (Phase 4)."""

    requirement: str
    status: str  # "met" | "unknown" | "conflict" | "unsupported"  ("not_met" products are left out)
    evidence: Optional[str] = None  # e.g. "Noise cancellation: Yes"


class RankedProduct(BaseModel):
    id: str
    title: str
    price: float
    rating: Optional[float] = None
    ratingCount: Optional[int] = None
    icon: str
    attributes: dict[str, str]
    reasoning: str
    sourceToolCallId: str
    isTopPick: bool = False
    claims: list[Claim] = []  # Phase 5: only claims that PASSED verification
    # Rupee-price details (INR layer). `price` above is always the rupee price when one exists.
    currency: str = "INR"
    priceIsApproximate: bool = False  # True when the rupee price was converted from another currency
    listedPrice: Optional[str] = None  # the source's own price, e.g. "$109.00", only when converted
    priceNote: Optional[str] = None  # e.g. "Converted from $109.00 at ₹96.42 per $1 (rate dated 2026-10-06)"
    # Phase 4
    url: Optional[str] = None
    imageUrl: Optional[str] = None
    source: Optional[str] = None  # e.g. "Flipkart (saved 8 Oct 2026)"
    requirements: list[RequirementOut] = []


class ParsedIntentOut(BaseModel):
    category: str
    budget: str
    mustHaves: list[str]


class ChatResponse(BaseModel):
    aisle: str
    parsedIntent: ParsedIntentOut
    trace: list[TraceStep]
    comparisonAttributes: list[str]
    products: list[RankedProduct]
    verification: Optional[VerificationSummary] = None  # Phase 5
    dataSource: Optional[str] = None  # Phase 4: where the products came from, and how old the data is


class ChatRequest(BaseModel):
    query: str