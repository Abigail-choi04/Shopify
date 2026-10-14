"""
ShopMate AI — Cart Mandate Schemas (Phase 7)

A "Cart Mandate" is a record of exactly what the shopper approved to buy:
one product, one price, one quantity, one seller, valid until one time.
Once approved, the server signs it (HMAC) so that any later change to the
item, price, or quantity is detected and the checkout is refused.

This is a MOCK: no real payment ever happens. Same idea as the AP2
(Agent Payments Protocol) "cart mandate", simplified for a class project.
"""

from typing import Optional

from pydantic import BaseModel, Field


class MandateCreate(BaseModel):
    product_id: str  # e.g. "flipkart-MOBGTAGPTB3VS24W"
    quantity: int = Field(default=1, ge=1, le=5)


class ApproveRequest(BaseModel):
    consent: bool = False  # the shopper must explicitly tick the box


class MandateEvent(BaseModel):
    at: str
    event: str  # drafted | approved | approval_refused | price_changed | signature_invalid | checked_out | cancelled | expired
    detail: str = ""


class Mandate(BaseModel):
    id: str
    status: str  # draft | approved | completed | cancelled | rejected | expired
    mandate_type: str = "mock_cart_mandate_v1"
    product_id: str
    title: str
    merchant: Optional[str] = None
    url: Optional[str] = None
    image_url: Optional[str] = None
    unit_price_inr: float
    quantity: int
    total_inr: float
    currency: str = "INR"
    price_captured_at: Optional[str] = None  # when the price was captured, e.g. "2026-10-08"
    price_note: Optional[str] = None
    created_at: str
    expires_at: str
    approved_at: Optional[str] = None
    completed_at: Optional[str] = None
    user_consent: bool = False
    signature: Optional[str] = None  # set only when approved
    order_id: Optional[str] = None  # set only when the mock checkout completes
    status_reason: Optional[str] = None  # why it was rejected / cancelled / expired
    terms: str = "Mock only: no real payment is taken and nothing is ordered from the seller."


class MandateResponse(BaseModel):
    mandate: Mandate
    events: list[MandateEvent]
    storage: str  # where the audit log is kept: "postgres" or "local sqlite file"