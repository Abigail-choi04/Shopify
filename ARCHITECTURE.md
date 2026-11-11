# ShopMate AI — Architecture and Technology Choices

How the system fits together and why each technology was chosen. It also serves as material for the paper's system-design section. Everything here describes what is built; what is not built is listed in section 9.

---

## 1. System overview

The shopper types a need in plain language ("noise-cancelling earbuds under ₹3,000"). The agent plans, searches real listings, checks each requirement against what the listing states, ranks the candidates, explains each recommendation as checkable claims, verifies those claims, and returns ranked results with a visible reasoning trace. If the shopper chooses a product, a signed mock "cart mandate" captures consent; no real payment exists.

The research question is not "can an LLM recommend a product". It is **whether an agent can plan, use tools, replan when it fails, and stay grounded in real data, so that the model never decides what is true.** The model plans and phrases; deterministic code decides facts, checks claims and gates actions.

```
┌────────────┐  HTTP  ┌───────────────┐      ┌────────────────────────────────┐
│  Frontend   │◄──────►│   Backend      │◄────►│  Agent (LangGraph)              │
│ React+Vite  │        │   FastAPI      │      │  planner → search → rank →      │
│ chat, trace,│        │ /chat          │      │  explain → verify → respond     │
│ cart modal  │        │ /mandates      │      │  + clarify and replan branches  │
└────────────┘        │ /products      │      └───────────────┬────────────────┘
                       └───────┬───────┘                      │
                               │                  ┌───────────▼────────────────┐
                      ┌────────▼───────┐          │  Product data                │
                      │ Postgres        │          │  Flipkart snapshot (private) │
                      │ (Supabase):     │          │  SerpAPI web fallback (off)  │
                      │ mandate audit   │          │  FakeStoreAPI toy catalog    │
                      └────────────────┘          └─────────────────────────────┘
```

---

## 2. The agent graph

```
              (request names no kind of product)
 planner ─────────────────────────────────────────► clarify ─► END
    │
    ▼
 search ──(nothing meets every requirement)──► replan
    ▲                                            │
    └────────────(search again, loosened)────────┘
    │
    ▼
  rank ─► explain ─► verify ──(all good, or retry used up)──► respond
              ▲         │
              └─────────┘  (some claims failed: one rewrite allowed)
```

| Node | Who does the work | What it does |
|---|---|---|
| planner | Language model | Turns the request into a category, budget and must-haves (a `ParsedIntent`); writes one question if no product type is named |
| clarify | Code | Returns the planner's question instead of guessing; never asks twice |
| search | Code | Searches the snapshot by category and budget, checks every must-have against the listing, removes only products the listing clearly contradicts |
| replan | Code builds options, model picks, code checks the pick | When nothing is left: works out every single change that brings real products back, the model chooses one, a fixed rule decides if the choice is unusable; search runs again (at most twice) |
| rank | Code | Review-weighted rating, requirement matches and price |
| explain | Language model | Writes each product's reasoning as separate claims, each citing the tool call it came from |
| verify | Code | Checks every claim against the real product data; one rewrite allowed; failures are dropped |
| respond | Code | Assembles the answer from verified claims only |

Every tool call gets a short ID (`call_001`, ...) recorded in the trace. Claims must cite one, and the verifier enforces it.

**Why a fixed graph and not open-ended autonomy:** the shape is fixed on purpose, so the trace is inspectable and behaviour is reliable. The autonomy is inside the graph: the planner decides what the request means, the replanner decides which requirement to give up, and the choices differ per request. This is a constrained agent, a common and defensible pattern.

---

## 3. Layers

### 3.1 Frontend: React + Vite
Chat input, the reasoning trace, ranked product cards with requirement chips and a verification banner, a "Changed to find matches" note when replanning loosened something, a clarifying-question box, and the cart-mandate modal (draft, consent, approve, mock checkout, countdown, audit log). Vite was chosen over Next.js because FastAPI is already the API layer and there is no need for server-side rendering.

### 3.2 Backend: FastAPI
Routes: `POST /chat` (the agent), `/mandates` (create, approve, checkout, cancel, get), `/products`, `/health`, `/health/db`. FastAPI's async support suits the I/O-bound work (model calls), and Pydantic validates every request and response shape.

### 3.3 Language model: Groq, `openai/gpt-oss-120b`
Used for three jobs only: planning the request, choosing a relaxation among options the code offers, and phrasing claims. The API is OpenAI-compatible, so changing provider is a settings change. The free tier allows 200,000 tokens per day, which is why the live evaluation is resumable.

### 3.4 Agent orchestration: LangGraph
Gives explicit state at each node, which is what produces the trace, and conditional edges for the clarify and replan branches.

### 3.5 Product data
- **Flipkart snapshot (main source).** 480 listings (82 earphones, 100 smartphones, 98 laptops, 100 running shoes, 100 smartwatches) captured on 8 October 2026 with a third-party scraping service. Flipkart's terms do not allow republishing listings, so the files live in `backend/data_private/` and are git-ignored. Every answer states the capture date.
- **SerpAPI (optional fallback).** Adds Google Shopping results when too few products remain. Off unless switched on; results are link-only and cannot be put into a mandate because the server cannot re-check their price.
- **FakeStoreAPI (toy catalog).** The original Phase 1 source, used only if the snapshot is missing or `DATA_SOURCE=fakestore`.

All sources pass through a client and a normalizer into one shared `Product` shape, so ranking and the frontend never know where a product came from.

### 3.6 Typed spec facts and requirement matching
Listing specifications are extracted into typed facts (for example RAM 8 GB, noise cancellation yes). A fact exists only if the listing states it clearly; a contradictory listing yields no fact (it is recorded as a conflict) and silence means "unknown". Each requirement is matched into one of five outcomes:

| Outcome | Meaning | Effect |
|---|---|---|
| met | The listing says it does | Counts toward ranking |
| not met | The listing clearly says it does not | Product is removed |
| unknown | The listing is silent | Product stays, flagged "couldn't confirm" |
| conflict | The listing contradicts itself | Product stays, flagged |
| unsupported | The system has no rule for this requirement | Product stays, flagged |

Only "not met" removes a product, so missing information is never treated as failure. Ranking: score = 2 × Bayesian-weighted rating + 1 per confirmed requirement − scaled price; variants of one model (colour, storage) are grouped so the top three are three different models.

### 3.7 Replanning
When no product meets everything, `app/agent/replan.py` builds every single change that would bring real products back: raise the budget to the cheapest price at which every requirement is met (offered only if within 50% of the shopper's budget), or keep the budget and drop one requirement. **A brand the shopper named is never dropped, and the category never changes.** The model picks one option; code checks the pick and falls back to a fixed rule (a small raise of up to 20% first, otherwise the drop that brings back the most products) if the reply is unusable. The answer tells the shopper exactly what was given up, and "within budget" claims are still checked against the budget the shopper originally gave.

### 3.8 Grounding and verification
1. **Trace:** every thought, action and observation is recorded and shown.
2. **Claims with sources:** the explanation is structured claims (field, value, sentence, source tool call). A claim without a valid source is dropped.
3. **Deterministic verifier:** checks the field, tool-call ID, provenance, value, yes/no wording (negation) and the numbers inside the sentence against the real product. One rewrite, then drop; if the model's output is unusable the answer falls back to data only.

The verifier is plain Python, so it is testable: a fault-injection test corrupts claims in 16 known ways and measures how many are caught.

### 3.9 Mock cart mandate (modelled on the AP2 pattern)
The server drafts the mandate with its own price (the browser's price is ignored), quantity up to 5, and a 15-minute lifetime. Approval needs explicit consent and re-checks the price. The approved cart is signed with HMAC-SHA256 over its canonical fields; checkout re-verifies state, expiry, signature and price. Every step is written to an audit log (Postgres through SQLAlchemy, with a local-file fallback). No payment processor exists or is planned.

### 3.10 Database: Supabase (Postgres)
Holds the mandate audit log and serves the database health check. Standard Postgres, so nothing depends on Supabase specifically. A vector database was left out because ranking works on structured attributes and there is no similarity-search requirement.

---

## 4. Why this supports an agentic claim

- **Planning and decisions:** the planner interprets the request, decides when to ask a question, and the replanner chooses which constraint to loosen.
- **Tool use:** search, requirement checking and ranking are logged tool calls with IDs.
- **Reasoning:** the trace is a user-visible product feature, not a debug log.
- **Feedback-driven execution:** the verifier rejects claims and triggers a rewrite; the replanner reacts to a failed search by changing the plan and searching again.
- **Acting safely:** purchase intent needs a signed, consented, re-checked mandate.

Not built: memory across turns and multiple cooperating agents (section 9).

---

## 5. Evaluation (what is measured)

- **Offline (no key, no tokens):** snapshot coverage; extraction vs listing titles; retrieval and ranking on 66 queries using the gold intent; verifier fault injection; replanning rescue rate on the queries that return nothing.
- **Live (Groq):** planner accuracy against gold intents, first-draft claim failures, rewrites, drops, fallbacks, latency; the replanning and clarifying-question stress set; an LLM-only baseline with no tools or data.

Aggregate results are in `backend/evaluation/results/`.

---

## 6. Deliberately out of scope
- Real payments or live checkout.
- Scraping at demo time (the data is a saved snapshot).
- A vector database or semantic search.
- Server-side rendering.

## 7. Known limits
- One snapshot, one retailer, about 100 listings per category, captured during a sale; the data is private.
- Requirement rules are English-only patterns for five categories.
- The mandate is a mock for one server: no accounts, real payments or key management.

## 8. Phase map

| Phase | Piece | Status |
|---|---|---|
| 0 | Scaffolding (frontend, backend, database) | Done |
| 1 | Product schema and FakeStoreAPI normalizer | Done |
| 2–3 | Groq planning and the LangGraph agent | Done |
| 4 | Real data: Flipkart snapshot, typed facts, requirement matching, ranking, SerpAPI fallback | Done |
| 5 | Grounding and verifier | Done |
| 6 | Session memory | Not built |
| 7 | Mock cart mandate (server and approval screen) | Done |
| 8 | Streaming and frontend polish | Not built |
| 9 | Multi-agent critic | Not built (stretch) |
| Extra | Replanning, clarifying questions, evaluation set and scripts | Done |

## 9. Not built yet
Session memory across turns (Phase 6), streaming (Phase 8), multi-agent critic (Phase 9), and a licensed live product feed.