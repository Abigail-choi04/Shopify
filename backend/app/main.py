"""
ShopMate AI — Backend Entrypoint

Phase 0: health checks proving frontend/backend/database can talk.
Phase 1: adds the /products router (FakeStoreAPI-backed, normalized).
Phase 3: adds the /chat router (LangGraph agent, with Phase 2's Groq
intent parsing collapsed into the planner node).
Phase 7: adds the /mandates router (mock Cart Mandate: approve, sign, mock checkout).
"""

import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text

from app.routers import chat, mandates, products

load_dotenv()

app = FastAPI(title="ShopMate AI Backend", version="0.7.0")

# CORS (Cross-Origin Resource Sharing) — lets the Vite frontend
# (running on a different port) call this backend during local dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(products.router)
app.include_router(chat.router)
app.include_router(mandates.router)

DATABASE_URL = os.getenv("DATABASE_URL", "")


@app.get("/health")
def health_check():
    """Basic liveness check — no dependencies touched."""
    return {"status": "ok", "service": "shopmate-backend"}


@app.get("/health/db")
def health_check_db():
    """
    Confirms the backend can actually reach Postgres.
    If this fails, check your .env has the right DATABASE_URL
    (Supabase connection string).
    """
    if not DATABASE_URL:
        return {"status": "error", "detail": "DATABASE_URL not set in .env"}

    try:
        engine = create_engine(DATABASE_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "service": "postgres"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}