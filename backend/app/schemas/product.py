"""
ShopMate AI — Product Schema (Phase 1, currency fields added with the INR layer, spec fields in Phase 4)

This is the ONE shape every product must be converted into, no matter
which source (retailer/tool) it came from. This is what makes the
ranking/comparison logic category-agnostic — it never needs to know
"this came from FakeStoreAPI vs the Flipkart snapshot vs SerpAPI", it
just sees a Product.

Prices: `price` + `currency` are what the SOURCE listed (never altered).
`price_inr` is the rupee amount the whole app uses for budgets, ranking
and claims. For an INR source it equals `price`; for a foreign source it
is converted by app/services/currency.py, and the rate used is recorded
in `fx_rate` / `fx_as_of` / `fx_source` so every converted number can
be explained and checked.

Specs (Phase 4): `specs` is the source's own spec list, cleaned but
otherwise as listed. `spec_facts` are the few facts we have turned into
checked, typed values (e.g. ram_gb = 8) by app/normalizers/spec_facts.py.
A fact exists ONLY when the source data states it clearly; when the
source contradicts itself the key goes into `spec_conflicts` instead, and
when the source is silent the key is simply absent ("unknown", never "no").

`raw` keeps the original untouched source data, so any claim the agent
makes can be traced back to real source data.
"""

from typing import Any, Optional, Union

from pydantic import BaseModel, Field, model_validator


class SpecFact(BaseModel):
    value: Union[bool, float, str]  # the checkable value: True, 8.0, "wireless" ...
    display: str  # how it is shown to the shopper: "Yes", "8 GB", "Wireless (Bluetooth)"


class Product(BaseModel):
    id: str  # e.g. "fakestore-1" or "flipkart-ACCHEYV9THQDE5ZZ" — prefixed with source so IDs never collide
    source: str  # "fakestore" | "flipkart_snapshot" | "serpapi"
    title: str
    category: str
    price: float  # as listed by the source, in `currency`
    currency: str = "USD"
    price_inr: Optional[float] = None  # rupee price used app-wide; None = could not be converted
    fx_rate: Optional[float] = None  # INR per 1 unit of `currency`, set only when converted
    fx_as_of: Optional[str] = None  # date of that rate, e.g. "2026-10-06"
    fx_source: Optional[str] = None  # "live" | "stale_cache" | "fallback"
    image_url: Optional[str] = None
    rating: Optional[float] = None
    rating_count: Optional[int] = None
    description: Optional[str] = None

    # --- Phase 4 ---
    brand: Optional[str] = None
    subcategory: Optional[str] = None  # e.g. "True Wireless", from the source's own category path
    merchant: Optional[str] = None  # who sells it: "Flipkart", or the shop named by Google Shopping
    url: Optional[str] = None
    mrp: Optional[float] = None  # the "list price" shown struck-through, in `currency`
    in_stock: Optional[bool] = None
    sponsored: bool = False
    captured_at: Optional[str] = None  # date the data was collected, e.g. "2026-10-08"
    group_id: Optional[str] = None  # variants of one model (colour/storage) share this
    specs: dict[str, str] = Field(default_factory=dict)
    spec_facts: dict[str, SpecFact] = Field(default_factory=dict)
    spec_conflicts: list[str] = Field(default_factory=list)

    raw: dict[str, Any]  # untouched original data from the source, for traceability

    @model_validator(mode="after")
    def _fill_inr_for_rupee_sources(self):
        """A product already priced in INR needs no conversion: its rupee price IS its price."""
        if self.price_inr is None and self.currency.upper() == "INR":
            self.price_inr = round(self.price, 2)
        return self