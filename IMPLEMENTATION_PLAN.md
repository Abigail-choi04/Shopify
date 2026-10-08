# ShopMate AI — Detailed Implementation Plan

This is the complete, phase-by-phase build plan: what gets built, with
which exact tools, in what order, how to verify each phase works, and
what's still a decision point. Read alongside `ARCHITECTURE.md` (the
*why*) and `docs/architecture-diagram.png` (the visual).

**Status as of this document**: Phase 0 and Phase 1 are built and
tested (backend scaffold + FakeStoreAPI integration). A frontend-only
hardcoded demo (visually representing Phases 2 → 8's eventual output)
has also been built ahead of schedule, to have something to show
before the real pipeline exists — this is explicitly a prototype, not
a phase in its own right, and gets replaced piece by piece as Phases
2–8 are implemented for real.

---

## 1. Full Tech Stack (reference table)

| Layer | Technology | Version (pin) | Role |
|---|---|---|---|
| Frontend framework | React | 19.x (via Vite template) | UI components |
| Frontend build tool | Vite | 8.x | Dev server, bundling |
| Backend framework | FastAPI | 0.115.0 | REST API, orchestrator |
| ASGI server | Uvicorn | 0.30.6 | Runs the FastAPI app |
| Data validation | Pydantic | (bundled with FastAPI) | Schema enforcement (`Product`, later `Intent`) |
| HTTP client (server-side) | httpx | 0.27.2 | Async calls to FakeStoreAPI/RapidAPI/MYSTORE |
| Database | Supabase (hosted Postgres) | Postgres 15/16 | Session memory (Phase 6) |
| DB driver | psycopg2-binary | 2.9.9 | Python ↔ Postgres |
| ORM / SQL toolkit | SQLAlchemy | 2.0.35 | Query building, connection pooling |
| LLM provider | Groq | `openai/gpt-oss-120b` model | Intent parsing (P2), agent tool-calling (P3+) |
| LLM SDK | `openai` Python package (pointed at Groq's base URL) | latest | Because Groq exposes an OpenAI-compatible endpoint |
| Agent orchestration | LangGraph | latest stable | Planner → Search → Rank → Verify → Response graph |
| Agent framework base | LangChain (core) | latest stable | LangGraph depends on LangChain's tool/message abstractions |
| Product data (fallback) | FakeStoreAPI | n/a (public REST API) | Always-on, zero-key demo backbone |
| Product data (real, P4) | RapidAPI "Real-Time Product Search" | n/a | Cross-retailer aggregation (Amazon/Walmart/eBay/Best Buy/Target) |
| Product data (real, P4) | MYSTORE API | n/a | Flipkart-sourced, India-relevant |
| Search fallback | SerpAPI | n/a | Search-grounding fallback, 250 free searches/month |
| Env management | python-dotenv | 1.0.1 | Loads `.env` into `os.environ` |
| Package manager (Python) | pip + venv | n/a | Per user preference |
| Package manager (JS) | npm | bundled with Node 18+ | Frontend deps |
| Version control | Git | n/a | (not yet initialized — see §8) |

---

## 2. Prerequisites & Accounts Needed

Before starting Phase 2 onward, these accounts/keys are required:

1. **Groq account** — https://console.groq.com → API Keys → create one.
   Free tier is generous; no credit card required as of this writing.
2. **Supabase account** — already set up (see README.md in the repo).
3. **RapidAPI account** (Phase 4 only) — sign up at rapidapi.com,
   subscribe to "Real-Time Product Search" on the free tier (100
   req/month).
4. **MYSTORE API key** (Phase 4 only) — check current signup process
   at time of implementation; free tier availability should be
   re-verified since third-party free tiers change.
5. **SerpAPI account** (optional, fallback) — serpapi.com free tier.

None of these are needed for Phases 0, 1, or the current hardcoded
demo.

---

## 3. Phase 0 — Scaffolding ✅ Done

**Goal**: prove frontend, backend, and database can all talk to each
other, with zero agent logic.

**Tools used**: FastAPI, Uvicorn, React+Vite, Supabase, SQLAlchemy.

**What was built**:
- `backend/app/main.py` — FastAPI app with `/health` and `/health/db`
  endpoints.
- `frontend/src/App.jsx` — fetches both endpoints on load, displays
  status.
- `docker-compose.yml` was initially used for local Postgres, then
  **removed** in favor of Supabase per your decision to avoid local
  Docker.

**Verification performed**: opened `localhost:5173`, confirmed both
statuses showed "ok".

---

## 4. Phase 1 — Data Layer (fallback-first) ✅ Done

**Goal**: integrate FakeStoreAPI as the always-on product backbone,
normalized into a category-agnostic schema.

**Tools used**: httpx (async HTTP), Pydantic (schema).

**What was built**:
- `backend/app/schemas/product.py` — the shared `Product` model every
  source gets converted into.
- `backend/app/services/fakestore_client.py` — raw HTTP calls to
  FakeStoreAPI, no transformation.
- `backend/app/normalizers/fakestore.py` — converts FakeStoreAPI's raw
  JSON into `Product`.
- `backend/app/routers/products.py` — exposes `/products`,
  `/products/{id}`, `/products/categories`, with a 5-minute in-memory
  cache.

**Verification performed**: `localhost:5173` showed "ok (20 products
loaded)" with a rendered grid of sample products.

**Design decision recorded**: client (raw HTTP) and normalizer
(shape conversion) are kept in separate files per source, so Phase 4
adds new files without touching Phase 1's code.

---

## 5. Frontend Demo Prototype (built ahead of schedule)

**Goal**: something demoable before the real agent pipeline exists —
a scripted walk-through of the intended user experience, useful for
early feedback and as a visual reference while building the real
thing.

**Tools used**: React state (`useState`/`useRef`), no backend calls,
no LLM calls — entirely client-side and hardcoded.

**What was built**:
- `frontend/src/data/scenarios.js` — 6 hardcoded scenarios
  (headphones, running shoes, laptops, backpacks, smartwatches,
  mixer-grinders) plus a generic fallback, each shaped exactly like
  what Phases 2–5 will eventually produce for real (parsed intent,
  ReAct trace with `source_tool_call_id`, ranked products with
  category-specific comparison attributes).
- `frontend/src/components/ReasoningTrace.jsx` — renders the
  Thought/Action/Observation trace, revealed step by step.
- `frontend/src/components/ProductRecommendations.jsx` — ranked cards
  + comparison table.
- `frontend/src/components/CartMandateModal.jsx` — the mock AP2-style
  mandate JSON + explicit consent checkbox.
- `frontend/src/App.jsx` — orchestrates: idle → thinking (trace
  reveals) → results → mandate → confirmed.
- Warehouse-themed visual design (`App.css`) — kraft/cardboard
  palette, stencil typography (Oswald), hazard-stripe header, shelf-tag
  product cards, inventory-manifest comparison table, shipping-manifest
  mandate modal.

**Important for the defense**: this prototype makes **zero** network
or LLM calls. Every "reasoning step" and "recommendation" is a
JavaScript object in `scenarios.js`, matched to the query by keyword.
It exists to validate the UX and interaction design before investing
in the real backend logic — a legitimate, common practice (UI-first
prototyping), but must be presented as exactly that, not as the
working system, if asked directly.

---

## 6. Phase 2 — Basic LLM Wiring (next phase to build)

**Goal**: replace the keyword-matching in `scenarios.js` with a real,
single-shot Groq call that parses a natural-language query into
structured intent. No planning, no tools, no agent loop yet.

**Tools**: `openai` Python SDK (pointed at Groq's base URL), Pydantic
for the output schema, FastAPI endpoint to expose it.

**Step-by-step**:

1. **Install the SDK**:
   ```bash
   cd backend
   pip install openai
   ```
   Add `openai==1.51.0` (or current stable) to `requirements.txt`.

2. **Add the Groq API key** to `backend/.env`:
   ```
   GROQ_API_KEY=gsk_...
   ```
   (already a placeholder in `.env.example` from Phase 0)

3. **Create `backend/app/schemas/intent.py`** — the structured output
   shape:
   ```python
   class ParsedIntent(BaseModel):
       category: str
       max_price: float | None
       must_have_attributes: list[str]
       raw_query: str
   ```

4. **Create `backend/app/services/groq_client.py`** — wraps the Groq
   call. Uses the `openai` SDK with `base_url="https://api.groq.com/openai/v1"`
   and `model="openai/gpt-oss-120b"`. Sends a system prompt instructing
   the model to return JSON matching `ParsedIntent`, using either
   function-calling/tool-schema enforcement or JSON mode (whichever
   Groq's current API supports best for this model — verify against
   Groq's docs at implementation time, since structured-output support
   evolves).

5. **Create `backend/app/routers/intent.py`** — a `POST /parse-intent`
   endpoint that takes `{"query": "..."}` and returns a `ParsedIntent`.

6. **Register the router** in `main.py`.

**Testing this phase**:
- Direct test via FastAPI's auto-generated docs at
  `http://localhost:8000/docs` — call `/parse-intent` with a few
  sample queries ("noise-cancelling headphones under 8000",
  "cheap running shoes") and manually verify the JSON output is
  sensible.
- Write 5–10 example queries covering edge cases: no price mentioned,
  multiple constraints, ambiguous category, non-English brand names —
  and log actual vs. expected parses in a simple text file
  (`backend/tests/manual_intent_samples.md`) for later regression
  checking.
- No frontend changes required yet — this phase is backend-only and
  tested via `/docs` or `curl`.

**Open decision for this phase**: whether to enforce structured output
via Groq's JSON mode, a function-calling schema, or manual
prompt-and-parse-with-retry. This should be decided once the current
Groq API capabilities for `openai/gpt-oss-120b` are confirmed
(function-calling reliability varies by model even when
OpenAI-compatible).

---

## 7. Phase 3 — Agent Orchestration (LangGraph)

**Goal**: the actual agent. A graph with explicit nodes: Planner →
Search/tool-use → Comparison/Ranking → Response. (Verifier node is
Phase 5, added once this skeleton works.)

**Tools**: LangGraph, LangChain core (for tool/message types).

**Step-by-step**:

1. **Install**:
   ```bash
   pip install langgraph langchain-core
   ```

2. **Define tools** (`backend/app/agent/tools.py`) — wrap the existing
   `/products` logic as LangGraph-callable tools:
   - `search_products(category, max_price)` → calls the Phase 1
     product router logic directly (in-process, not over HTTP, since
     it's the same backend).
   - `rank_by_attributes(products, attributes)` → scoring logic that
     takes the category-specific attribute list (this is where
     category-adaptive ranking logic lives — see below).

3. **Category-adaptive ranking logic** (`backend/app/agent/ranking.py`):
   a lookup table or LLM-driven step that maps a detected category to
   its relevant ranking attributes (e.g. electronics/headphones →
   `["anc", "battery_life", "rating"]`; footwear → `["cushioning",
   "breathability", "rating"]`). Early implementation: a hardcoded
   dict keyed by category, mirroring exactly what `scenarios.js`
   already hardcodes in the frontend prototype — this is the real
   version of that demo logic. Stretch goal (Phase 9): have the LLM
   infer relevant attributes per category dynamically instead of a
   fixed lookup table.

4. **Define the graph** (`backend/app/agent/graph.py`):
   ```python
   from langgraph.graph import StateGraph

   graph = StateGraph(AgentState)
   graph.add_node("planner", planner_node)
   graph.add_node("search", search_node)
   graph.add_node("rank", rank_node)
   graph.add_node("respond", respond_node)
   graph.add_edge("planner", "search")
   graph.add_edge("search", "rank")
   graph.add_edge("rank", "respond")
   graph.set_entry_point("planner")
   ```
   Each node's function calls Groq (via the Phase 2 client) with a
   node-specific prompt, and each node's output is logged as a trace
   step (Thought/Action/Observation) — this log is what the frontend
   will render, replacing the hardcoded `scenarios.js` trace.

5. **Expose via API** — replace `/parse-intent` with `/chat`
   (`POST {"query": "..."}`), returning the full trace + ranked
   products in one response (streaming can be added in Phase 8).

**Testing this phase**:
- Run the same manual query set from Phase 2 through the new `/chat`
  endpoint via `/docs` or `curl`, and manually verify: (a) the trace
  has sensible Thought/Action/Observation steps, (b) the returned
  products are actually filtered/ranked correctly, (c) different
  categories produce different ranking attributes (the core
  category-adaptive claim).
- This is also the point to start writing an actual eval set: a CSV
  or JSON file of (query, expected category, expected top pick) for
  the categories being tested, so later phases can be regression-
  tested rather than eyeballed.

---

## 8. Phase 4 — Real Data Sources

**Goal**: layer RapidAPI/MYSTORE on top of the FakeStoreAPI fallback,
with graceful degradation.

**Tools**: httpx, the same client/normalizer pattern from Phase 1.

**Step-by-step**:

1. Create `backend/app/services/rapidapi_client.py` and
   `backend/app/normalizers/rapidapi.py`, following the exact pattern
   `fakestore_client.py`/`fakestore.py` already established.
2. Same for MYSTORE if pursued.
3. In `backend/app/agent/tools.py`'s `search_products`, implement the
   fallback chain: try the real source first; on non-2xx response,
   timeout, or 429 (quota exceeded), catch the exception and fall back
   to `fakestore_client`, **and add an explicit trace entry** noting
   the fallback occurred (e.g. `{"type": "observation", "text": "Real
   product source unavailable — using demo catalog instead."}`) — this
   is the "never a silent failure" requirement from the architecture
   doc.
4. Add a feature flag (`USE_REAL_PRODUCT_APIS=true/false` in `.env`)
   so real APIs are opt-in — keeps day-to-day development from burning
   the RapidAPI free-tier quota (100 req/month is easy to exhaust
   while iterating).

**Testing this phase**:
- With the flag off: confirm nothing changes from Phase 3's behavior.
- With the flag on: run 2–3 queries, confirm real product data comes
  back and looks plausible (real brand names, real-ish prices).
- Deliberately break the API key (wrong value) to confirm the fallback
  path triggers and is disclosed in the trace, not silently swallowed.

---

## 9. Phase 5 — Transparent Reasoning

**Goal**: implement the grounding + verifier mechanisms described in
the project doc, not just display a trace (which the frontend
prototype already does cosmetically).

**Tools**: a second, cheap Groq call for the verifier; structured
output validation (Pydantic) to enforce `source_tool_call_id`
presence.

**Step-by-step**:

1. Every tool call in the LangGraph nodes gets a unique ID
   (`call_001`, `call_002`, ...; a UUID in the real system, kept short
   for the trace UI).
2. The `respond` node's output schema requires each claim (e.g. each
   product's price/spec mentioned) to carry the `source_tool_call_id`
   it came from. Pydantic validation rejects/drops any claim missing
   this field before it's returned to the frontend.
3. Add a `verify` node between `rank` and `respond`: a second Groq
   call (or simpler rule-based check, e.g. "does this claimed price
   match the raw tool output?") that compares the draft answer against
   the raw tool outputs stored in state, flags mismatches, and either
   corrects or drops the unverifiable claim.

**Testing this phase**:
- Deliberately construct a case where the model might hallucinate
  (e.g. ask about a spec the product data doesn't actually have) and
  confirm the verifier catches and drops it rather than passing it
  through.
- Confirm every product/claim in a normal response has a valid
  `source_tool_call_id` that traces back to an actual logged tool call.

---

## 10. Phase 6 — Session Memory (V2)

**Goal**: persist budget/preferences/rejected items across turns in
Supabase.

**Tools**: SQLAlchemy, Supabase (already connected since Phase 0).

**Step-by-step**:

1. Define a `Session` table (SQLAlchemy model) — `session_id`,
   `budget`, `preferences` (JSON column), `rejected_product_ids`
   (JSON array column), `updated_at`.
2. Add a lightweight session-ID mechanism (e.g. a cookie or a token
   the frontend keeps in memory for the demo — full auth is out of
   scope).
3. Before the planner node runs, load the session's stored context
   and inject it into the prompt ("user previously rejected X for
   being too heavy; budget is capped at ₹8,000 based on earlier
   turns").
4. After a turn, update the stored session with any new
   preferences/rejections the user expressed.

**Testing this phase**:
- Multi-turn manual test: state a preference in turn 1 ("I don't like
  over-ear headphones"), confirm turn 2's recommendations reflect it
  without the user repeating themselves.
- Restart the backend mid-session and confirm state persisted (proves
  it's actually in Supabase, not just in-memory).

---

## 11. Phase 7 — Mock Cart Mandate

**Goal**: wire the real backend to the mandate flow the frontend
prototype already visualizes.

**Tools**: none new — this is mostly backend endpoint + frontend wiring.

**Step-by-step**:

1. `POST /cart/mandate` — takes a product ID, returns a signed-looking
   JSON mandate object (same shape as the frontend prototype already
   builds client-side: item, price, quantity, timestamp, consent
   placeholder).
2. `POST /cart/confirm` — takes the mandate + explicit consent flag,
   "finalizes" the mock order (writes an `orders` row to Supabase for
   demo purposes — no real payment).
3. Replace the frontend's client-side mandate JSON construction
   (currently in `CartMandateModal.jsx`) with a call to
   `/cart/mandate`, so the object is agent-generated, not
   hardcoded — this is the one piece of the current UI that must
   change from "simulated" to "real" without changing its visual
   design at all.

**Testing this phase**: confirm the mandate object returned by the
real endpoint matches the shape the UI already expects (no frontend
changes needed beyond swapping the data source), and confirm an
order row appears in Supabase after confirmation.

---

## 12. Phase 8 — Frontend Polish

**Goal**: streaming responses, expandable reasoning trace, demo
rehearsal on the 2–3 chosen categories.

**Tools**: Server-Sent Events (SSE) or WebSocket for streaming (SSE is
simpler and sufficient here since it's one-directional
server→client).

**Step-by-step**:
1. Convert `/chat` to a streaming endpoint (`StreamingResponse` in
   FastAPI) that emits each trace step as it's produced by the graph,
   rather than waiting for the full run to complete.
2. Update the frontend to consume the stream (replace the
   `setTimeout`-based fake reveal in the current prototype's
   `App.jsx` with real incremental rendering as chunks arrive) —
   note this is a very small change since the UI already renders
   trace steps incrementally by design.
3. Rehearse the live demo specifically on the categories with the
   most reliable real data (Phase 4's real-source categories that
   were verified to return good results), falling back to the demo
   catalog for anything else.

**Testing this phase**: full end-to-end run of each rehearsed demo
query, timed, to confirm total latency is acceptable for a live
audience (a few seconds per step, not tens of seconds).

---

## 13. Phase 9 (Stretch) — Multi-Agent Critic

**Goal**: a genuinely separate critic agent (different prompt, and
ideally evaluated against the primary chain rather than sharing its
context), reviewing the primary recommendation before it's shown.

**Only pursue this if Phases 0–8 are solid and there's time left** —
it's explicitly marked stretch/nice-to-have in the original project
scope, and a shaky Phase 9 is worse for the paper than a polished
Phase 0–8.

---

## 14. Testing Philosophy Throughout

- Every phase above lists a **manual verification step** — do this
  before moving to the next phase, not at the end.
- From Phase 3 onward, start keeping a running eval set (query →
  expected category → expected top pick) — this becomes the "task
  success rate" metric the project doc's Judge Q&A prep already
  anticipates being asked about.
- Any time a real external API is involved (Groq, RapidAPI, MYSTORE),
  test the failure path deliberately (wrong key, simulated timeout),
  not just the happy path — this is what "what if a tool call fails?"
  in the Q&A prep is actually asking about, and it needs a real answer
  by demo day, not a hypothetical one.

---

## 15. What Still Needs a Decision

These are flagged rather than assumed, per your instruction to ask
rather than guess:

1. **Structured-output enforcement mechanism for Groq** (Phase 2) —
   JSON mode vs. function-calling vs. manual parsing. Needs checking
   against Groq's current documented support for `openai/gpt-oss-120b`
   at implementation time.
2. **Category-attribute mapping approach** (Phase 3) — a hardcoded
   lookup table (fast, reliable, limited to known categories) vs.
   LLM-inferred attributes per category (more general, less
   predictable, harder to demo reliably). Recommend starting hardcoded
   (matches the current demo prototype) and only moving to LLM-inferred
   if time allows (natural fit for Phase 9 stretch).
3. **Session identification mechanism** (Phase 6) — cookie-based,
   token-based, or single-session-only for the demo. For a hackathon
   demo with one user at a time, a single fixed session ID is probably
   sufficient and avoids building auth.
4. **MYSTORE's current API availability/signup process** (Phase 4) —
   should be re-verified when this phase starts, since third-party
   free-tier APIs change without notice.
