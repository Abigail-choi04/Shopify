"""
ShopMate AI — Parsed Intent Schema (Phase 2, now built as part of Phase 3)

This is what a natural-language query gets turned into by the agent's
planner node. `category_slug` is the FINE-GRAINED category the LLM
detected (e.g. "headphones", "running_shoes") — this drives which
ranking attributes get used (see app/agent/ranking.py). It is
DIFFERENT from the coarser category FakeStoreAPI actually stocks
(electronics / jewelery / men's clothing / women's clothing) — that
mapping happens separately in app/agent/ranking.py's
FAKESTORE_CATEGORY_MAP, because search (what data exists) and ranking
(what attributes matter) are different concerns.
"""

from typing import Optional

from pydantic import BaseModel, Field


class ParsedIntent(BaseModel):
    category_slug: str = Field(
        description="Fine-grained category the model detected, e.g. 'headphones', 'running_shoes', 'laptop'."
    )
    category_label: str = Field(
        description="Human-readable category label, e.g. 'Electronics — Headphones'."
    )
    max_price: Optional[float] = Field(
        default=None, description="Maximum price (INR) the user stated, or null if not mentioned."
    )
    must_have_attributes: list[str] = Field(
        default_factory=list,
        description="Attributes the user explicitly required, e.g. ['Active Noise Cancellation', 'Wireless'].",
    )
    raw_query: str = Field(description="The original, unmodified user query.")