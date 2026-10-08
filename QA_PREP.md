# ShopMate AI — Judge / Reviewer Q&A Prep

Organized by theme. Each answer is written the way you'd actually say
it out loud — short first, detail if pushed further. The last section
covers the questions specific to presenting a hardcoded demo honestly,
which matters more than any technical answer if it comes up.

---

## A. "Why is this agentic and not just an LLM feature?"

**Q: What makes this different from a chatbot with a shopping prompt?**
A single-shot chatbot takes a query and returns an answer from one
model call. ShopMate AI plans (decides what to search for and in what
order), calls tools to get real data rather than generating an answer
from parametric memory, adapts its reasoning process per category
without being told which category in advance, and runs a
feedback/verification step on its own draft before responding. Those
four things — planning, tool use, adaptive reasoning, feedback loops —
are the standard definition of "agentic" versus "prompted," and the
architecture has an explicit graph node for each one (see the
architecture diagram).

**Q: Isn't "search then rank" just a fixed pipeline, not real
autonomy?**
The pipeline's *shape* (planner → search → rank → respond) is fixed,
but its *content* is not: the planner decides which category the
query falls into and which attributes matter for ranking without a
hardcoded if/else per category — a footwear query and an electronics
query produce different ranking logic from the same code path. That's
the autonomy claim: decision-making within the pipeline, not a
scripted sequence with the same steps regardless of input. This is a
fair distinction to push on, and the honest framing is: this is a
constrained/structured agent (a common, defensible design pattern),
not an open-ended autonomous agent — the graph structure exists
specifically so the trace is inspectable and the demo is reliable,
which is the trade-off being made deliberately.

**Q: What's the multi-agent story?**
Multi-agent collaboration is the Phase 9 stretch goal: a critic agent
independent from the primary reasoning chain reviews the recommendation
before it's shown. In the core system (Phases 0–8), the "agentic"
claim rests on planning + tool use + adaptive reasoning + a
verification feedback step (Phase 5), not multiple cooperating agents.
If asked whether multi-agent is implemented and it isn't yet: say so
directly — it's explicitly marked stretch/nice-to-have in the project
scope, not a core claim.

---

## B. Tool & Architecture Choices

**Q: Why Groq instead of OpenAI or Anthropic directly?**
Three reasons: (1) inference latency — Groq's LPU hardware is
significantly faster than typical GPU-served inference, which matters
because this agent makes several sequential LLM calls per query
(planner → search-interpretation → rank → verify → respond), so
per-call latency compounds in a way it doesn't for a single-shot
chatbot; (2) a generous free tier suited to a student project's
budget; (3) an OpenAI-compatible API, so switching providers later is
a config change (base URL + model name), not a rewrite. It was
evaluated against Cerebras (faster raw throughput, but thinner
tooling/ecosystem at evaluation time) and Fireworks AI (strong
structured-output serving, less generous free tier for this use case).

**Q: Why FastAPI over Flask, Django, or Node/Express?**
Async support (most of this app's work is I/O-bound — waiting on
Groq, waiting on product APIs — so async concurrency matters more
than in a typical CRUD app), automatic request/response validation
via Pydantic (the same `Product`/`Intent` schemas are enforced at the
API boundary, not just internally), and free interactive API docs.
Lighter than Django (no ORM/admin/templating overhead this project
doesn't use) and keeps one language (Python) across backend, data
processing, and the agent layer, rather than splitting between
Python and Node.

**Q: Why React + Vite instead of Next.js?**
Next.js's headline features — server-side rendering and a built-in
API layer — aren't needed: FastAPI is already the API layer, and
there's no public-facing SEO surface to justify SSR. Vite gives a
faster local dev loop for a single-page chat interface. This is a
close call, not a strong technical necessity either way — Next.js
would also have worked, and the honest reason it wasn't chosen is
architectural fit + familiarity, not a hard technical blocker.

**Q: Why LangGraph instead of writing the agent loop by hand?**
A hand-written loop would work for a graph this small and has less
dependency overhead — this is a fair pushback. LangGraph was chosen
because it gives explicit, inspectable state at each node, which is
what directly produces the reasoning-trace UI the project promises,
rather than needing to build that instrumentation manually. It's also
a recognized agent framework, which is easier to defend as
demonstrating real agentic infrastructure than an equivalent bespoke
loop, given the project's grading criteria explicitly ask for
demonstrated agentic concepts.

**Q: Why Supabase instead of a local Postgres or a different hosted DB
(e.g. Neon, Railway, RDS)?**
It's standard Postgres underneath, so nothing about schema design or
query code is Supabase-specific — SQLAlchemy talks to it exactly as it
would talk to local Postgres. It was chosen over local Postgres/Docker
specifically to remove a dependency (Docker Desktop) that had already
caused setup friction across two different development machines.
Versus other hosted Postgres providers (Neon, Railway): no strong
technical reason over those alternatives — Supabase's free tier and
familiarity drove the choice, and any of them would satisfy the same
architectural role.

**Q: Why skip a vector database?**
The project doc lists it as optional, and there's no current
requirement for semantic similarity search (e.g. "find me something
like this one"). Category-adaptive ranking works on structured
attributes — price, rating, category-specific specs — which a
relational model handles cleanly. Adding a vector store now would be
infrastructure without a corresponding capability need; it's a
reasonable Phase 9+ addition if a similarity-search feature is added
later, not a gap in the current design.

**Q: Why FakeStoreAPI as the primary data source instead of building
a real catalog from day one?**
Two reasons, one technical and one risk-management. Technically, it
provides a ready-made, category-agnostic normalized shape to build the
schema/normalizer pattern against before real-API integration
complexity is added. For risk: it has no API key, no quota, and no
uptime dependency — meaning a live demo cannot fail due to a
third-party rate limit or outage, which real sources (RapidAPI's
100 req/month cap especially) genuinely can. Real sources are layered
on top in Phase 4 with FakeStoreAPI remaining as the fallback if they
fail.

---

## C. Data, Grounding, and Hallucination

**Q: How do you stop it from hallucinating a price or spec that
doesn't exist?**
Three layered mechanisms: (1) every tool call gets a logged ID, and
the agent's final structured output must attach a
`source_tool_call_id` to every factual claim; claims without one are
dropped before the user sees them — this is enforced by schema
validation, not a prompt instruction the model could ignore; (2) a
separate verifier pass (a second, cheaper LLM call) checks the draft
answer against the raw tool outputs before it's shown, flagging
mismatches; (3) the full ReAct-style trace (Thought → Action →
Observation) is shown to the user, not hidden — so even if something
slipped through, it's auditable rather than a black-box claim.

**Q: What if two claims disagree — the tool output and the model's
phrasing of it?**
That's exactly what the Phase 5 verifier node checks for: it compares
the draft response's claims against the literal tool outputs stored in
the graph's state, not against the model's own summary of them. A
mismatch causes that claim to be corrected or dropped, never passed
through with a caveat.

**Q: How do you evaluate whether recommendations are actually good?**
Task success rate (does the top recommendation actually satisfy the
stated constraints — budget, must-have attributes), latency per query,
tool-call efficiency (how many calls it took to reach an answer), and
user override rate (how often a user rejects the top pick and asks for
something else) — this last one requires the session-memory tracking
from Phase 6 to measure properly.

**Q: What happens if a tool call fails (API down, quota exceeded)?**
Falls back to the cached/demo data source (FakeStoreAPI) with explicit
disclosure in the trace — never a silent failure. This fallback
behavior is deliberately tested (Phase 4 testing plan includes
breaking the API key on purpose) rather than assumed to work.

---

## D. Payments, Trust, and Safety

**Q: Would you trust this with real money?**
No — and that's by design, not a current limitation to apologize for.
Nothing beyond a mocked "Cart Mandate" is implemented: a JSON object
(item, price, quantity, timestamp, consent) modeled on the real-world
AP2 mandate pattern, which only proceeds after the user explicitly
checks a consent box approving that exact object. No payment
processor is integrated and none is planned within this project's
scope.

**Q: What's the real-world path if this became a production system?**
Reference the actual open specs this pattern is modeled on: AP2
(Agent Payments Protocol — Google/FIDO, cryptographic mandates) for
payment authorization, ACP (OpenAI + Stripe + Meta) for the
agent-merchant checkout handshake, and UCP (Google + Shopify) for the
catalog/product-discovery layer. A production version would integrate
with these existing protocols rather than build a proprietary checkout
flow — the mock mandate here is intentionally shaped to be a drop-in
concept match, not a from-scratch design.

**Q: Human-in-the-loop — why require explicit consent instead of just
letting the agent complete the purchase autonomously?**
Because an irreversible, financially consequential action is exactly
the case where autonomous agents should not act without a checkpoint —
this is a widely-held safety principle in agentic system design, not
specific to shopping. The mandate pattern demonstrates that the system
respects that boundary structurally (the "confirm" endpoint requires
the consent flag, not just prompting the user and hoping the model
respects a "wait for confirmation" instruction).

---

## E. Scale, Generalization, and Categories

**Q: Does this only work for the categories you've built?**
Search is designed to be fully general — it isn't tied to specific
categories; it queries whatever category the aggregator API/data
source returns. What's category-specific is the *ranking* logic:
different categories care about different attributes (ANC/battery for
headphones, cushioning/breathability for shoes, RAM/storage for
laptops). For the live demo, a handful of categories are rehearsed
with pre-verified good data quality, while the underlying search
capability is general — this distinction (general search, adaptive
but currently lookup-table-based ranking) should be stated plainly if
asked, rather than implying full automatic generalization to any
category exists today.

**Q: How would you add a new retailer or data source?**
Because of the client/normalizer separation (a design decision made
in Phase 1), adding a source means writing one new client file (raw
API calls) and one new normalizer file (converts that API's shape into
the shared `Product` schema) — zero changes to search, ranking, or the
frontend, since everything downstream only ever sees the normalized
shape.

**Q: How would this scale to production traffic?**
Honestly: this hasn't been load-tested and scale wasn't a design
goal for a class/hackathon project. The architectural choices that
would matter most at scale — async FastAPI (already in place, so
concurrent requests aren't blocking), the product cache (currently a
5-minute in-memory TTL cache, which would need to move to
Supabase/Redis for multi-instance deployment), and rate-limit handling
for real product APIs — are identifiable next steps, not solved
problems.

---

## F. Honesty About the Current Build State

These are the most important answers to have ready, because getting
caught overstating the current state is worse than any technical gap.

**Q: Is this live right now / is this using a real AI model?**
Answer plainly based on what's actually true at demo time. As of this
document, the frontend demo shown is a **UI prototype**: the
"reasoning trace" and "recommendations" are hardcoded JavaScript
objects matched to the query by keyword, not live Groq/LangGraph
calls. This was built deliberately, ahead of the backend agent work,
to validate the user experience and interaction design before
investing in the full pipeline — a standard UI-first prototyping
practice. If asked directly, say this straightforwardly: "This
specific demo is a scripted walkthrough of the intended experience;
the live agent pipeline is [in progress / built] — here's what's real
versus simulated" and point to the phase status in
`IMPLEMENTATION_PLAN.md`. Do not imply the hardcoded trace is a live
model output.

**Q: What's actually built versus planned?**
Be ready to state the current phase status precisely (update this
answer as phases complete): Phase 0 (scaffolding) and Phase 1
(FakeStoreAPI data layer) are built and tested against a real backend.
The frontend UI/UX (trace display, recommendation cards, mandate
modal) is built and demoable, but currently runs on hardcoded
scenario data rather than the live agent. Phases 2 onward (Groq
integration, LangGraph agent, real data sources, grounding/verifier,
session memory, real mandate backend) are planned with a detailed
step-by-step implementation plan, but not yet built as of this
document.

**Q: Why show a hardcoded demo instead of waiting until the real
pipeline works?**
Two honest reasons: it de-risks the UX work (confirming the trace/
recommendation/mandate flow is understandable and well-designed before
spending time wiring the LLM calls that would render it), and it
gives something concrete to gather feedback on early. This is a
legitimate development sequencing choice, not a way of avoiding the
harder agent-building work — the implementation plan for the real
pipeline is fully specified and next.

---

## G. Anticipated Curveballs

**Q: What was the hardest design decision so far?**
The client/normalizer separation in Phase 1 (§9 of ARCHITECTURE.md) —
deciding to pay the upfront cost of a shared schema and per-source
adapter files rather than just wiring FakeStoreAPI directly into the
ranking logic. It felt like overhead for a single data source, but
it's what makes Phase 4 (real data sources) and the category-adaptive
ranking claim actually hold up architecturally instead of requiring a
rewrite.

**Q: What would you do differently if starting over?**
A candid, defensible answer: probably define the `ParsedIntent` and
agent-state schemas (Phase 2/3) before finishing the frontend
prototype, since the prototype's hardcoded shapes were written first
and the real schemas need to match them retroactively — not a large
problem, but sequencing backend contracts before UI polish is
generally the safer order.

**Q: What's the single biggest risk to the demo going wrong?**
Real product API quota exhaustion (RapidAPI's 100 req/month) during
rehearsal eating into the live-demo budget — which is exactly why
Phase 4's design treats real APIs as flag-gated and demo-day-only,
with FakeStoreAPI as an always-available fallback that degrades
gracefully rather than breaking the demo outright.
