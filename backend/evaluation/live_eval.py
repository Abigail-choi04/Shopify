"""
ShopMate AI — Live evaluation (needs your GROQ_API_KEY; makes real model calls)

Run from the backend/ folder (with your .env loaded, i.e. GROQ_API_KEY set):

    python -m evaluation.live_eval                  # all 66 queries, full ShopMate pipeline
    python -m evaluation.live_eval --limit 5        # a quick trial
    python -m evaluation.live_eval --repeat 3       # run each query 3 times (LLM answers vary)
    python -m evaluation.live_eval --baseline       # LLM-only baseline: no tools, no snapshot, no verifier
    python -m evaluation.live_eval --rescore        # recompute the summary from the saved file (no model calls)
    python -m evaluation.live_eval --set replan     # the replanning / clarifying-question stress set (21 queries)

The run is RESUMABLE: every finished query is saved at once, and running the same command again
skips what is already done. If Groq's daily token limit is hit the run stops cleanly; run it
again after the limit resets (the error message says when). Per-minute limits are waited out.

What the full pipeline run measures (per query, then averaged):
  - planner accuracy      did the model parse category, budget and must-haves like the gold intent?
  - first-draft claim accuracy   how many of the explanation claims the model drafted FIRST passed the verifier
  - rewrites / dropped claims    how often one rewrite was needed, and how many claims were finally removed
  - data-only fallback    how often the model's output was unusable
  - replanning            how often nothing met every requirement, how often the agent loosened one requirement,
                          whether that brought products back, and whether the model or the fixed rule chose
  - clarifying questions  how often a question was asked, split into requests that name no kind of product
                          (asking is right) and requests the catalog covers (asking is a false alarm)
  - latency, errors

What the baseline measures: the same model asked for 3 recommendations with no data access. Each
recommended product name is matched against the saved snapshot ("grounded") and the quoted price is
compared with the real listing price. The name matching is approximate, so read it as an estimate.

Per-query details (with product titles) go to data_private/eval/ (git-ignored);
aggregate numbers go to evaluation/results/ (safe to commit). The replan set uses its own files
(live_pipeline_replan.jsonl / live_pipeline_replan.json), so it never mixes with the core results.
"""

import argparse
import asyncio
import json
import os
import re
import statistics
import time
from collections import Counter

from dotenv import load_dotenv

from app.agent.ranking import get_snapshot_category
from app.services import serpapi_client, snapshot_store
from evaluation.common import QUERY_SETS, RESULTS_DIR, load_queries, pct, private_dir

SEARCH_ACTION = re.compile(r'search_products\(category="([^"]*)", max_price=([^)]*)\)')
REPLAN_ACTION = "choose_relaxation("
CLARIFY_ACTION = "ask_clarifying_question("
NO_MATCH_LINE = "No matching products were found"
REWRITE_LINE = re.compile(r"(\d+) of (\d+) claim\(s\) verified; (\d+) failed\. Asking for one rewrite")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", re.sub(r"\([^)]*\)", " ", text.lower())))


# ------------------------------------------------------------- scoring


def requirement_match(gold: str, predicted: str) -> bool:
    a, b = _norm(gold), _norm(predicted)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    ta, tb = _tokens(gold), _tokens(predicted)
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= 0.5


def score_planner(gold: dict, predicted_slug: str | None, predicted_budget: float | None, predicted_musts: list[str]) -> dict:
    gold_category = get_snapshot_category(gold["category_slug"])
    predicted_category = get_snapshot_category(predicted_slug) if predicted_slug else None
    if gold_category is None and predicted_category is None:
        category_ok = True  # both "not something the snapshot covers"
    else:
        category_ok = gold_category == predicted_category
    budget_ok = (gold["max_price"] is None and predicted_budget is None) or (
        gold["max_price"] is not None and predicted_budget is not None and abs(float(gold["max_price"]) - predicted_budget) < 0.5
    )
    gold_musts = gold["must_haves"]
    matched_gold = sum(1 for g in gold_musts if any(requirement_match(g, p) for p in predicted_musts))
    matched_pred = sum(1 for p in predicted_musts if any(requirement_match(g, p) for g in gold_musts))
    return {
        "category_ok": category_ok,
        "budget_ok": budget_ok,
        "must_have_recall": matched_gold / len(gold_musts) if gold_musts else 1.0,
        "must_have_precision": matched_pred / len(predicted_musts) if predicted_musts else 1.0,
        "intent_exact": category_ok and budget_ok and matched_gold == len(gold_musts) and matched_pred == len(predicted_musts),
    }


def parse_trace(trace) -> dict:
    """
    Reads the planner's category and budget from the FIRST search (later searches may use a budget that
    replanning raised, which is not what the planner understood), plus the replanning / question steps.
    """
    slug = budget = None
    first_checked = first_failed = None
    data_only = False
    searches = replans = 0
    clarified = initial_no_match = False
    for step in trace:
        match = SEARCH_ACTION.search(step.text)
        if match:
            searches += 1
            if searches == 1:
                slug = match.group(1)
                budget = None if match.group(2).strip() == "None" else float(match.group(2))
        if step.type == "action" and step.text.startswith(REPLAN_ACTION):
            replans += 1
        if step.type == "action" and step.text.startswith(CLARIFY_ACTION):
            clarified = True
        if NO_MATCH_LINE in step.text and replans == 0:
            initial_no_match = True
        rewrite = REWRITE_LINE.search(step.text)
        if rewrite and first_checked is None:
            first_checked, first_failed = int(rewrite.group(2)), int(rewrite.group(3))
        if "malformed output" in step.text:
            data_only = True
    return {
        "slug": slug, "budget": budget, "first_checked": first_checked, "first_failed": first_failed,
        "data_only_fallback": data_only, "replans": replans, "clarified": clarified, "initial_no_match": initial_no_match,
    }


# ------------------------------------------------------- full pipeline


async def run_pipeline_once(query: dict) -> dict:
    from app.agent.graph import run_agent

    started = time.time()
    record = {"id": query["id"], "type": query["type"], "query": query["query"]}
    try:
        response = await run_agent(query["query"])
    except Exception as error:  # noqa: BLE001 - a failed run is a data point, not a crash
        record.update(error=f"{type(error).__name__}: {error}", seconds=round(time.time() - started, 1))
        return record

    info = parse_trace(response.trace)
    verification = response.verification
    checked = verification.claimsChecked if verification else 0
    first_checked = info["first_checked"] if info["first_checked"] is not None else checked
    first_failed = info["first_failed"] if info["first_failed"] is not None else 0
    record.update(
        seconds=round(time.time() - started, 1),
        planner=score_planner(query["gold"], info["slug"], info["budget"], response.parsedIntent.mustHaves),
        predicted={"slug": info["slug"], "max_price": info["budget"], "must_haves": response.parsedIntent.mustHaves},
        products=len(response.products),
        first_draft_claims=first_checked,
        first_draft_failed=first_failed,
        rewritten=bool(verification and verification.retried),
        final_claims_checked=checked,
        final_claims_dropped=verification.claimsDropped if verification else 0,
        data_only_fallback=info["data_only_fallback"],
        titles=[p.title for p in response.products],
        initial_no_match=info["initial_no_match"],
        replans=info["replans"],
        relaxations=[{"kind": r.kind, "chosen_by": r.chosenBy, "requirement": r.requirement,
                      "old_budget": r.oldBudget, "new_budget": r.newBudget} for r in response.relaxations],
        clarification_asked=response.clarification is not None,
        gold_in_catalog=get_snapshot_category(query["gold"]["category_slug"]) is not None,
    )
    return record


def summarize_replanning(ok: list[dict]) -> dict:
    """Older saved runs (before replanning existed) simply count as 'no replan, no question'."""
    no_match = [r for r in ok if r.get("initial_no_match")]
    replanned = [r for r in ok if r.get("replans", 0) > 0]
    relaxations = [x for r in replanned for x in r.get("relaxations", [])]
    asked = [r for r in ok if r.get("clarification_asked")]
    in_catalog = [r for r in ok if r.get("gold_in_catalog")]
    not_in_catalog = [r for r in ok if "gold_in_catalog" in r and not r["gold_in_catalog"]]
    return {
        "replanning": {
            "runs_with_no_full_match_at_first": len(no_match),
            "runs_replanned": len(replanned),
            "replanned_runs_ending_with_products": sum(1 for r in replanned if r["products"] > 0),
            "no_match_runs_left_empty": sum(1 for r in no_match if r.get("replans", 0) == 0 and r["products"] == 0),
            "relaxation_kinds": dict(Counter(x["kind"] for x in relaxations)),
            "chosen_by": dict(Counter(x["chosen_by"] for x in relaxations)),
        },
        "clarification": {
            "runs_with_question": len(asked),
            "asked_when_no_covered_category_pct": pct(sum(1 for r in not_in_catalog if r.get("clarification_asked")), len(not_in_catalog)),
            "asked_when_category_covered_false_alarm_pct": pct(sum(1 for r in in_catalog if r.get("clarification_asked")), len(in_catalog)),
        },
        "by_type": {
            t: {
                "runs": len(rs),
                "replanned": sum(1 for r in rs if r.get("replans", 0) > 0),
                "with_products": sum(1 for r in rs if r["products"] > 0),
                "asked_question": sum(1 for r in rs if r.get("clarification_asked")),
            }
            for t, rs in sorted(_group_by_type(ok).items())
        },
    }


def _group_by_type(records: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for r in records:
        groups.setdefault(r.get("type", "?"), []).append(r)
    return groups


def summarize_pipeline(records: list[dict], query_set: str = "core") -> dict:
    ok = [r for r in records if "error" not in r]
    planner = [r["planner"] for r in ok]
    with_products = [r for r in ok if r["products"] > 0]
    first_claims = sum(r["first_draft_claims"] for r in with_products)
    first_failed = sum(r["first_draft_failed"] for r in with_products)
    return {
        "query_set": query_set,
        "queries_completed": len({r["id"] for r in ok}),
        "queries_total": len(load_queries(query_set)),
        "runs": len(ok),
        "planner": {
            "category_correct_pct": pct(sum(p["category_ok"] for p in planner), len(planner)),
            "budget_correct_pct": pct(sum(p["budget_ok"] for p in planner), len(planner)),
            "must_have_recall_pct": round(100 * statistics.mean(p["must_have_recall"] for p in planner), 1) if planner else 0,
            "must_have_precision_pct": round(100 * statistics.mean(p["must_have_precision"] for p in planner), 1) if planner else 0,
            "intent_exact_pct": pct(sum(p["intent_exact"] for p in planner), len(planner)),
        },
        "runs_with_products": len(with_products),
        "first_draft_claims": first_claims,
        "first_draft_claims_failed": first_failed,
        "first_draft_claim_error_pct": pct(first_failed, first_claims),
        "runs_needing_rewrite_pct": pct(sum(1 for r in with_products if r["rewritten"]), len(with_products)),
        "final_claims_checked": sum(r["final_claims_checked"] for r in with_products),
        "final_claims_dropped": sum(r["final_claims_dropped"] for r in with_products),
        "data_only_fallback_runs": sum(1 for r in ok if r["data_only_fallback"]),
        "median_seconds": round(statistics.median(r["seconds"] for r in ok), 1) if ok else None,
        "p90_seconds": round(sorted(r["seconds"] for r in ok)[int(0.9 * (len(ok) - 1))], 1) if ok else None,
        **summarize_replanning(ok),
    }


# ----------------------------------------------------------- baseline

BASELINE_SYSTEM = (
    "You are a shopping assistant for India. Recommend exactly 3 specific products that match the request and are sold on Flipkart. "
    'Reply ONLY with JSON: {"products": [{"name": "<exact product name>", "price_inr": <number>}]}'
)


GENERIC = {
    "wireless", "wired", "true", "bluetooth", "earbuds", "earphones", "earphone", "headphones", "with", "and", "for", "in", "ear", "mic",
    "smartphone", "phone", "mobile", "laptop", "notebook", "smartwatch", "watch", "running", "shoes", "shoe", "mens", "men", "women", "womens",
    "ram", "gb", "storage", "ssd", "inch", "size", "black", "blue", "grey", "gray", "white", "pink", "red", "green", "silver", "midnight",
}
VARIANT_WORDS = {"pro", "plus", "max", "ultra", "lite", "se", "neo", "air", "mini", "fe", "prime", "classic", "turbo"}


def match_title(name: str, titles: list[str]) -> tuple[str | None, float]:
    """
    Which snapshot title is the model talking about? The model's name is usually shorter than a
    Flipkart title, so we ask: are (almost) all the distinctive words of the NAME inside the title,
    without the title adding a different variant ('Pro', 'Plus', 'Lite'...)? Returns (title, coverage).
    """
    wanted = {t for t in _tokens(name) - GENERIC if not re.fullmatch(r"\d+(gb|tb|mah)", t)}
    best, best_score = None, 0.0
    if len(wanted) < 2:
        return None, 0.0
    model_numbers = {t for t in wanted if any(c.isdigit() for c in t)}  # '11', 'm53', '5g', '131' must all appear
    for title in titles:
        have = _tokens(title)
        if not have or not model_numbers <= have:
            continue
        coverage = len(wanted & have) / len(wanted)
        extras = (have - GENERIC) - wanted
        if extras & VARIANT_WORDS:
            continue
        # prefer the closest title: high coverage, then fewest extra words
        score = coverage - 0.01 * len(extras)
        if score > best_score:
            best, best_score = title, score
    return best, max(0.0, round(best_score, 2))


async def run_baseline_once(query: dict, call_groq_json) -> dict:
    snapshot = snapshot_store.load_snapshot()
    category = get_snapshot_category(query["gold"]["category_slug"])
    catalog = snapshot.category(category) if (snapshot and category) else []
    record = {"id": query["id"], "type": query["type"], "query": query["query"], "in_scope": bool(catalog)}
    started = time.time()
    try:
        answer = await call_groq_json(BASELINE_SYSTEM, query["query"])
    except Exception as error:  # noqa: BLE001
        record.update(error=f"{type(error).__name__}: {error}")
        return record
    record["seconds"] = round(time.time() - started, 1)
    items = answer.get("products", []) if isinstance(answer, dict) else []
    by_title = {p.title: p for p in catalog}
    rows = []
    for item in items[:3]:
        name = str(item.get("name", ""))
        title, score = match_title(name, list(by_title))
        grounded = title is not None and score >= 0.7
        price_ok = None
        if grounded:
            real = by_title[title].price_inr
            try:
                price_ok = abs(float(item.get("price_inr")) - real) <= 0.10 * real
            except (TypeError, ValueError):
                price_ok = False
        rows.append({"name": name, "quoted_price": item.get("price_inr"), "grounded": grounded, "match_score": round(score, 2), "matched_title": title if grounded else None, "price_within_10pct": price_ok})
    record["recommendations"] = rows
    return record


def regrade_baseline(records: list[dict]) -> list[dict]:
    """Re-match saved baseline names against the snapshot (no model calls)."""
    snapshot = snapshot_store.load_snapshot()
    for record in records:
        category = get_snapshot_category(record.get("category_slug") or _gold_slug(record["id"]))
        catalog = snapshot.category(category) if (snapshot and category) else []
        by_title = {p.title: p for p in catalog}
        for rec in record.get("recommendations", []):
            title, score = match_title(rec["name"], list(by_title))
            rec["grounded"] = title is not None and score >= 0.7
            rec["match_score"] = score
            rec["matched_title"] = title if rec["grounded"] else None
            price = rec.get("quoted_price")
            rec["price_within_10pct"] = None
            if rec["grounded"] and price is not None:
                try:
                    real = by_title[title].price_inr
                    rec["price_within_10pct"] = abs(float(price) - real) <= 0.10 * real
                except (TypeError, ValueError):
                    rec["price_within_10pct"] = False
    return records


def _gold_slug(query_id: str) -> str | None:
    for query_set in QUERY_SETS:
        for query in load_queries(query_set):
            if query["id"] == query_id:
                return query["gold"]["category_slug"]
    return None


def summarize_baseline(records: list[dict], query_set: str = "core") -> dict:
    scoped = [r for r in records if r.get("in_scope") and "error" not in r and r.get("recommendations")]
    recs = [x for r in scoped for x in r.get("recommendations", [])]
    grounded = [x for x in recs if x["grounded"]]
    return {
        "query_set": query_set,
        "queries_completed": len({r["id"] for r in records if "error" not in r}),
        "queries_total": len(load_queries(query_set)),
        "in_scope_runs": len(scoped),
        "recommendations": len(recs),
        "grounded_in_catalog_pct": pct(len(grounded), len(recs)),
        "grounded_count": len(grounded),
        "price_checked_count": sum(1 for x in grounded if x["price_within_10pct"] is not None),
        "price_within_10pct_of_listing_pct_of_grounded": pct(sum(1 for x in grounded if x["price_within_10pct"]), sum(1 for x in grounded if x["price_within_10pct"] is not None)),
    }


# --------------------------------------------------------------- main

RETRY_IN = re.compile(r"try again in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", re.I)


def is_rate_limit(text: str) -> bool:
    return "RateLimit" in text or "429" in text or "rate limit" in text.lower()


def is_daily_limit(text: str) -> bool:
    lowered = text.lower()
    return "tokens per day" in lowered or "(tpd)" in lowered or "requests per day" in lowered


def wait_seconds(text: str, default: float = 30.0) -> float:
    match = RETRY_IN.search(text)
    if not match or not any(match.groups()):
        return default
    hours, minutes, seconds = (float(g) if g else 0.0 for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def load_saved(path) -> list[dict]:
    """Reads the saved runs. Tolerates two records stuck on one line (an older version wrote no final newline)."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    decoder, position, rows = json.JSONDecoder(), 0, []
    while True:
        while position < len(text) and text[position].isspace():
            position += 1
        if position >= len(text):
            break
        row, position = decoder.raw_decode(text, position)
        rows.append(row)
    return [r for r in rows if "error" not in r]  # failed runs are simply redone


def save_all(path, records: list[dict]) -> None:
    """Rewrites the file with exactly one record per line (also repairs an older file)."""
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")


async def run_all(queries, baseline: bool, repeat: int, pause: float, path) -> list[dict]:
    from app.services.groq_client import call_groq_json

    records = load_saved(path)
    save_all(path, records)
    done = {(r["id"], r.get("repeat", 1)) for r in records}
    if done:
        print(f"Resuming: {len(done)} finished run(s) found in {path.name}; they will be skipped.", flush=True)
    for query in queries:
        for attempt in range(1, repeat + 1):
            if (query["id"], attempt) in done:
                continue
            for _try in range(4):
                record = await (run_baseline_once(query, call_groq_json) if baseline else run_pipeline_once(query))
                error = record.get("error", "")
                if not error or not is_rate_limit(error):
                    break
                if is_daily_limit(error):
                    print(f"\nSTOPPED: Groq daily limit reached. {error[:300]}\nSaved {len(records)} finished run(s). "
                          "Run the same command again after the limit resets; it will continue where it stopped.", flush=True)
                    return records
                wait = min(wait_seconds(error) + 2, 180)
                print(f"   rate limit on {query['id']}: waiting {wait:.0f}s then retrying", flush=True)
                await asyncio.sleep(wait)
            record["repeat"] = attempt
            if "error" in record:
                print(f"   {query['id']} failed ({record['error'][:90]}); not saved, will be retried next run", flush=True)
                continue
            records.append(record)
            with path.open("a", encoding="utf-8") as handle:  # saved immediately: a crash loses nothing
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            status = "ok" if not baseline else f"{len(record.get('recommendations', []))} recs"
            print(f"[{len(records)}] {query['id']:<9} {record.get('seconds', '-')}s  {status}", flush=True)
            await asyncio.sleep(pause)
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="ShopMate live evaluation")
    parser.add_argument("--baseline", action="store_true", help="LLM-only baseline instead of the full pipeline")
    parser.add_argument("--rescore", action="store_true", help="recompute the summary from the saved file; no model calls")
    parser.add_argument("--limit", type=int, default=0, help="only the first N queries")
    parser.add_argument("--repeat", type=int, default=1, help="runs per query")
    parser.add_argument("--type", default="", help="only queries of this type (e.g. multi)")
    parser.add_argument("--pause", type=float, default=2.0, help="seconds between calls (free-tier rate limits)")
    parser.add_argument("--set", dest="query_set", choices=sorted(QUERY_SETS), default="core",
                        help="core = the 66 main queries; replan = the replanning / clarifying-question stress set")
    args = parser.parse_args()

    load_dotenv()
    os.environ.pop("SERPAPI_ENABLED", None)  # never spend a web search during evaluation
    assert not serpapi_client.is_enabled()
    if snapshot_store.load_snapshot(force=True) is None:
        raise SystemExit("No snapshot found in backend/data_private/.")
    if not args.rescore and not os.getenv("GROQ_API_KEY"):
        raise SystemExit("GROQ_API_KEY is not set. Put it in backend/.env first.")

    name = "baseline" if args.baseline else "pipeline"
    if args.query_set != "core":
        name += f"_{args.query_set}"  # its own files: never mixed into the core results
    path = private_dir() / f"live_{name}.jsonl"
    queries = load_queries(args.query_set)
    if args.type:
        queries = [q for q in queries if q["type"] == args.type]
    if args.limit:
        queries = queries[: args.limit]

    if args.rescore:
        records = load_saved(path)
    else:
        records = asyncio.run(run_all(queries, args.baseline, args.repeat, args.pause, path))
    if args.baseline:
        records = regrade_baseline(records)
    summary = summarize_baseline(records, args.query_set) if args.baseline else summarize_pipeline(records, args.query_set)
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / f"live_{name}.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print("\n" + json.dumps(summary, indent=1))
    print(f"\nQueries finished: {summary['queries_completed']} of {summary['queries_total']}. "
          + ("All done." if summary["queries_completed"] >= summary["queries_total"] else "Run the command again later to finish the rest."))


if __name__ == "__main__":
    main()