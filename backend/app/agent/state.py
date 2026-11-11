"""
ShopMate AI — Agent State (Phase 3, extended in Phase 5)

LangGraph passes this dict between nodes, with each node returning the
fields it updates. Using a TypedDict (rather than a Pydantic model) is
LangGraph's standard pattern — it works with LangGraph's built-in
state-merging without extra configuration.
"""

from typing import TypedDict

from app.schemas.agent import ChatResponse, Claim, DroppedClaim, TraceStep
from app.schemas.intent import ParsedIntent


class AgentState(TypedDict, total=False):
    raw_query: str
    parsed_intent: ParsedIntent
    candidate_products: list  # list[Product], left untyped here to avoid a circular import
    ranked_products: list  # list[Product]
    trace: list[TraceStep]
    call_counter: int
    final_response: ChatResponse

    # --- Phase 5: grounding + verification ---
    search_call_id: str  # the tool call that retrieved the products (source of price/rating facts)
    rank_call_id: str  # the tool call that produced the ranking (source of rank facts)
    proposed_claims: dict[str, list[Claim]]  # product_id -> claims the LLM wrote (unchecked)
    verified_claims: dict[str, list[Claim]]  # product_id -> claims that passed the verifier
    dropped_claims: list[DroppedClaim]
    claims_checked: int
    claims_verified: int
    retry_count: int  # how many times the explain step has been re-run after failures
    verify_feedback: str  # what to tell the LLM on the retry
    verification_done: bool  # True once verify has made its final decision

    # --- Phase 4: saved snapshot, requirements, web fallback ---
    requirement_results: dict  # product_id -> list[RequirementResult]
    product_call_ids: dict  # product_id -> the tool call that retrieved it (search, or the web fallback)
    data_source_note: str  # e.g. "Flipkart snapshot, captured 8 Oct 2026"

    # --- Replanning (constraint relaxation) ---
    original_intent: ParsedIntent  # what the shopper actually asked for, before anything was loosened
    replan_count: int  # how many loosening steps have been applied
    relaxations: list  # list[replan.Relaxation], in the order they were applied

    # --- Clarifying questions ---
    allow_clarification: bool  # False when the query already answers an earlier question

    # --- Verifier demo ("inject an error") ---
    demo_tamper: bool  # True when the shopper asked to see the checker catch a deliberately wrong claim
    demo_tamper_info: dict  # which claim was altered, and (once checked) the checker's verdict