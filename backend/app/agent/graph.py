"""
ShopMate AI — LangGraph Agent (Phase 3 + Phase 5 grounding/verification + Phase 4 real data)

Graph shape:

    planner -> search -> rank -> explain -> verify --(all good, or retry used up)--> respond
                                   ^           |
                                   +-----------+  (some claims failed, one rewrite allowed)

- planner: calls Groq to turn the raw query into a ParsedIntent
  (category, budget, must-haves). This IS Phase 2's job, done as this
  graph's first internal step.
- search: calls the search_products tool against the saved Flipkart
  snapshot (or the toy catalog if the snapshot is missing), checks the
  shopper's must-haves against each product's listed specs (leaving out
  products the listing clearly contradicts), and, if too few products
  remain and SerpAPI is switched on, adds Google Shopping results.
- rank: calls the rank_products tool: review-weighted rating, price, and
  how many requirements the specs confirm (see tools.py).
- explain (Phase 5): calls Groq to write each product's reasoning as
  separate, checkable CLAIMS, each citing the tool call it came from.
- verify (Phase 5): plain-Python check of every claim against the real
  product data (app/agent/verifier.py). If something fails, the model
  gets ONE chance to rewrite; anything still failing is dropped and the
  trace says so. Nothing unverified ever reaches the shopper.
- respond: assembles the final ChatResponse from verified claims only.

Every tool call gets a short ID (call_001, call_002, ...) logged in the
trace; claims must cite one of these, and the verifier enforces it.
"""

import json

from langgraph.graph import END, StateGraph
from pydantic import ValidationError

from app.agent.ranking import (
    CATEGORY_ICONS,
    SEARCH_WORDS,
    attribute_label,
    get_ranking_attributes,
    get_snapshot_category,
)
from app.agent.requirements import CONFLICT, MET, NOT_MET, UNCONFIRMED, RequirementResult
from app.agent.state import AgentState
from app.agent.tools import filter_by_requirements, rank_products, search_products
from app.agent.verifier import BUDGET_CURRENCY, unconfirmed_requirements, verify_product_claims
from app.normalizers.spec_facts import COMPARISON_SPECS
from app.schemas.agent import (
    ChatResponse,
    Claim,
    DroppedClaim,
    ExplainOutput,
    ParsedIntentOut,
    RankedProduct,
    RequirementOut,
    TraceStep,
    VerificationSummary,
)
from app.schemas.intent import ParsedIntent
from app.schemas.product import Product
from app.services import product_catalog, serpapi_client, snapshot_store
from app.services.currency import convert_products, describe_conversions, format_inr, format_listed_price
from app.services.groq_client import call_groq_json

MAX_EXPLAIN_RETRIES = 1  # how many times the model may rewrite its claims after a failed check
MIN_RESULTS_BEFORE_FALLBACK = 3  # fewer matches than this -> try the web fallback (if switched on)

PLANNER_SYSTEM_PROMPT = """You are the planning component of an agentic shopping assistant.
Given a user's natural-language shopping request, extract structured intent.

Respond with ONLY a JSON object matching this exact shape:
{
  "category_slug": string (one of: "headphones" (earphones, earbuds, headphones), "smartphone", "laptop", "running_shoes", "smartwatch", or a short snake_case slug you invent if none fit),
  "category_label": string (human-readable, e.g. "Electronics — Headphones"),
  "max_price": number or null (in INR rupees, extracted from the query if a budget is mentioned, else null. Understand Indian number words: "5k" = 5000, "50k" = 50000, "1.5 lakh" or "1.5 lakhs" = 150000, "2 lakh" = 200000, "1 crore" = 10000000, "5,000" = 5000. A plain number like "under 5000" is rupees. If the user states a budget in another currency, set max_price to null),
  "must_have_attributes": array of strings (explicit requirements stated in the query, one short phrase each, keeping any numbers, e.g. ["Active Noise Cancellation", "Wireless", "8GB RAM", "5G", "40 hours battery"]; do NOT repeat the budget here; empty array if none stated)
}

Do not include any text outside the JSON object."""

EXPLAIN_SYSTEM_PROMPT = """You write the reasoning shown next to each recommended product in a shopping assistant.
You will receive a JSON object of FACTS about the ranked products. You must write short, checkable CLAIMS using ONLY those facts.

Respond with ONLY a JSON object of this exact shape:
{
  "products": [
    {
      "product_id": string (copied exactly from the facts),
      "claims": [
        {
          "field": one of "price" | "rating" | "rating_count" | "category" | "within_budget" | "rank" | "spec",
          "key": only for "spec" claims: the spec name, copied from that product's "specs",
          "value": the exact value from the facts (a number, a string, true/false for yes/no specs, or true for within_budget),
          "text": one short sentence for the shopper that states this fact,
          "source_tool_call_id": the call ID the fact came from
        }
      ]
    }
  ]
}

Rules:
- Use ONLY values present in the facts. Never mention features, materials, battery life, noise cancellation or any other specification unless it is in that product's "specs".
- Every claim must cite a call ID: use the product's "fact_call_id" for price, rating, rating_count, category, within_budget and spec; use "rank_call_id" for rank.
- A "spec" claim needs "key" (one of that product's "specs" keys) and "value" (exactly the spec's value). The sentence must say exactly what the value says: if the value is false the sentence must say the product does NOT have it. Give 1 to 3 spec claims per product when it has specs, preferring specs that match the shopper's requirements (see "requirements") and the most useful ones for comparing.
- Never say a requirement is met unless its status is "met". Do not mention requirements whose status is unknown, conflict or unsupported; the app reports those itself.
- Each sentence may contain only numbers that appear in the facts (price, rating, review count, budget, rank position, or the spec value being stated).
- Every price in the facts is in Indian rupees. Write prices with the ₹ symbol only, never $ or any other currency symbol. Whole rupees are fine (e.g. ₹9,592).
- If a product has "price_is_converted": true, its rupee price was converted from another currency, so say "about" or "around" before the price in your sentence (e.g. "Priced at about ₹9,592.").
- Use "within_budget" only when a budget is given AND the product's price is not null AND it is at or under the budget. Otherwise do not make a budget claim for that product.
- Write 2 to 5 claims per product. Include "rank" for every product.
- Cover every product in the facts, in the same order.
Do not include any text outside the JSON object."""


def _next_call_id(state: AgentState) -> tuple[str, int]:
    counter = state.get("call_counter", 0) + 1
    return f"call_{counter:03d}", counter


def _is_converted(product: Product) -> bool:
    return product.fx_rate is not None


def _price_text(product: Product) -> str:
    """The shopper-facing price: rupees (with '≈' if converted); the listed price if no rupee price exists."""
    if product.price_inr is None:
        return format_listed_price(product.price, product.currency)
    prefix = "≈ " if _is_converted(product) else ""
    return f"{prefix}{format_inr(product.price_inr)}"


def _price_note(product: Product) -> str | None:
    if not _is_converted(product):
        return None
    labels = {"live": "rate dated", "stale_cache": "last fetched rate, dated", "fallback": "fixed fallback rate as of"}
    return (
        f"Converted from {format_listed_price(product.price, product.currency)} at ₹{product.fx_rate:.2f} per unit "
        f"({labels.get(product.fx_source or '', 'rate dated')} {product.fx_as_of})."
    )


def _source_label(product: Product) -> str:
    if product.source == "flipkart_snapshot":
        return f"Flipkart (saved {snapshot_store.format_date(product.captured_at)})"
    if product.source == "serpapi":
        return f"Google Shopping · {product.merchant or 'unknown shop'} ({snapshot_store.format_date(product.captured_at)})"
    return "Sample catalog (toy data)"


def _attributes(product: Product) -> dict[str, str]:
    """The comparison table row for one product: price, rating, then the category's spec columns."""
    attributes = {
        "Price": _price_text(product),
        "Rating": f"{product.rating} / 5" if product.rating is not None else "Not available",
    }
    for key, label in COMPARISON_SPECS.get(product.category, []):
        fact = product.spec_facts.get(key)
        if fact is not None:
            attributes[label] = fact.display
        elif key in product.spec_conflicts:
            attributes[label] = "Listing contradicts itself"
        else:
            attributes[label] = "Not listed" if product.spec_facts else "Not available from this source"
    if product.mrp and product.price_inr:
        discount = round((product.mrp - product.price_inr) / product.mrp * 100)
        attributes["MRP"] = f"{format_inr(product.mrp)} ({discount}% off)" if discount > 0 else format_inr(product.mrp)
    attributes["Source"] = _source_label(product)
    return attributes


def _why_unconfirmed(result: RequirementResult, product: Product) -> str:
    if result.status == CONFLICT:
        return f"{result.requirement} (the listing contradicts itself)"
    if not product.spec_facts:
        return f"{result.requirement} (no spec data from this source)"
    if result.status == "unsupported":
        return f"{result.requirement} (can't be checked against the listing)"
    return f"{result.requirement} (not stated in the listing)"


def _requirement_sentences(results: list[RequirementResult], product: Product, claimed_keys: set[str]) -> str:
    """Deterministic, so grounded by construction: what the listing confirms, and what it can't."""
    confirmed = [r.evidence for r in results if r.status == MET and r.evidence and r.spec_key not in claimed_keys]
    unconfirmed = [_why_unconfirmed(r, product) for r in results if r.status in UNCONFIRMED]
    parts = []
    if confirmed:
        parts.append("Confirmed from the listing: " + "; ".join(confirmed) + ".")
    if unconfirmed:
        parts.append("Couldn't confirm: " + ", ".join(unconfirmed) + ".")
    return " ".join(parts)


def _requirement_summary(must_haves: list[str], results: dict[str, list[RequirementResult]]) -> str:
    """'noise cancellation: 31 confirmed, 18 excluded, 9 unconfirmed; ...' across all candidates."""
    lines = []
    for requirement in [m for m in must_haves if m and m.strip()]:
        counts = {"met": 0, "not_met": 0, "other": 0}
        for product_results in results.values():
            for result in product_results:
                if result.requirement == requirement:
                    counts["met" if result.status == MET else "not_met" if result.status == NOT_MET else "other"] += 1
        lines.append(f"{requirement}: {counts['met']} confirmed, {counts['not_met']} left out (listing says no), {counts['other']} unconfirmed")
    return "; ".join(lines)


async def planner_node(state: AgentState) -> dict:
    raw_query = state["raw_query"]

    trace: list[TraceStep] = [
        TraceStep(
            type="thought",
            text=f'Parsing the request: "{raw_query}" — extracting category, budget, and must-have attributes.',
        )
    ]

    intent_json = await call_groq_json(PLANNER_SYSTEM_PROMPT, raw_query)
    intent_json["raw_query"] = raw_query
    parsed_intent = ParsedIntent.model_validate(intent_json)

    call_id, counter = _next_call_id(state)
    trace.append(
        TraceStep(
            type="action",
            text=f'parse_intent(query="{raw_query}")',
            toolCallId=call_id,
        )
    )
    trace.append(
        TraceStep(
            type="observation",
            text=(
                f"Detected category '{parsed_intent.category_label}', "
                f"budget {format_inr(parsed_intent.max_price) if parsed_intent.max_price else 'not specified'}."
            ),
        )
    )

    return {"parsed_intent": parsed_intent, "trace": trace, "call_counter": counter}


async def search_node(state: AgentState) -> dict:
    parsed_intent: ParsedIntent = state["parsed_intent"]
    trace = list(state["trace"])
    slug = parsed_intent.category_slug
    must_haves = parsed_intent.must_have_attributes

    call_id, counter = _next_call_id(state)
    trace.append(
        TraceStep(
            type="action",
            text=f'search_products(category="{slug}", max_price={parsed_intent.max_price})',
            toolCallId=call_id,
        )
    )

    candidates = await search_products(slug, parsed_intent.max_price)

    snapshot = snapshot_store.load_snapshot()
    category = get_snapshot_category(slug) if snapshot is not None else None
    if snapshot is not None:
        data_source_note = f"Flipkart snapshot, captured {snapshot.captured_label}"
        if category is None:
            observation = (
                f"The saved Flipkart snapshot ({snapshot.captured_label}) doesn't cover '{slug}'. "
                "It covers earphones, smartphones, laptops, running shoes and smartwatches."
            )
        else:
            in_category = len(snapshot.category(category))
            budget_part = f"; {len(candidates)} within your budget" if parsed_intent.max_price is not None else ""
            observation = (
                f"Searched the saved Flipkart snapshot (captured {snapshot.captured_label}): "
                f"{in_category} {category.replace('_', ' ')}{budget_part}."
            )
    else:
        data_source_note = "Sample catalog (FakeStoreAPI toy data)"
        observation = f"Retrieved {len(candidates)} candidate product(s) from the catalog."
    trace.append(TraceStep(type="observation", text=observation))

    # Check the shopper's must-haves against each product's listed specs.
    known_brands = snapshot.brands(category) if snapshot is not None and category else None
    kept, excluded, results = filter_by_requirements(candidates, must_haves, known_brands)
    if [m for m in must_haves if m and m.strip()] and candidates:
        trace.append(
            TraceStep(
                type="observation",
                text=(
                    "Checked your requirements against each product's listed specs — "
                    f"{_requirement_summary(must_haves, results)}. Products whose listing clearly says no are left out; "
                    "products whose listing is silent stay in, marked as unconfirmed."
                ),
            )
        )

    product_call_ids = {p.id: call_id for p in kept}

    # Too few matches: try the web fallback, if it is switched on.
    if len(kept) < MIN_RESULTS_BEFORE_FALLBACK:
        if serpapi_client.is_enabled():
            serp_call_id, counter_after = _next_call_id({"call_counter": counter})
            counter = counter_after
            words = SEARCH_WORDS.get(category or "", slug.replace("_", " "))
            query = " ".join([words] + [m for m in must_haves if m and m.strip()]).strip()
            trace.append(
                TraceStep(type="action", text=f'serpapi_shopping_search(query="{query}", country="in")', toolCallId=serp_call_id)
            )
            try:
                found = await serpapi_client.search_shopping(query, category or slug, parsed_intent.max_price)
                web_products = await convert_products(found.products)
                if parsed_intent.max_price is not None:
                    web_products = [p for p in web_products if p.price_inr is None or p.price_inr <= parsed_intent.max_price]
                web_results = {p.id: [] for p in web_products}
                for product in web_products:
                    web_results[product.id] = filter_by_requirements([product], must_haves, known_brands)[2][product.id]
                kept = kept + web_products
                results.update(web_results)
                product_call_ids.update({p.id: serp_call_id for p in web_products})
                origin = "saved from an earlier search" if found.cached else f"search {found.searches_used} of {found.searches_limit} this month"
                trace.append(
                    TraceStep(
                        type="observation",
                        text=(
                            f"Only {len(kept) - len(web_products)} product(s) in the snapshot matched, so Google Shopping (India) was also searched "
                            f"({origin}): {len(web_products)} product(s) added. These have no spec data, so none of your requirements can be confirmed for them."
                        ),
                    )
                )
            except serpapi_client.SerpApiError as error:
                trace.append(TraceStep(type="observation", text=f"The web fallback could not be used: {error}."))
        elif snapshot is not None:
            trace.append(
                TraceStep(
                    type="observation",
                    text=f"Only {len(kept)} product(s) matched, and the web fallback is switched off, so that is everything available.",
                )
            )

    if not kept:
        if excluded:
            blockers: dict[str, int] = {}
            for _product, failed in excluded:
                blockers[failed.requirement] = blockers.get(failed.requirement, 0) + 1
            reasons = ", ".join(f"'{name}' ({count})" for name, count in sorted(blockers.items(), key=lambda kv: -kv[1]))
            trace.append(
                TraceStep(
                    type="observation",
                    text=f"No matching products were found: every product in range was left out because its listing contradicts {reasons}.",
                )
            )
        else:
            trace.append(TraceStep(type="observation", text="No matching products were found."))

    # Be open about every exchange-rate conversion applied to these prices.
    for note in describe_conversions(kept):
        trace.append(TraceStep(type="observation", text=note))

    # The budget is in INR; say so plainly if it could not be applied to some products.
    if parsed_intent.max_price is not None:
        not_comparable = [p for p in kept if p.price_inr is None]
        if not_comparable:
            trace.append(
                TraceStep(
                    type="observation",
                    text=(
                        f"Your budget ({format_inr(parsed_intent.max_price)}) could not be applied to "
                        f"{len(not_comparable)} product(s) because no exchange rate was available, so they are shown unfiltered."
                    ),
                )
            )

    # Never a silent fallback: if the live product API was down, say so.
    if snapshot is None and product_catalog.last_fetch_used_fallback():
        trace.append(
            TraceStep(
                type="observation",
                text=(
                    "Live product source was unavailable, so these results come from the "
                    "offline sample catalog instead of live data."
                ),
            )
        )

    return {
        "candidate_products": kept,
        "requirement_results": results,
        "product_call_ids": product_call_ids,
        "data_source_note": data_source_note,
        "trace": trace,
        "call_counter": counter,
        "search_call_id": call_id,
    }


async def rank_node(state: AgentState) -> dict:
    parsed_intent: ParsedIntent = state["parsed_intent"]
    candidates = state["candidate_products"]
    results = state.get("requirement_results", {})
    trace = list(state["trace"])

    has_specs = any(p.spec_facts for p in candidates)
    intended_attributes = get_ranking_attributes(parsed_intent.category_slug)
    if has_specs:
        thought = (
            f"For '{parsed_intent.category_label}', the attributes that should matter are: "
            f"{', '.join(attribute_label(a) for a in intended_attributes)}. "
            "Ranking uses each product's rating weighted by how many reviews it has (so 5.0 stars from 3 reviews "
            "doesn't beat 4.5 stars from thousands), its price, and how many of your requirements the listed specs confirm."
        )
        label = 'rank_by_attributes(attributes=["weighted_rating", "price", "requirements"])'
    else:
        thought = (
            f"For '{parsed_intent.category_label}', the attributes that should matter are: "
            f"{', '.join(attribute_label(a) for a in intended_attributes)}. "
            "These products have no structured spec data, so ranking below uses review-weighted rating and price — "
            "the only grounded fields available — rather than guessing at spec values."
        )
        label = 'rank_by_attributes(attributes=["weighted_rating", "price"])'
    trace.append(TraceStep(type="thought", text=thought))

    call_id, counter = _next_call_id(state)
    trace.append(TraceStep(type="action", text=label, toolCallId=call_id))

    ranked = rank_products(candidates, requirement_results=results)

    trace.append(
        TraceStep(
            type="observation",
            text=f"Top {len(ranked)} candidate(s) identified, grounded in the tool calls above.",
        )
    )

    return {
        "ranked_products": ranked,
        "trace": trace,
        "call_counter": counter,
        "rank_call_id": call_id,
    }


async def explain_node(state: AgentState) -> dict:
    """Phase 5: the model writes per-product CLAIMS (not free text), each citing a tool call."""
    parsed_intent: ParsedIntent = state["parsed_intent"]
    ranked = state["ranked_products"]
    trace = list(state["trace"])
    retry_count = state.get("retry_count", 0)

    call_id, counter = _next_call_id(state)
    label = "explain_products(claims_per_product=2-4)"
    if retry_count:
        label += f" — rewrite {retry_count} after failed checks"
    trace.append(TraceStep(type="action", text=label, toolCallId=call_id))

    if not ranked:
        trace.append(TraceStep(type="observation", text="No products to explain."))
        return {"proposed_claims": {}, "trace": trace, "call_counter": counter}

    results = state.get("requirement_results", {})
    call_ids = state.get("product_call_ids", {})
    facts = {
        "search_call_id": state["search_call_id"],
        "rank_call_id": state["rank_call_id"],
        "budget": parsed_intent.max_price,
        "currency": BUDGET_CURRENCY,
        "products": [
            {
                "product_id": product.id,
                "rank": position,
                "fact_call_id": call_ids.get(product.id, state["search_call_id"]),
                "title": product.title,
                "category": product.category,
                "price": product.price_inr,
                "price_is_converted": _is_converted(product),
                "rating": product.rating,
                "rating_count": product.rating_count,
                "specs": {key: {"value": fact.value, "display": fact.display} for key, fact in product.spec_facts.items()},
                "requirements": [
                    {"requirement": r.requirement, "status": r.status, "evidence": r.evidence}
                    for r in results.get(product.id, [])
                ],
            }
            for position, product in enumerate(ranked, start=1)
        ],
    }
    user_prompt = json.dumps(facts, ensure_ascii=False)
    feedback = state.get("verify_feedback")
    if feedback:
        user_prompt += "\n\n" + feedback

    proposed: dict[str, list[Claim]] = {}
    try:
        raw = await call_groq_json(EXPLAIN_SYSTEM_PROMPT, user_prompt)
        output = ExplainOutput.model_validate(raw)
        proposed = {item.product_id: item.claims for item in output.products}
        total = sum(len(claims) for claims in proposed.values())
        trace.append(
            TraceStep(type="observation", text=f"Drafted {total} claim(s) across {len(proposed)} product(s); each must now pass verification.")
        )
    except (json.JSONDecodeError, ValidationError):
        trace.append(
            TraceStep(
                type="observation",
                text="The explanation step returned malformed output, so these products fall back to plain data-only reasoning.",
            )
        )

    return {"proposed_claims": proposed, "trace": trace, "call_counter": counter}


async def verify_node(state: AgentState) -> dict:
    """Phase 5: deterministic check of every claim. One rewrite allowed, then drop what still fails."""
    parsed_intent: ParsedIntent = state["parsed_intent"]
    ranked = state["ranked_products"]
    proposed = state.get("proposed_claims", {})
    trace = list(state["trace"])
    retry_count = state.get("retry_count", 0)

    call_id, counter = _next_call_id(state)
    trace.append(TraceStep(type="action", text="verify_claims(against=tool_outputs)", toolCallId=call_id))

    valid_call_ids = {step.toolCallId for step in trace if step.type == "action" and step.toolCallId}
    call_ids = state.get("product_call_ids", {})
    results = state.get("requirement_results", {})

    verified_by_product: dict[str, list[Claim]] = {}
    failures: list[tuple[str, Claim, str]] = []  # (product_id, claim, reason)
    checked = 0

    for position, product in enumerate(ranked, start=1):
        claims = proposed.get(product.id, [])
        checked += len(claims)
        verified, failed = verify_product_claims(
            claims,
            product,
            position,
            parsed_intent.max_price,
            valid_call_ids,
            call_ids.get(product.id, state["search_call_id"]),  # the call that retrieved THIS product
            state["rank_call_id"],
            len(ranked),
        )
        verified_by_product[product.id] = verified
        failures.extend((product.id, claim, reason) for claim, reason in failed)

    verified_count = checked - len(failures)

    # Some claims failed and the model hasn't had its rewrite yet -> go back to explain.
    if failures and retry_count < MAX_EXPLAIN_RETRIES:
        problems = "\n".join(f'- product {pid}: "{claim.text}" -> {reason}' for pid, claim, reason in failures)
        feedback = (
            "Your previous claims failed verification against the real data:\n"
            f"{problems}\n"
            "Rewrite ALL claims for ALL products, fixing these problems. Use only the facts provided."
        )
        trace.append(
            TraceStep(
                type="observation",
                text=f"{verified_count} of {checked} claim(s) verified; {len(failures)} failed. Asking for one rewrite.",
            )
        )
        return {
            "trace": trace,
            "call_counter": counter,
            "retry_count": retry_count + 1,
            "verify_feedback": feedback,
            "verification_done": False,
        }

    # Final decision: keep the verified claims, drop the rest, and say so.
    dropped = [DroppedClaim(productId=pid, text=claim.text, reason=reason) for pid, claim, reason in failures]
    if failures:
        trace.append(
            TraceStep(
                type="observation",
                text=f"{verified_count} of {checked} claim(s) verified; {len(failures)} still failed and were dropped.",
            )
        )
    else:
        trace.append(
            TraceStep(
                type="observation",
                text=f"All {checked} claim(s) verified against the tool outputs." if checked else "No claims to verify; using data-only reasoning.",
            )
        )

    unconfirmed = unconfirmed_requirements({p.id: results.get(p.id, []) for p in ranked})
    if unconfirmed:
        trace.append(
            TraceStep(
                type="observation",
                text=(
                    f"Your requirements ({', '.join(unconfirmed)}) can't be confirmed from the listing data for some of these "
                    "products, so those are shown as unconfirmed instead of being assumed."
                ),
            )
        )

    return {
        "trace": trace,
        "call_counter": counter,
        "verified_claims": verified_by_product,
        "dropped_claims": dropped,
        "claims_checked": checked,
        "claims_verified": verified_count,
        "verification_done": True,
    }


def route_after_verify(state: AgentState) -> str:
    return "respond" if state.get("verification_done") else "explain"


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else text + "."


async def respond_node(state: AgentState) -> dict:
    parsed_intent: ParsedIntent = state["parsed_intent"]
    ranked = state["ranked_products"]
    trace = state["trace"]
    verified_by_product = state.get("verified_claims", {})
    results = state.get("requirement_results", {})
    rank_call_id = state["rank_call_id"]

    products_out = []
    for index, product in enumerate(ranked):
        claims = verified_by_product.get(product.id, [])
        if claims:
            reasoning = " ".join(_sentence(claim.text) for claim in claims)
        else:
            # Data-only fallback: built straight from the product fields, so grounded by construction.
            rating_part = f"Rated {product.rating} out of 5" if product.rating is not None else "No rating available"
            reasoning = f"{rating_part} at {_price_text(product)}."

        product_results = results.get(product.id, [])
        claimed_keys = {c.key for c in claims if c.field == "spec" and c.key}
        extra = _requirement_sentences(product_results, product, claimed_keys)
        if extra:
            reasoning = f"{reasoning} {extra}"

        products_out.append(
            RankedProduct(
                id=product.id,
                title=product.title,
                price=product.price_inr if product.price_inr is not None else product.price,
                rating=product.rating,
                ratingCount=product.rating_count,
                icon=CATEGORY_ICONS.get(product.category, "📦"),
                attributes=_attributes(product),
                reasoning=reasoning,
                sourceToolCallId=rank_call_id,
                isTopPick=(index == 0),
                claims=claims,
                currency="INR" if product.price_inr is not None else product.currency,
                priceIsApproximate=_is_converted(product),
                listedPrice=format_listed_price(product.price, product.currency) if _is_converted(product) else None,
                priceNote=_price_note(product),
                url=product.url,
                imageUrl=product.image_url,
                source=_source_label(product),
                requirements=[
                    RequirementOut(requirement=r.requirement, status=r.status, evidence=r.evidence) for r in product_results
                ],
            )
        )

    spec_columns = []
    for product in ranked:
        spec_columns = [label for _, label in COMPARISON_SPECS.get(product.category, [])]
        if spec_columns:
            break

    dropped = state.get("dropped_claims", [])
    response = ChatResponse(
        aisle=parsed_intent.category_label,
        parsedIntent=ParsedIntentOut(
            category=parsed_intent.category_label,
            budget=format_inr(parsed_intent.max_price) if parsed_intent.max_price else "Not specified",
            mustHaves=parsed_intent.must_have_attributes,
        ),
        trace=trace,
        comparisonAttributes=["Price", "Rating"] + spec_columns,
        products=products_out,
        verification=VerificationSummary(
            claimsChecked=state.get("claims_checked", 0),
            claimsVerified=state.get("claims_verified", 0),
            claimsDropped=len(dropped),
            retried=state.get("retry_count", 0) > 0,
            dropped=dropped,
        ),
        dataSource=state.get("data_source_note"),
    )

    return {"final_response": response}


def build_agent_graph():
    graph = StateGraph(AgentState)
    graph.add_node("planner", planner_node)
    graph.add_node("search", search_node)
    graph.add_node("rank", rank_node)
    graph.add_node("explain", explain_node)
    graph.add_node("verify", verify_node)
    graph.add_node("respond", respond_node)

    graph.set_entry_point("planner")
    graph.add_edge("planner", "search")
    graph.add_edge("search", "rank")
    graph.add_edge("rank", "explain")
    graph.add_edge("explain", "verify")
    graph.add_conditional_edges("verify", route_after_verify, {"respond": "respond", "explain": "explain"})
    graph.add_edge("respond", END)

    return graph.compile()


_compiled_graph = None


async def run_agent(query: str) -> ChatResponse:
    """Entry point called by the /chat router."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_agent_graph()

    initial_state: AgentState = {"raw_query": query, "trace": [], "call_counter": 0, "retry_count": 0}
    final_state = await _compiled_graph.ainvoke(initial_state)
    return final_state["final_response"]