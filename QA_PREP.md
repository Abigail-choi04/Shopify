# ShopMate AI — Judge / Reviewer Q&A Prep

Written the way you would say it out loud: short first, detail if pushed. Numbers come from `backend/evaluation/results/`; re-check them if the data or code changes.

---

## A. "Why is this agentic and not just an LLM feature?"

**Q: What makes this different from a chatbot with a shopping prompt?**
A chatbot answers from one model call. ShopMate plans (turns the request into a category, budget and must-haves, or asks a question if it can't tell), calls logged tools to get real data, replans when a search fails, and verifies its own draft before showing it. The graph has an explicit node for each of those, and the trace shows them.

**Q: Isn't "search then rank" a fixed pipeline, not real autonomy?**
The shape is fixed on purpose, so the trace is inspectable and the demo reliable. The decisions inside it are not scripted: the planner decides what the request means and when to ask a question, and when nothing matches the replanner decides which constraint to give up and searches again. Honest framing: it is a constrained, structured agent, a common and defensible pattern, not an open-ended autonomous one.

**Q: What does the agent do when it fails?**
If the search returns nothing, code works out every single change that would bring real products back (raise the budget a little, or drop one requirement), the model picks one, code checks the pick, and the search runs again, at most twice. The shopper is told exactly what was given up. A brand they named is never dropped. Offline, this rescued 5 of the 6 queries that returned nothing.

**Q: What's the multi-agent story?**
There isn't one, and we don't claim it. The agentic claim rests on planning, tool use, replanning, a verification feedback loop and a consent-gated action. A second critic agent is a stretch goal and is not built.

**Q: Is there memory?**
Not across turns: each request is independent. A clarifying question's answer is sent back as a new request. Session memory is planned future work.

---

## B. Tool and architecture choices

**Q: Why Groq and `gpt-oss-120b`?**
Low latency matters because one answer takes several sequential model calls; the free tier suits a student project; the API is OpenAI-compatible so changing provider is a settings change. The model only plans, chooses among options the code offers, and phrases claims; it never decides what is true.

**Q: Why LangGraph instead of a hand-written loop?**
A hand-written loop would work for a graph this size. LangGraph gives explicit state at each node (which is what produces the trace) and clean conditional branches for clarify and replan.

**Q: Why FastAPI? Why React + Vite?**
FastAPI: async for I/O-bound model calls, Pydantic validation at the API boundary, one language for backend and agent. React + Vite: FastAPI is already the API layer and there is no need for server-side rendering, so Next.js adds nothing here. A close call, not a technical necessity.

**Q: Why Supabase?**
It is standard Postgres, so nothing is Supabase-specific; it removed a Docker dependency that had caused setup friction across laptops. It holds the mandate audit log; if no database is reachable the app falls back to a local file.

**Q: Why no vector database?**
Ranking works on structured attributes (price, rating, typed specs). There is no similarity-search requirement, so a vector store would be infrastructure without a need.

---

## C. Data: what data do you use, and where does it come from?

**Q: Where does the product data come from? Show us.**
A saved snapshot of 480 Flipkart listings in five categories (82 earphones, 100 smartphones, 98 laptops, 100 running shoes, 100 smartwatches), captured on 8 October 2026 with a third-party scraping service (Apify). It is stored privately in `backend/data_private/` because Flipkart's terms don't allow republishing listings. Nothing else is stored: prices, ratings and specs are read from those files, and every answer states the capture date. Be ready to open the folder and show the files and the `check_snapshot` output.

**Q: Why a snapshot and not live data?**
Repeatable evaluation, no API quota risk during the demo, and no scraping at demo time. The cost is that it is one moment, one retailer and about 100 listings per category, taken during a sale. An optional SerpAPI web fallback exists (off by default); its results are link-only and cannot go into a mandate because the server can't re-check their price.

**Q: What if a listing doesn't state a spec?**
It is "unknown", never a guess. A fact exists only when the listing states it clearly; a self-contradicting listing yields no fact. Only products the listing clearly contradicts are removed.

**Q: What currency do you use?**
Rupees. Flipkart prices are already in INR; for other sources the exchange rate is fetched live, not fixed.

---

## D. Grounding and hallucination

**Q: How do you stop it inventing a price or spec?**
The model writes explanations as separate claims, each citing the tool call it came from. A plain-Python verifier checks every claim against the real listing: the field, the cited call, the value, the yes/no wording and every number in the sentence. A failed claim gets one rewrite; if it still fails it is dropped. Nothing unverified reaches the shopper, and the full trace is shown.

**Q: How do you know the verifier works?**
A fault-injection test: take true claims about every product, corrupt them in 16 known ways, and count what is rejected. It rejected 12,121 of 12,132 corrupted claims (99.9%) and 0 of 7,321 true claims. The test also found a real bug in an earlier version (6.0% of true claims wrongly rejected), which we fixed. Be honest about its limit: it is synthetic and covers the error classes we defined.

**Q: Did the live model ever fail the verifier?**
In the live run on all 66 queries (99 runs), 0 of 1,350 first-draft claims failed. So the verifier was a safety net that wasn't triggered on this model and these queries; its catching power is shown by the fault test, not by live failures.

**Q: How do you evaluate recommendations?**
66 queries with gold intents (category, budget, must-haves). Planner: category and budget were correct in every live run; must-have recall 82.2%, precision 92.4%, strict exact-intent 71.7% (most misses are paraphrases, such as "Bluetooth" for "wireless"). We also compare against the same model with no tools or data: only 6 of its 180 recommended products matched a current listing (3.3%). Limits: queries and gold intents were written by the authors, one model, one snapshot.

**Q: Did you check requirement matching with human reviewers?**
No. We designed a blind two-reviewer check but dropped it; the paper says so. What we have instead: rules that are deterministic and tested, an extraction check against listing titles (97 of 97 phones and 98 of 98 laptops agree on RAM), and the fault-injection test. Say plainly that requirement matching was not validated by human reviewers.

**Q: What happens if the model or an API fails?**
If the model's output is unusable, the answer falls back to data only, with the trace saying so. If Groq's free daily limit is hit, the request errors visibly. The evaluation scripts wait out per-minute limits and resume after daily limits. Failures are never silent.

---

## E. Payments, trust and safety

**Q: Would you trust this with real money?**
No, by design. Nothing real is wired: the "cart mandate" is a mock modelled on the AP2 pattern. The server drafts it with its own price (the browser's price is ignored), approval needs explicit consent and re-checks the price, the approved cart is signed with HMAC-SHA256, and checkout re-verifies state, expiry, signature and price. Every step is in an audit log. 18 automated tests cover tampering, expiry, wrong key, price change and reuse.

**Q: Why require consent instead of letting the agent buy?**
A purchase is irreversible and costs money, which is exactly where agents should stop for a human. The check is structural (the approve endpoint refuses without consent, and checkout refuses unsigned or changed carts), not a prompt the model could ignore.

**Q: What is the real-world path?**
Integrate with the open protocols this pattern follows: AP2 for payment authorization, ACP for the merchant checkout handshake, UCP for catalog discovery, instead of a proprietary flow.

---

## F. Scale and generalization

**Q: Does it only work for the categories you built?**
Five categories have snapshot data and typed spec rules. Outside them the agent says the catalog doesn't cover it (and does not replan, since loosening can't help). Adding a source means one client and one normalizer; adding a category means data plus its rules.

**Q: How would this scale?**
Honestly, not tested for scale. Next steps would be a shared cache instead of in-process state, a licensed live product feed, and rate-limit handling.

---

## G. Honesty about the current build state

Say these plainly; overstating is worse than any gap.

**Q: Is this live? Is the AI real?**
Yes. The frontend calls the real backend, which runs the LangGraph agent with Groq and the real snapshot. The old scripted prototype has been replaced.

**Q: What is built and what isn't?**
Built: planning, search, requirement matching, ranking, claim verification, replanning, clarifying questions, the mock mandate with approval screen, and the evaluation set. Not built: memory across turns, streaming, a multi-agent critic, a live product feed. The mandate is a mock for a single server with no real payment.

**Q: What are the main limitations?**
One snapshot of one retailer, about 100 listings per category, during a sale, and private; English-only rules for five categories; one model; authors wrote the queries; no human validation of requirement matching; live results mostly one run per query.

---

## H. Curveballs

**Q: Hardest design decision?**
Making facts exist only when a listing states them clearly. It means silence is "unknown" rather than pass or fail, which changes what the shopper sees and keeps the verifier honest.

**Q: What would you do differently?**
Define the evaluation set earlier, and plan for the model's free-tier token limit from the start (the live runs took several days of quota).

**Q: Biggest demo risk?**
Groq's daily token limit or a network failure during the demo. Mitigation: rehearse with a few queries only, keep a recorded run, and know that the data side works offline.