# ShopMate AI — Architecture & Tech Choices

This document explains what's actually being built, how the pieces fit
together, and why each technology was picked over its alternatives.
It's written to double as material for your conference paper's
system-design section.

---

## 1. System Overview

ShopMate AI is an agentic shopping assistant. The user states a need
in natural language ("noise-cancelling headphones under ₹8,000"); the
system plans, searches across product data, compares options against
category-specific attributes, and returns ranked, justified
recommendations with a visible reasoning trace. A mocked "Cart
Mandate" step captures purchase intent without any real payment
processing.

The defining research question isn't "can an LLM recommend a
product" — it's **whether an agent can reliably plan, use tools, stay
grounded in real data (not hallucinate specs/prices), and adapt its
reasoning to categories it wasn't specifically programmed for.**
That's the agentic contribution: multi-step planning + tool use +
grounding + transparent reasoning, not a single prompt-to-answer call.

```
┌─────────────┐      ┌──────────────┐      ┌───────────────────┐
│   Frontend   │◄────►│   Backend    │◄────►│   Agent Layer      │
│ React+Vite   │ HTTP │  FastAPI     │      │  LangGraph         │
│ (chat UI,    │      │ (orchestrator,│      │  Planner→Search→   │
│  trace view, │      │  API routes) │      │  Rank→Verify→      │
│  cart modal) │      │              │      │  Respond            │
└─────────────┘      └──────┬───────┘      └─────────┬──────────┘
                             │                         │
                    ┌────────▼────────┐      ┌─────────▼──────────┐
                    │   Supabase       │      │   Product Sources  │
                    │  (Postgres) —    │      │  FakeStoreAPI       │
                    │  session memory, │      │  (fallback, Phase1) │
                    │  V2 preferences  │      │  RapidAPI / MYSTORE │
                    └──────────────────┘      │  (real data, Phase4)│
                                               └────────────────────┘
```

---

## 2. Layer-by-Layer Breakdown

### 2.1 Frontend — React + Vite

**What it does**: chat-style input, renders the reasoning trace as it
streams in, shows ranked product cards + a comparison table, and the
mock Cart Mandate confirmation modal.

**Why React + Vite over Next.js**: Next.js's main advantages are
server-side rendering (SSR) and a built-in API layer — neither is
needed here since FastAPI already serves as the backend and there's
no SEO requirement (this isn't a public marketing site). Vite gives a
faster local dev loop (near-instant hot reload) and a simpler mental
model for a single-page chat interface. Next.js remains a reasonable
alternative if one-click hosting (Vercel) becomes a priority later.

### 2.2 Backend — FastAPI

**What it does**: the orchestrator. Exposes REST endpoints, owns the
product-normalization layer, and (from Phase 3 onward) hosts the
LangGraph agent that the frontend talks to.

**Why FastAPI over Flask/Django/Express**:
- Native `async`/`await` — matters here because most of the work
  (calling Groq, calling product APIs) is I/O-bound, and FastAPI's
  async support lets the server handle multiple concurrent tool calls
  efficiently.
- Automatic request/response validation and OpenAPI docs via Pydantic
  — every API contract (`Product`, later `Intent`, `Recommendation`)
  is declared once and validated automatically, which reduces silent
  data-shape bugs and gives free interactive API docs at `/docs`.
- Lighter-weight than Django (no ORM/admin/templating baggage this
  project doesn't need) and better suited to an API-only backend than
  Express (Python keeps one language across backend + agent layer +
  data processing, avoiding a JS/Python split).

### 2.3 Data Layer — Product Schema & Normalizers

**What it does**: every product, regardless of source, is converted
into one shared `Product` shape (`id`, `source`, `title`, `category`,
`price`, `rating`, `raw`, etc.) before anything downstream touches it.

**Why this matters architecturally**: this is what makes the
category-adaptive ranking agent (Phase 3) source-agnostic. The
ranking logic never needs to know whether a product came from
FakeStoreAPI or RapidAPI — it only ever sees a `Product`. Adding a
new data source later means writing one new client file + one new
normalizer file, with zero changes to ranking, search, or the
frontend. This pattern (client → normalizer → shared schema) is the
same one production aggregators use internally, so it's also a
legitimate design decision to defend to reviewers, not just
convenient plumbing.

The `raw` field on every normalized product is kept for traceability
— Phase 5's grounding mechanism needs to point back to real source
data for any claim the agent makes.

### 2.4 Database — Supabase (hosted Postgres)

**What it stores**: session memory for V2 (budget, preferences,
rejected items across turns — Phase 6), and later a product cache if
API rate limits demand it.

**Why Supabase over local Postgres/Docker**: no local database
install or container runtime needed — one less thing to break across
different machines (this project has already been moved between two
laptops). Supabase is standard Postgres underneath, so nothing about
the schema, queries, or SQLAlchemy usage changes versus a local
instance — it's a deployment choice, not an architectural one. The
free tier is sufficient for a hackathon/class project's session-scale
data.

**Why Postgres over a vector database for this use case**: the
project doc lists a vector store as optional, and it's being skipped
entirely. Category-adaptive ranking works on structured attributes
(price, rating, category-specific specs) that a normal SQL/relational
model captures cleanly — there's no semantic-similarity search
requirement (e.g. "find me something like this but cheaper" via
embeddings) in the current scope. Adding a vector store would be
solving a problem this project doesn't have yet.

### 2.5 LLM Provider — Groq

**What it does**: powers intent parsing (Phase 2) and the agent's
tool-calling decisions (Phase 3+).

**Why Groq over alternatives**:
| Provider | Strength | Trade-off |
|---|---|---|
| **Groq** (chosen) | Very low inference latency (LPU hardware), generous free tier, OpenAI-compatible API (easy to swap later) | Smaller model catalog than OpenAI/Anthropic directly |
| Cerebras | Even faster raw throughput | Thinner ecosystem/tooling, less mature function-calling support at eval time |
| Fireworks AI | Strong structured-output/function-calling serving | Less aggressive free tier for a student project |

Groq's speed matters specifically because a multi-step agent (planner
→ search → rank → verify → respond) makes several sequential LLM
calls per user query — latency compounds across steps in a way it
doesn't in a single-shot chatbot, so inference speed is a first-order
UX concern here, not a nice-to-have. Using an OpenAI-compatible
interface means swapping providers later (if Groq's free tier becomes
a constraint) is a config change, not a rewrite.

### 2.6 Agent Orchestration — LangGraph (Phase 3+)

**What it does**: implements the actual agentic loop as an explicit
graph: Planner node → Search/tool-use node → Comparison/ranking node
→ Verifier/critic node → Response node.

**Why LangGraph over a hand-rolled loop**: a hand-rolled `while` loop
calling the LLM repeatedly would work for a graph this small, and has
less dependency overhead. LangGraph is chosen instead because (a) it
gives explicit, inspectable state at each node — which directly
produces the reasoning-trace UI requirement — rather than needing to
build that instrumentation by hand, and (b) it's a recognized
"real" agent framework, which matters for a project whose grading
criteria explicitly ask for demonstrated agentic concepts (planning,
tool use, feedback-driven execution) — using established
infrastructure is easier to defend in a paper/demo than a bespoke
loop that does the same thing less legibly.

### 2.7 Product Data Sources

| Source | Role | Why |
|---|---|---|
| **FakeStoreAPI** (Phase 1) | Always-on fallback / demo backbone | Zero API key, zero quota, zero cost — guarantees the demo never breaks on stage regardless of what happens to third-party quotas |
| **RapidAPI Real-Time Product Search** (Phase 4) | Real cross-retailer data (Amazon/Walmart/eBay/Best Buy/Target via Google Shopping aggregation) | Free tier capped at 100 req/month — treated as a demo-day-only, flag-gated source, not used during normal development |
| **MYSTORE API** (Phase 4) | India-relevant retail data (Flipkart-sourced) | Free, regionally relevant given the project's ₹-denominated use cases |
| **SerpAPI** (fallback) | Search-grounding fallback | 250 searches/month free tier, backup if the above sources fail |

The tiered design — FakeStoreAPI always on, real sources layered on
top with graceful degradation — means a quota exhaustion or an
outage during a live demo degrades to "still works, just simulated
data" rather than a visible failure.

### 2.8 Transparent Reasoning (Phase 5)

Three mechanisms work together to prevent hallucinated
recommendations, directly addressing the "how do you stop it from
making things up" question a reviewer will ask:

1. **ReAct-style trace logging** — every `Thought → Action(tool_call)
   → Observation` step is logged, not just the final answer, and
   rendered as an expandable trace in the UI (this is what the demo
   prototype's `ReasoningTrace` component already simulates with
   hardcoded data).
2. **Grounding via `source_tool_call_id`** — the agent's final answer
   is structured JSON where every factual claim (a price, a spec, a
   rating) must carry the ID of the tool call that produced it.
   Claims without one are dropped before rendering, rather than shown
   with a caveat — the enforcement is structural, not a disclaimer.
3. **Verifier/critic pass** — a second, cheaper LLM call (or
   rule-based check) compares the draft answer against raw tool
   outputs before it reaches the user, flagging unverifiable claims
   instead of guessing at them.

### 2.9 Mock Cart Mandate (Phase 7)

No real payment processing exists or is planned — this is explicitly
out of scope. Instead, the agent generates a JSON object modeled on
the real-world **AP2** (Agent Payments Protocol) mandate pattern:
item, price, quantity, timestamp, and explicit user consent, and the
mock "purchase" only proceeds after the user checks a consent box
approving that exact object. This is deliberately close to how
production agentic-commerce protocols work (AP2 for payment
authorization, ACP for the agent-merchant checkout handshake, UCP for
catalog/product discovery) without wiring into a real payment
processor — the point for the paper is demonstrating the *pattern* of
human-in-the-loop authorization before an agent takes an
irreversible action, which is a core safety property of agentic
commerce systems generally, not specific to shopping.

---

## 3. Why This Architecture Supports an Agentic (not just LLM-wrapped) Claim

The class project's core requirement is justifying agentic behavior
over "an LLM feature bolted onto an app." The architecture supports
that claim concretely:

- **Autonomous decision-making**: the planner node decides *which*
  tools to call and in what order based on the parsed query — this
  isn't a fixed pipeline; a footwear query and an electronics query
  trigger different ranking attributes without hand-written branching
  per category.
- **Tool usage**: product search, spec normalization, and ranking are
  all exposed as callable tools the agent invokes, not inline
  function calls the developer sequenced.
- **Reasoning**: the ReAct trace is a first-class, user-visible
  artifact of the system, not a debug log.
- **Feedback-driven execution**: the verifier/critic node checks the
  planner's draft output against ground truth and can reject/flag
  claims — a feedback loop within a single query, and (in Phase 6)
  across queries via session memory.
- **Multi-agent collaboration** (stretch, Phase 9): a second critic
  agent independent from the primary reasoning chain, evaluating its
  output.

---

## 4. What's Deliberately Out of Scope

- Real payment processing or live checkout automation.
- Scraping arbitrary e-commerce sites at demo time (data sources are
  all API/package-based, never ad hoc scraping — avoids fragility on
  stage).
- A vector database / semantic search (no current requirement for
  similarity-based product matching; would add complexity without a
  corresponding capability need).
- SSR/Next.js (no public-facing SEO surface to justify it).

---

## 5. Phase-to-Architecture Map

For reference, here's which architectural piece each phase builds:

| Phase | Architecture piece |
|---|---|
| 0 | Frontend/backend/DB scaffolding, no logic |
| 1 | Product schema + FakeStoreAPI normalizer (§2.3, §2.7) |
| 2 | Groq intent parsing (§2.5) |
| 3 | LangGraph agent loop (§2.6) |
| 4 | Real data sources layered on fallback (§2.7) |
| 5 | Transparent reasoning / grounding (§2.8) |
| 6 | Supabase-backed session memory (§2.4) |
| 7 | Mock Cart Mandate (§2.9) |
| 8 | Frontend polish, demo rehearsal |
| 9 | Multi-agent critic (stretch) |
