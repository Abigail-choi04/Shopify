# ShopMate AI — Setup Guide (Phases 0 & 1)

This covers getting the full stack running: database (Supabase), backend (FastAPI), and frontend (React + Vite).

---

## 1. Database (Supabase)

1. Create a free project at https://supabase.com (New Project -> set name, password, region -> wait for it to provision).
2. In the Supabase dashboard: click the green **Connect** button (top right) -> **URI** tab. Copy the connection string, replacing `[YOUR-PASSWORD]` with your actual database password.
3. No local install or Docker needed — this database runs in the cloud, so an internet connection is required to reach it.

## 2. Install prerequisites (one-time)

- **Python 3.11+** — check with `python --version`.
- **Node.js 18+** — check with `node --version`.

## 3. Set up the backend

```bash
cd backend
python -m venv .venv
```

Activate the virtual environment:
- **Windows (Git Bash):** `source .venv/Scripts/activate`
- **macOS:** `source .venv/bin/activate`

Install dependencies and set up your environment file:
```bash
pip install -r requirements.txt
cp .env.example .env
```

Open `.env` and paste in your real Supabase connection string from Step 1.

Run the backend:
```bash
uvicorn app.main:app --reload
```

Leave this terminal running. You should see `Uvicorn running on http://127.0.0.1:8000`.

## 4. Set up the frontend

Open a **new** terminal (leave the backend one running):

```bash
cd frontend
npm install
npm run dev
```

You should see `Local: http://localhost:5173/`.

## 5. Test it

Open **http://localhost:5173**. You should see:

- Backend (FastAPI) status: **ok**
- Database (Postgres/Supabase) status: **ok**
- Products (FakeStoreAPI, normalized) status: **ok (20 products loaded)**, followed by a grid of sample products.

### Troubleshooting

| Symptom | Likely cause |
|---|---|
| Backend status: "unreachable" | The `uvicorn` terminal isn't running, or crashed — check that terminal for errors. |
| DB status: "DATABASE_URL not set in .env" | `.env` is missing, or you're running `uvicorn` from the wrong folder (must be `backend/`). |
| DB status: connection error / timeout | Check your internet connection, and double check you replaced `[YOUR-PASSWORD]` in the connection string with your real password. |
| DB status: "password authentication failed" | Your Supabase database password is wrong in `.env` — re-copy the connection string from the Supabase dashboard. |
| Products status: error | FakeStoreAPI may be temporarily down, or you're offline — this is an external public API with no login required. |
| Port 8000/5173 already in use | Something else on your machine is using that port — close it, or ask for help changing the port. |

---

## What's next (Phase 2)

Wiring up Groq for natural-language intent parsing — turning a shopping request like "noise-cancelling headphones under ₹8000" into structured intent. No agent/tools yet, just prompt → structured JSON.
