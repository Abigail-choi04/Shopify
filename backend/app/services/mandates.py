"""
ShopMate AI — Cart Mandate Logic (Phase 7, MOCK — no real payment)

The agent can only PROPOSE a purchase. This module makes sure nothing
is "bought" unless the shopper approved exactly that cart:

  1. create_draft  — the SERVER looks up the product and its rupee price
                     (it never trusts a price sent by the browser).
  2. approve       — needs the shopper's explicit consent; re-checks the
                     price; then SIGNS the cart (HMAC-SHA256, a tamper-proof
                     stamp made with a secret key only the server knows).
  3. checkout      — refuses unless the signature still matches the cart,
                     the mandate is unexpired and unused, and the price has
                     not changed since approval. Then returns a pretend order.
  4. cancel        — the shopper can withdraw a draft or approved mandate.

Every step is written to an audit log (see mandate_db.py).

Settings (.env):
  MANDATE_SECRET        the signing key. Set your own long random text!
  MANDATE_TTL_MINUTES   how long a mandate stays valid (default 15)
"""

import hashlib
import hmac
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from app.schemas.product import Product
from app.services import currency, mandate_db, product_catalog, snapshot_store

logger = logging.getLogger("uvicorn.error")

DEV_SECRET = "dev-only-secret-please-set-MANDATE_SECRET"
FINAL_STATES = {"completed", "cancelled", "rejected", "expired"}


class MandateError(Exception):
    """A refused action. `code` is for programs, `message` is safe to show the shopper."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


# ---------- small helpers ----------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(moment: datetime | None = None) -> str:
    return (moment or _now()).isoformat(timespec="seconds")


def ttl_minutes() -> float:
    try:
        return float(os.getenv("MANDATE_TTL_MINUTES", "15"))
    except ValueError:
        return 15.0


def _secret() -> bytes:
    secret = os.getenv("MANDATE_SECRET")
    if not secret:
        logger.warning("MANDATE_SECRET is not set; using the built-in development key. Set your own in .env.")
        secret = DEV_SECRET
    return secret.encode("utf-8")


def _signed_fields(m: dict) -> dict:
    """Exactly the facts the shopper approved. Change any one and the signature breaks."""
    return {
        "id": m["id"],
        "product_id": m["product_id"],
        "title": m["title"],
        "merchant": m.get("merchant"),
        "unit_price_inr": m["unit_price_inr"],
        "quantity": m["quantity"],
        "total_inr": m["total_inr"],
        "currency": m["currency"],
        "expires_at": m["expires_at"],
    }


def sign(m: dict) -> str:
    canonical = json.dumps(_signed_fields(m), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hmac.new(_secret(), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def _log(mandate_id: str, event: str, detail: str = "") -> None:
    mandate_db.add_event(mandate_id, _stamp(), event, detail)


def _save(m: dict) -> None:
    mandate_db.save_mandate(m, _stamp())


def _same_price(a: float, b: float) -> bool:
    return abs(a - b) < 0.005


async def lookup_product(product_id: str) -> Product | None:
    """The server's own copy of the product (never the browser's)."""
    if product_id.startswith("serpapi-"):
        raise MandateError(
            "unsupported_source",
            "This listing came from a web search, so the server cannot re-check its price. Open the listing to buy it directly.",
            422,
        )
    if product_id.startswith("flipkart-"):
        return snapshot_store.get_product(product_id)
    if product_id.startswith("fakestore-"):
        products = await product_catalog.get_all_normalized_products()
        found = next((p for p in products if p.id == product_id), None)
        if found is None:
            return None
        return (await currency.convert_products([found]))[0]
    return None


def _current_price(product: Product | None) -> float:
    if product is None:
        raise MandateError("product_not_found", "That product is no longer in the catalog.", 404)
    if product.price_inr is None:
        raise MandateError("no_rupee_price", "This product has no rupee price, so it cannot be put in a cart.", 422)
    return float(product.price_inr)


def _load(mandate_id: str) -> dict:
    m = mandate_db.load_mandate(mandate_id)
    if m is None:
        raise MandateError("not_found", "No such mandate.", 404)
    return _expire_if_needed(m)


def _expire_if_needed(m: dict) -> dict:
    if m["status"] in ("draft", "approved") and _now() > datetime.fromisoformat(m["expires_at"]):
        m["status"] = "expired"
        m["status_reason"] = "The mandate was not completed in time."
        _save(m)
        _log(m["id"], "expired", "Time limit passed before checkout.")
    return m


def _require_state(m: dict, allowed: set[str], action: str) -> None:
    if m["status"] == "expired":
        raise MandateError("expired", "This mandate has expired. Start again from the product.", 410)
    if m["status"] not in allowed:
        reason = {
            "completed": "it has already been used",
            "cancelled": "it was cancelled",
            "rejected": f"it was rejected ({m.get('status_reason') or 'see the audit log'})",
            "draft": "it has not been approved yet",
            "approved": "it is already approved",
        }.get(m["status"], f"it is {m['status']}")
        raise MandateError("wrong_state", f"Cannot {action}: {reason}.", 409)


def _reject(m: dict, event: str, reason: str) -> None:
    m["status"] = "rejected"
    m["status_reason"] = reason
    _save(m)
    _log(m["id"], event, reason)


# ---------- the four actions ----------


async def create_draft(product_id: str, quantity: int = 1) -> dict:
    if not 1 <= quantity <= 5:
        raise MandateError("bad_quantity", "Quantity must be between 1 and 5.", 422)
    product = await lookup_product(product_id)
    unit = _current_price(product)
    created = _now()
    m = {
        "id": "mnd_" + uuid.uuid4().hex[:12],
        "status": "draft",
        "mandate_type": "mock_cart_mandate_v1",
        "product_id": product.id,
        "title": product.title,
        "merchant": product.merchant,
        "url": product.url,
        "image_url": product.image_url,
        "unit_price_inr": unit,
        "quantity": quantity,
        "total_inr": round(unit * quantity, 2),
        "currency": "INR",
        "price_captured_at": product.captured_at,
        "price_note": (
            f"Price from a saved listing dated {snapshot_store.format_date(product.captured_at)}; it may differ today."
            if product.source == "flipkart_snapshot"
            else None
        ),
        "created_at": _stamp(created),
        "expires_at": _stamp(created + timedelta(minutes=ttl_minutes())),
        "approved_at": None,
        "completed_at": None,
        "user_consent": False,
        "signature": None,
        "order_id": None,
        "status_reason": None,
        "terms": "Mock only: no real payment is taken and nothing is ordered from the seller.",
    }
    _save(m)
    _log(m["id"], "drafted", f"{quantity} x {product.title} at {unit:.2f} INR")
    return m


async def approve(mandate_id: str, consent: bool) -> dict:
    m = _load(mandate_id)
    _require_state(m, {"draft"}, "approve")
    if not consent:
        _log(m["id"], "approval_refused", "The shopper did not give consent.")
        raise MandateError("no_consent", "Tick the consent box to approve this purchase.", 422)

    current = _current_price(await lookup_product(m["product_id"]))
    if not _same_price(current, m["unit_price_inr"]):
        _reject(m, "price_changed", f"Price moved from {m['unit_price_inr']:.2f} to {current:.2f} INR before approval.")
        raise MandateError("price_changed", "The price changed while you were deciding, so this mandate was cancelled. Please start again.", 409)

    m["user_consent"] = True
    m["approved_at"] = _stamp()
    m["status"] = "approved"
    m["signature"] = sign(m)
    _save(m)
    _log(m["id"], "approved", "Consent given; cart signed.")
    return m


async def checkout(mandate_id: str) -> dict:
    m = _load(mandate_id)
    _require_state(m, {"approved"}, "check out")

    expected = sign(m)
    if not m.get("signature") or not hmac.compare_digest(expected, m["signature"]):
        _reject(m, "signature_invalid", "The cart no longer matches what was approved.")
        raise MandateError("signature_invalid", "This cart does not match what was approved, so checkout was refused.", 409)

    current = _current_price(await lookup_product(m["product_id"]))
    if not _same_price(current, m["unit_price_inr"]):
        _reject(m, "price_changed", f"Price moved from {m['unit_price_inr']:.2f} to {current:.2f} INR after approval.")
        raise MandateError("price_changed", "The price changed after you approved, so checkout was refused.", 409)

    m["status"] = "completed"
    m["completed_at"] = _stamp()
    m["order_id"] = "MOCK-" + uuid.uuid4().hex[:8].upper()
    _save(m)
    _log(m["id"], "checked_out", f"Mock order {m['order_id']} (no payment taken).")
    return m


def cancel(mandate_id: str) -> dict:
    m = _load(mandate_id)
    _require_state(m, {"draft", "approved"}, "cancel")
    m["status"] = "cancelled"
    m["status_reason"] = "Cancelled by the shopper."
    _save(m)
    _log(m["id"], "cancelled", "Cancelled by the shopper.")
    return m


def get(mandate_id: str) -> tuple[dict, list[dict]]:
    m = _load(mandate_id)
    return m, mandate_db.load_events(mandate_id)