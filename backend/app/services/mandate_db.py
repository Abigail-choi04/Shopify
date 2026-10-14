"""
ShopMate AI — Mandate Storage (Phase 7)

Keeps every mandate and its audit log (what happened, and when) in a
small database, using SQLAlchemy.

Which database:
  1. MANDATE_DB_URL if set, otherwise
  2. DATABASE_URL (your Supabase Postgres connection string), otherwise
  3. a local SQLite file: backend/data_private/mandates.db

If the Postgres connection fails, it falls back to the local file and
logs a warning — and every API answer says which storage was used
("storage": "postgres" or "local sqlite file"), so it is never silent.

Two tables are created automatically the first time they are needed:
  shopmate_mandates        (id, status, data as JSON text, updated_at)
  shopmate_mandate_events  (id, mandate_id, at, event, detail)
"""

import json
import logging
import os

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, create_engine, insert, select, update

from app.services import snapshot_store

logger = logging.getLogger("uvicorn.error")

metadata = MetaData()

mandates_table = Table(
    "shopmate_mandates",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("status", String(20), nullable=False),
    Column("data", Text, nullable=False),
    Column("updated_at", String(40), nullable=False),
)

events_table = Table(
    "shopmate_mandate_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("mandate_id", String(40), nullable=False, index=True),
    Column("at", String(40), nullable=False),
    Column("event", String(40), nullable=False),
    Column("detail", Text, nullable=False, default=""),
)

_state: dict = {"key": None, "engine": None, "label": None}


def reset() -> None:
    """Forget the cached connection (used by tests)."""
    engine = _state.get("engine")
    if engine is not None:
        engine.dispose()
    _state.update({"key": None, "engine": None, "label": None})


def _local_engine():
    folder = snapshot_store.snapshot_dir()
    folder.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{folder / 'mandates.db'}"), "local sqlite file"


def _connect():
    url = os.getenv("MANDATE_DB_URL") or os.getenv("DATABASE_URL") or ""
    if url:
        try:
            is_postgres = url.startswith("postgres")
            engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5} if is_postgres else {})
            metadata.create_all(engine)
            return engine, "postgres" if is_postgres else "sqlite database"
        except Exception as error:  # noqa: BLE001 - any connection problem means "use the local file"
            logger.warning("Mandate storage: could not use the configured database (%s). Using a local file instead.", type(error).__name__)
    engine, label = _local_engine()
    metadata.create_all(engine)
    return engine, label


def get_engine():
    key = (os.getenv("MANDATE_DB_URL") or os.getenv("DATABASE_URL") or "") + "|" + str(snapshot_store.snapshot_dir())
    if _state["key"] != key or _state["engine"] is None:
        reset()
        engine, label = _connect()
        _state.update({"key": key, "engine": engine, "label": label})
    return _state["engine"]


def storage_label() -> str:
    get_engine()
    return _state["label"]


def save_mandate(mandate: dict, updated_at: str) -> None:
    engine = get_engine()
    payload = json.dumps(mandate, ensure_ascii=False)
    with engine.begin() as conn:
        existing = conn.execute(select(mandates_table.c.id).where(mandates_table.c.id == mandate["id"])).first()
        if existing:
            conn.execute(
                update(mandates_table)
                .where(mandates_table.c.id == mandate["id"])
                .values(status=mandate["status"], data=payload, updated_at=updated_at)
            )
        else:
            conn.execute(insert(mandates_table).values(id=mandate["id"], status=mandate["status"], data=payload, updated_at=updated_at))


def load_mandate(mandate_id: str) -> dict | None:
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(select(mandates_table.c.data).where(mandates_table.c.id == mandate_id)).first()
    return json.loads(row[0]) if row else None


def add_event(mandate_id: str, at: str, event: str, detail: str = "") -> None:
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(insert(events_table).values(mandate_id=mandate_id, at=at, event=event, detail=detail))


def load_events(mandate_id: str) -> list[dict]:
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            select(events_table.c.at, events_table.c.event, events_table.c.detail)
            .where(events_table.c.mandate_id == mandate_id)
            .order_by(events_table.c.id)
        ).all()
    return [{"at": r[0], "event": r[1], "detail": r[2]} for r in rows]