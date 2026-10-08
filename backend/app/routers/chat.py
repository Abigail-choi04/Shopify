"""
ShopMate AI — Chat Router (Phase 3, error handling improved in Phase 5)

The one real endpoint the frontend will eventually call instead of
pickScenario() in scenarios.js. Takes a natural-language query, runs
it through the LangGraph agent, and returns a response shaped exactly
like a scenarios.js entry (aisle, parsedIntent, trace, comparisonAttributes,
products), plus Phase 5's optional `verification` summary.
"""

import logging

from fastapi import APIRouter, HTTPException

from app.agent.graph import run_agent
from app.schemas.agent import ChatRequest, ChatResponse

logger = logging.getLogger("uvicorn.error")

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Runs the full planner -> search -> rank -> explain -> verify -> respond
    agent loop for one query. No conversation history yet (that's Phase 6
    session memory) — every call is a fresh, independent run.
    """
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    try:
        return await run_agent(request.query)
    except RuntimeError as e:
        # Raised by groq_client if GROQ_API_KEY is missing — surface it
        # clearly instead of a generic 500.
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        # Anything else (Groq outage, bad model output, a bug): log the full
        # traceback in the terminal and return a readable message, not a bare 500.
        logger.exception("Unhandled error in /chat")
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")