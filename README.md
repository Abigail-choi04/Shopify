# ShopMate AI

An agentic shopping assistant for the Indian market. You describe what you want ("wireless earbuds under ₹2,000 with a good mic"); the agent plans, searches real listings, checks each requirement against what the listing actually says, ranks the results, explains every recommendation with claims that are checked against the data, and, if you decide to buy, issues a signed mock "cart mandate" after your explicit consent.

Stack: FastAPI + LangGraph + Groq (`openai/gpt-oss-120b`) on the backend, React + Vite on the frontend, Postgres (Supabase) for the mandate audit log.

What makes it agentic (in plain words):
- **Plans:** the model turns your request into a category, a budget and must-haves, or asks one question if it can't tell what you want.
- **Uses tools:** product search, requirement checking and ranking are tools whose calls are logged with IDs.
- **Replans:** if nothing meets everything, the agent finds the smallest change that brings real products back (raise the budget a little, or drop one requirement; never a brand you named), searches again, and tells you what it gave up.
- **Checks itself:** every sentence of explanation is a claim that a plain-Python verifier checks against the listing data; failed claims get one rewrite, then are dropped.
- **Asks before acting:** a purchase needs a signed mandate that you approve; the server re-checks the price.

More detail: `ARCHITECTURE.md` (how it fits together), `IMPLEMENTATION_PLAN.md` (what is built, what is not), `QA_PREP.md` (questions judges may ask).

---

## 1. Prerequisites (one-time)

- **Python 3.11 or 3.12** (check with `python --version`). Python 3.13+ may fail to install `psycopg2-binary`; use 3.12 if it does.
- **Node.js 18+** (check with `node --version`).
- A free **Groq API key** (https://console.groq.com). The free tier allows 200,000 tokens per day.
- A free **Supabase** project if you want the database health check and the mandate audit log in Postgres (optional: without it, mandates are stored in a local file).

## 2. Backend

```bash
cd backend
python -m venv .venv
```

Activate it:
- **Windows (Git Bash):** `source .venv/Scripts/activate`
- **macOS / Linux:** `source .venv/bin/activate`

```bash
pip install -r requirements.txt
cp .env.example .env
```

Open `.env` and fill in at least `GROQ_API_KEY` and `MANDATE_SECRET`. Add `DATABASE_URL` if you use Supabase.

### Product data (private, not in the repo)

Search runs on a saved snapshot of Flipkart listings (480 products in five categories, captured 8 Oct 2026). Flipkart's terms do not allow republishing listings, so the files are **not** in git. Put these five files in `backend/data_private/` (or point `SNAPSHOT_DIR` at their folder):

`earphones.json`, `smartphones.json`, `laptops.json`, `running_shoes.json`, `smartwatches.json`

Check that they load:
```bash
python -m scripts.check_snapshot
```

Run the backend:
```bash
uvicorn app.main:app --reload
```
You should see `Uvicorn running on http://127.0.0.1:8000`. Interactive API docs are at http://127.0.0.1:8000/docs.

## 3. Frontend

In a **new** terminal:
```bash
cd frontend
npm install
npm run dev
```
Open **http://localhost:5173**. The frontend calls the backend at `http://localhost:8000` (change it with `VITE_API_URL` in `frontend/.env`).

## 4. Try it

Type one of these:

| Request | What you should see |
|---|---|
| Wireless earphones under ₹1500 | Three ranked products, each with checked claims and a "verified" banner |
| Phone with 12GB RAM under ₹9,000 | A "Changed to find matches" note: nothing matched everything, so it says exactly what was changed |
| Something nice for my brother's birthday | One clarifying question instead of a guess |
| Press "Select this" on a product | The cart-mandate screen: review, consent, approve, mock checkout, audit log |

## 5. Tests and evaluation

```bash
cd backend
python -m pytest tests -q                  # automated tests; no internet or keys needed
python -m evaluation.offline_eval          # offline evaluation on the snapshot; no keys, no tokens
python -m evaluation.live_eval             # live evaluation with Groq (uses tokens; resumable)
python -m evaluation.live_eval --baseline  # the same model with no tools or data (comparison)
python -m evaluation.live_eval --set replan  # replanning / clarifying-question stress set (21 queries)
python -m evaluation.live_eval --rescore   # recompute a summary from saved runs, no model calls
```

The live evaluation saves every finished query and stops cleanly when Groq's daily token limit is reached; run the same command again after the limit resets and it continues. Aggregate results are in `backend/evaluation/results/` (safe to share); per-product files stay in `backend/data_private/eval/` (private).

## 6. Environment settings (`backend/.env`)

| Setting | Meaning |
|---|---|
| `GROQ_API_KEY`, `GROQ_MODEL` | The language model (default `openai/gpt-oss-120b`) |
| `DATA_SOURCE` | `snapshot` (default) or `fakestore` (old toy catalog) |
| `SNAPSHOT_DIR` | Folder with the five snapshot files (default `backend/data_private`) |
| `SERPAPI_ENABLED`, `SERPAPI_KEY` | Optional web-search fallback; off by default |
| `MANDATE_SECRET`, `MANDATE_TTL_MINUTES` | Signing secret and lifetime for cart mandates |
| `DATABASE_URL`, `MANDATE_DB_URL` | Postgres for the health check and mandate audit log (falls back to a local file) |

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Frontend shows "unreachable" | The `uvicorn` terminal isn't running, or crashed; read its output |
| `GROQ_API_KEY` errors, or a 429 "rate limit" message | Key missing, or the free daily token limit is used up; wait for the reset |
| "No snapshot found" | The five JSON files are not in `backend/data_private/` (or `SNAPSHOT_DIR`) |
| `pip install` fails on `psycopg2-binary` | Use Python 3.12, or install a newer `psycopg2-binary` |
| Port 8000 / 5173 already in use | Close the other program using it |
| After pulling, your old `venv/` folder disappeared | The venv used to be committed by mistake; recreate it with the steps in section 2 |