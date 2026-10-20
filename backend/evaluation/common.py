"""
ShopMate AI — Evaluation helpers shared by the evaluation scripts.

Run every script from the backend/ folder, e.g.:
    python -m evaluation.offline_eval
"""

import json
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
QUERIES_PATH = EVAL_DIR / "queries.json"
RESULTS_DIR = EVAL_DIR / "results"  # aggregate numbers only: safe to commit


def load_queries() -> list[dict]:
    return json.loads(QUERIES_PATH.read_text(encoding="utf-8"))["queries"]


def private_dir() -> Path:
    """Per-product files (they contain Flipkart titles) go in the git-ignored data_private folder."""
    from app.services import snapshot_store

    folder = snapshot_store.snapshot_dir() / "eval"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def pct(part: float, whole: float) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0