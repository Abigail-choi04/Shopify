"""
ShopMate AI — Phase 7 tests: mock Cart Mandate (no internet, no real database)

Run from the backend/ folder:   python -m pytest tests -q
A throw-away local SQLite file is used for storage in every test.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from conftest import flipkart_record
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.main import app
from app.services import mandate_db, mandates, snapshot_store


@pytest.fixture
def client(write_snapshot):
    write_snapshot({"earphones": [flipkart_record("A", title="Nova Buds", price=1499)]})
    return TestClient(app)


def _draft(client, product_id="flipkart-A", quantity=1):
    return client.post("/mandates", json={"product_id": product_id, "quantity": quantity})


def _approved(client):
    mandate_id = _draft(client).json()["mandate"]["id"]
    response = client.post(f"/mandates/{mandate_id}/approve", json={"consent": True})
    return mandate_id, response


def _edit_stored(mandate_id, **changes):
    """Simulates someone tampering with the saved record."""
    engine = mandate_db.get_engine()
    data = mandate_db.load_mandate(mandate_id)
    data.update(changes)
    with engine.begin() as conn:
        conn.execute(update(mandate_db.mandates_table).where(mandate_db.mandates_table.c.id == mandate_id).values(data=json.dumps(data), status=data["status"]))


def _error(response):
    return response.json()["detail"]["code"]


def test_draft_uses_the_servers_price_and_is_unsigned(client):
    response = _draft(client, quantity=2)
    assert response.status_code == 200
    body = response.json()
    m = body["mandate"]
    assert (m["status"], m["unit_price_inr"], m["quantity"], m["total_inr"]) == ("draft", 1499, 2, 2998)
    assert m["signature"] is None and m["user_consent"] is False
    assert body["storage"] == "local sqlite file"
    assert [e["event"] for e in body["events"]] == ["drafted"]


def test_browser_cannot_set_the_price(client):
    response = client.post("/mandates", json={"product_id": "flipkart-A", "quantity": 1, "unit_price_inr": 1})
    assert response.json()["mandate"]["unit_price_inr"] == 1499


def test_unknown_product_and_web_listing_are_refused(client):
    assert _error(_draft(client, "flipkart-NOPE")) == "product_not_found"
    assert _error(_draft(client, "serpapi-abc")) == "unsupported_source"
    assert _error(_draft(client, "mystery-1")) == "product_not_found"


def test_quantity_limits(client):
    assert _draft(client, quantity=0).status_code == 422
    assert _draft(client, quantity=6).status_code == 422


def test_approval_needs_consent(client):
    mandate_id = _draft(client).json()["mandate"]["id"]
    response = client.post(f"/mandates/{mandate_id}/approve", json={"consent": False})
    assert _error(response) == "no_consent"
    shown = client.get(f"/mandates/{mandate_id}").json()
    assert shown["mandate"]["status"] == "draft"
    assert "approval_refused" in [e["event"] for e in shown["events"]]


def test_approve_signs_and_checkout_completes(client):
    mandate_id, approved = _approved(client)
    m = approved.json()["mandate"]
    assert m["status"] == "approved" and m["user_consent"] is True and len(m["signature"]) == 64

    done = client.post(f"/mandates/{mandate_id}/checkout")
    assert done.status_code == 200
    final = done.json()
    assert final["mandate"]["status"] == "completed"
    assert final["mandate"]["order_id"].startswith("MOCK-")
    assert [e["event"] for e in final["events"]] == ["drafted", "approved", "checked_out"]


def test_checkout_before_approval_is_refused(client):
    mandate_id = _draft(client).json()["mandate"]["id"]
    assert _error(client.post(f"/mandates/{mandate_id}/checkout")) == "wrong_state"


def test_a_mandate_can_only_be_used_once(client):
    mandate_id, _ = _approved(client)
    assert client.post(f"/mandates/{mandate_id}/checkout").status_code == 200
    assert _error(client.post(f"/mandates/{mandate_id}/checkout")) == "wrong_state"


def test_tampered_price_is_caught_by_the_signature(client):
    mandate_id, _ = _approved(client)
    _edit_stored(mandate_id, unit_price_inr=1.0, total_inr=1.0)
    response = client.post(f"/mandates/{mandate_id}/checkout")
    assert _error(response) == "signature_invalid"
    shown = client.get(f"/mandates/{mandate_id}").json()
    assert shown["mandate"]["status"] == "rejected"
    assert "signature_invalid" in [e["event"] for e in shown["events"]]


def test_tampered_quantity_is_caught(client):
    mandate_id, _ = _approved(client)
    _edit_stored(mandate_id, quantity=5)
    assert _error(client.post(f"/mandates/{mandate_id}/checkout")) == "signature_invalid"


def test_a_different_secret_cannot_check_out(client, monkeypatch):
    mandate_id, _ = _approved(client)
    monkeypatch.setenv("MANDATE_SECRET", "someone-elses-secret")
    assert _error(client.post(f"/mandates/{mandate_id}/checkout")) == "signature_invalid"


def test_price_change_after_approval_blocks_checkout(client, write_snapshot):
    mandate_id, _ = _approved(client)
    write_snapshot({"earphones": [flipkart_record("A", title="Nova Buds", price=1799)]})
    assert _error(client.post(f"/mandates/{mandate_id}/checkout")) == "price_changed"
    assert client.get(f"/mandates/{mandate_id}").json()["mandate"]["status"] == "rejected"


def test_price_change_before_approval_rejects_the_draft(client, write_snapshot):
    mandate_id = _draft(client).json()["mandate"]["id"]
    write_snapshot({"earphones": [flipkart_record("A", title="Nova Buds", price=999)]})
    response = client.post(f"/mandates/{mandate_id}/approve", json={"consent": True})
    assert _error(response) == "price_changed"


def test_expired_mandate_cannot_be_approved_or_checked_out(client):
    mandate_id = _draft(client).json()["mandate"]["id"]
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds")
    _edit_stored(mandate_id, expires_at=past)
    assert _error(client.post(f"/mandates/{mandate_id}/approve", json={"consent": True})) == "expired"
    shown = client.get(f"/mandates/{mandate_id}").json()
    assert shown["mandate"]["status"] == "expired"
    assert "expired" in [e["event"] for e in shown["events"]]


def test_cancel(client):
    mandate_id, _ = _approved(client)
    assert client.post(f"/mandates/{mandate_id}/cancel").json()["mandate"]["status"] == "cancelled"
    assert _error(client.post(f"/mandates/{mandate_id}/checkout")) == "wrong_state"


def test_unknown_mandate_id(client):
    assert client.get("/mandates/mnd_nope").status_code == 404


def test_signature_depends_on_the_approved_fields():
    base = {"id": "m", "product_id": "p", "title": "T", "merchant": "Flipkart", "unit_price_inr": 10.0, "quantity": 1,
            "total_inr": 10.0, "currency": "INR", "expires_at": "2026-10-14T10:00:00+00:00"}
    assert mandates.sign(base) == mandates.sign(dict(base))
    assert mandates.sign(base) != mandates.sign({**base, "quantity": 2})
    assert mandates.sign(base) != mandates.sign({**base, "unit_price_inr": 11.0})
    assert mandates.sign(base) == mandates.sign({**base, "url": "ignored-field"})


def test_falls_back_to_a_local_file_when_the_database_is_unreachable(client, monkeypatch):
    monkeypatch.setenv("MANDATE_DB_URL", "postgresql://nobody:x@127.0.0.1:1/none")
    mandate_db.reset()
    response = _draft(client)
    assert response.status_code == 200
    assert response.json()["storage"] == "local sqlite file"