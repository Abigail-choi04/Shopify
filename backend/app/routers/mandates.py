"""
ShopMate AI — Mandates Router (Phase 7, MOCK checkout)

  POST /mandates                  start a draft cart for one product
  POST /mandates/{id}/approve     the shopper consents; the server signs it
  POST /mandates/{id}/checkout    mock checkout (refused if anything changed)
  POST /mandates/{id}/cancel      withdraw it
  GET  /mandates/{id}             the mandate plus its audit log

Refusals come back as {"detail": {"code": "...", "message": "..."}} with a
fitting HTTP status, so the screen can show `message` to the shopper.
"""

from fastapi import APIRouter, HTTPException

from app.schemas.mandate import ApproveRequest, Mandate, MandateCreate, MandateResponse
from app.services import mandate_db, mandates

router = APIRouter(prefix="/mandates", tags=["mandates"])


def _respond(m: dict, events: list[dict] | None = None) -> MandateResponse:
    return MandateResponse(
        mandate=Mandate(**m),
        events=events if events is not None else mandate_db.load_events(m["id"]),
        storage=mandate_db.storage_label(),
    )


def _fail(error: mandates.MandateError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail={"code": error.code, "message": error.message})


@router.post("", response_model=MandateResponse)
async def create_mandate(request: MandateCreate):
    try:
        return _respond(await mandates.create_draft(request.product_id, request.quantity))
    except mandates.MandateError as error:
        raise _fail(error)


@router.post("/{mandate_id}/approve", response_model=MandateResponse)
async def approve_mandate(mandate_id: str, request: ApproveRequest):
    try:
        return _respond(await mandates.approve(mandate_id, request.consent))
    except mandates.MandateError as error:
        raise _fail(error)


@router.post("/{mandate_id}/checkout", response_model=MandateResponse)
async def checkout_mandate(mandate_id: str):
    try:
        return _respond(await mandates.checkout(mandate_id))
    except mandates.MandateError as error:
        raise _fail(error)


@router.post("/{mandate_id}/cancel", response_model=MandateResponse)
async def cancel_mandate(mandate_id: str):
    try:
        return _respond(mandates.cancel(mandate_id))
    except mandates.MandateError as error:
        raise _fail(error)


@router.get("/{mandate_id}", response_model=MandateResponse)
async def read_mandate(mandate_id: str):
    try:
        m, events = mandates.get(mandate_id)
        return _respond(m, events)
    except mandates.MandateError as error:
        raise _fail(error)