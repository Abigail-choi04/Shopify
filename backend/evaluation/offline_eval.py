"""
ShopMate AI — Offline evaluation (no Groq key, no internet)

Run from the backend/ folder:
    python -m evaluation.offline_eval

Five measurements, all on the saved Flipkart snapshot and all repeatable:

  A. Data coverage         how many products state each spec clearly, and how many contradict themselves
  B. Extraction check      do the spec facts we extracted agree with what the product TITLE says (RAM, storage)?
  C. Retrieval and ranking run the 66 queries in queries.json through search -> requirement check -> ranking,
                           using the GOLD intent (what a perfect planner would produce), so no language
                           model is involved. Also shows what grouping variants and review-weighting change.
  D. Verifier fault test   take true claims about every product, corrupt them in known ways, and count how many
                           corruptions the verifier catches (and how many TRUE claims it wrongly rejects).

  E. Replanning            for the queries where nothing meets every requirement, would loosening ONE
                           requirement (the fixed rule's pick; the model's pick is measured live) bring
                           real products back, and how much does it change the request?

Writes evaluation/results/offline_results.json (aggregate numbers only).
"""

import asyncio
import json
import math
import random
import statistics
import sys
from collections import Counter, defaultdict

from app.agent import tools as agent_tools
from app.agent.ranking import get_snapshot_category
from app.agent.replan import MAX_REPLANS, apply_option, build_options, choose_by_rule
from app.agent.requirements import MET
from app.agent.tools import filter_by_requirements, rank_products, search_products
from app.agent.verifier import verify_claim
from app.normalizers.spec_facts import COMPARISON_SPECS
from app.schemas.agent import Claim
from app.schemas.intent import ParsedIntent
from app.services import serpapi_client, snapshot_store
from evaluation.common import RESULTS_DIR, load_queries, pct

import re

# ---------------------------------------------------------------- A. coverage


def coverage(snapshot) -> dict:
    out = {}
    for category in snapshot.counts:
        products = snapshot.category(category)
        specs = {}
        for key, label in COMPARISON_SPECS.get(category, []):
            have = sum(1 for p in products if key in p.spec_facts)
            conflict = sum(1 for p in products if key in p.spec_conflicts)
            specs[key] = {"label": label, "stated_pct": pct(have, len(products)), "conflict_count": conflict}
        out[category] = {
            "products": len(products),
            "distinct_models": len({p.group_id for p in products}),
            "with_rating_pct": pct(sum(1 for p in products if p.rating is not None), len(products)),
            "with_any_conflict": sum(1 for p in products if p.spec_conflicts),
            "specs": specs,
        }
    return out


# ------------------------------------------------------------ B. extraction


RAM_IN_TITLE = {
    "smartphones": re.compile(r"(\d+)\s*GB\s*RAM", re.I),  # "Phone X (Blue, 128 GB) (8 GB RAM)"
    "laptops": re.compile(r"\(\s*(\d+)\s*GB\s*/", re.I),  # "Laptop - (16 GB/512 GB SSD/Windows 11 Home)"
}


def extraction_check(snapshot) -> dict:
    out = {}
    for category, pattern in RAM_IN_TITLE.items():
        agree = disagree = 0
        for product in snapshot.category(category):
            match = pattern.search(product.title)
            fact = product.spec_facts.get("ram_gb")
            if match and fact:
                if float(match.group(1)) == fact.value:
                    agree += 1
                else:
                    disagree += 1
        out[category] = {"title_and_fact_both_present": agree + disagree, "agree": agree, "disagree": disagree}
    return out


# ------------------------------------------------- C. retrieval and ranking


async def run_query(query: dict) -> dict:
    gold = query["gold"]
    slug, budget, must_haves = gold["category_slug"], gold["max_price"], gold["must_haves"]
    category = get_snapshot_category(slug)
    snapshot = snapshot_store.load_snapshot()
    row = {"id": query["id"], "type": query["type"], "category": category, "covered": category is not None}
    if category is None:
        row.update(in_budget=0, kept=0, excluded=0, top=0, empty_reason="category not in snapshot")
        return row

    candidates = await search_products(slug, budget)
    kept, excluded, results = filter_by_requirements(candidates, must_haves, snapshot.brands(category))
    top = rank_products(kept, 3, results)

    statuses = Counter(r.status for p in top for r in results.get(p.id, []))
    fully = sum(1 for p in top if all(r.status == MET for r in results.get(p.id, [])))
    row.update(in_budget=len(candidates), kept=len(kept), excluded=len(excluded), top=len(top),
               top_fully_confirmed=fully, req_status=dict(statuses))
    if not top:
        row["empty_reason"] = "nothing in budget" if not candidates else "every product contradicts a requirement"
    # grouping effect: how many top-3 slots would be repeats of one model if variants were not grouped?
    ungrouped = [p.model_copy(update={"group_id": None}) for p in kept]
    top_ungrouped = rank_products(ungrouped, 3, results)
    models = {p.group_id for p in kept if p.id in {u.id for u in top_ungrouped}}
    row["ungrouped_duplicate_slots"] = len(top_ungrouped) - len(models)
    # review weighting effect on the #1 pick
    if top:
        saved = agent_tools.PRIOR_REVIEWS
        agent_tools.PRIOR_REVIEWS = 0  # prior of 0 reviews = plain rating
        try:
            plain_top = rank_products(kept, 1, results)
        finally:
            agent_tools.PRIOR_REVIEWS = saved
        row["top1_reviews_weighted"] = top[0].rating_count
        row["top1_reviews_plain"] = plain_top[0].rating_count if plain_top else None
        row["top1_changed_by_weighting"] = plain_top[0].id != top[0].id if plain_top else False
    return row


def summarize_queries(rows: list[dict]) -> dict:
    answerable = [r for r in rows if r.get("top", 0) > 0]
    by_type = defaultdict(list)
    for r in rows:
        by_type[r["type"]].append(r)
    status_total = Counter()
    for r in rows:
        status_total.update(r.get("req_status", {}))
    pair_total = sum(status_total.values())
    slots = sum(r["top"] for r in rows)
    weighted_changed = [r for r in rows if r.get("top1_changed_by_weighting")]
    low_plain = [r for r in rows if r.get("top1_reviews_plain") is not None and (r["top1_reviews_plain"] or 0) < 50]
    low_weighted = [r for r in rows if r.get("top1_reviews_weighted") is not None and (r["top1_reviews_weighted"] or 0) < 50]
    return {
        "queries": len(rows),
        "in_scope": sum(1 for r in rows if r["covered"]),
        "answerable": len(answerable),
        "empty_in_scope": [r["id"] for r in rows if r["covered"] and r["top"] == 0],
        "empty_reasons": dict(Counter(r.get("empty_reason") for r in rows if r["covered"] and r["top"] == 0)),
        "top_slots": slots,
        "top_slots_fully_confirmed_pct": pct(sum(r.get("top_fully_confirmed", 0) for r in rows), slots),
        "requirement_pair_status_pct": {k: pct(v, pair_total) for k, v in status_total.items()},
        "requirement_pairs": pair_total,
        "mean_excluded_per_query": round(statistics.mean(r["excluded"] for r in rows if r["covered"]), 1),
        "by_type": {
            t: {"queries": len(v), "answerable": sum(1 for r in v if r.get("top", 0) > 0),
                "mean_kept": round(statistics.mean(r["kept"] for r in v), 1)}
            for t, v in by_type.items()
        },
        "grouping": {
            "queries_with_duplicate_models_if_ungrouped": sum(1 for r in rows if r.get("ungrouped_duplicate_slots", 0) > 0),
            "duplicate_slots_if_ungrouped": sum(r.get("ungrouped_duplicate_slots", 0) for r in rows),
        },
        "review_weighting": {
            "queries_with_a_top1": sum(1 for r in rows if r.get("top1_reviews_plain") is not None),
            "top1_changed": len(weighted_changed),
            "top1_under_50_reviews_plain": len(low_plain),
            "top1_under_50_reviews_weighted": len(low_weighted),
        },
    }


# ---------------------------------------------------- D. verifier fault test

CALLS = {"call_001", "call_002", "call_003", "call_004", "call_005"}
SEARCH_CALL, RANK_CALL = "call_002", "call_003"


def _label(key: str) -> str:
    return key.replace("_", " ")


def spec_sentence(key: str, fact) -> str:
    if isinstance(fact.value, bool):
        return f"It has {_label(key)}." if fact.value else f"No {_label(key)}."
    return f"{_label(key).capitalize()}: {fact.display}."


def true_claims(product, max_price) -> list[Claim]:
    claims = [
        Claim(field="price", value=product.price_inr, text=f"Priced at ₹{product.price_inr:,.0f}.", source_tool_call_id=SEARCH_CALL),
        Claim(field="rank", value=1, text="Ranked #1 of 3.", source_tool_call_id=RANK_CALL),
        Claim(field="category", value=product.category, text="It is in the right category.", source_tool_call_id=SEARCH_CALL),
        Claim(field="within_budget", value=True, text="It is within your budget.", source_tool_call_id=SEARCH_CALL),
    ]
    if product.rating is not None:
        claims.append(Claim(field="rating", value=product.rating, text=f"Rated {product.rating} out of 5.", source_tool_call_id=SEARCH_CALL))
    if product.rating_count is not None:
        claims.append(Claim(field="rating_count", value=product.rating_count, text=f"{product.rating_count:,} reviews.", source_tool_call_id=SEARCH_CALL))
    for key, fact in product.spec_facts.items():
        claims.append(Claim(field="spec", key=key, value=fact.value, text=spec_sentence(key, fact), source_tool_call_id=SEARCH_CALL))
    return claims


def mutations(product, category_keys: set[str], rng: random.Random) -> list[tuple[str, Claim]]:
    """(error class, corrupted claim). Every one of these SHOULD be rejected."""
    out: list[tuple[str, Claim]] = []
    price = product.price_inr
    out.append(("price: wrong value", Claim(field="price", value=round(price * 0.9), text=f"Priced at ₹{price:,.0f}.", source_tool_call_id=SEARCH_CALL)))
    out.append(("price: wrong number in the sentence", Claim(field="price", value=price, text=f"Priced at ₹{price * 0.8:,.0f}.", source_tool_call_id=SEARCH_CALL)))
    out.append(("price: cites the wrong tool call", Claim(field="price", value=price, text=f"Priced at ₹{price:,.0f}.", source_tool_call_id=RANK_CALL)))
    out.append(("price: cites a tool call that does not exist", Claim(field="price", value=price, text=f"Priced at ₹{price:,.0f}.", source_tool_call_id="call_999")))
    out.append(("rank: wrong position", Claim(field="rank", value=2, text="Ranked #2 of 3.", source_tool_call_id=RANK_CALL)))
    out.append(("unknown field", Claim(field="warranty", value="2 years", text="Comes with a warranty.", source_tool_call_id=SEARCH_CALL)))
    out.append(("invented number in an otherwise true sentence", Claim(field="price", value=price, text=f"Priced at ₹{price:,.0f}, backed by 987654 buyers.", source_tool_call_id=SEARCH_CALL)))
    if product.rating is not None:
        wrong = round(min(5.0, product.rating + 0.7) if product.rating < 4.3 else product.rating - 0.7, 1)
        out.append(("rating: wrong value", Claim(field="rating", value=wrong, text=f"Rated {product.rating} out of 5.", source_tool_call_id=SEARCH_CALL)))
    for key, fact in product.spec_facts.items():
        label = _label(key)
        if isinstance(fact.value, bool):
            flipped = not fact.value
            text = f"It has {label}." if flipped else f"No {label}."
            out.append(("spec yes/no: flipped value", Claim(field="spec", key=key, value=flipped, text=text, source_tool_call_id=SEARCH_CALL)))
            wrong_wording = f"No {label}." if fact.value else f"It has {label}."
            out.append(("spec yes/no: right value, opposite wording", Claim(field="spec", key=key, value=fact.value, text=wrong_wording, source_tool_call_id=SEARCH_CALL)))
        elif isinstance(fact.value, float):
            wrong = fact.value + max(1.0, round(fact.value * 0.5))
            out.append(("spec number: wrong value", Claim(field="spec", key=key, value=wrong, text=spec_sentence(key, fact), source_tool_call_id=SEARCH_CALL)))
            out.append(("spec number: wrong number in the sentence", Claim(field="spec", key=key, value=fact.value, text=f"{label.capitalize()}: {wrong:g}.", source_tool_call_id=SEARCH_CALL)))
        else:
            out.append(("spec text: wrong value", Claim(field="spec", key=key, value="something else entirely", text=spec_sentence(key, fact), source_tool_call_id=SEARCH_CALL)))
    for key in product.spec_conflicts:
        out.append(("spec the listing contradicts itself about", Claim(field="spec", key=key, value=True, text=f"It has {_label(key)}.", source_tool_call_id=SEARCH_CALL)))
    absent = sorted(category_keys - set(product.spec_facts) - set(product.spec_conflicts))
    for key in rng.sample(absent, min(2, len(absent))):
        out.append(("spec the listing never states", Claim(field="spec", key=key, value=True, text=f"It has {_label(key)}.", source_tool_call_id=SEARCH_CALL)))
    return out


def verify(claim: Claim, product, max_price) -> str | None:
    return verify_claim(claim, product, 1, max_price, CALLS, SEARCH_CALL, RANK_CALL, 3)


def fault_test(snapshot, seed: int = 7) -> dict:
    rng = random.Random(seed)
    keys_by_category = {c: {k for p in snapshot.category(c) for k in p.spec_facts} for c in snapshot.counts}
    true_total = true_rejected = 0
    rejected_examples: Counter = Counter()
    caught: Counter = Counter()
    total: Counter = Counter()
    for product in snapshot.products:
        max_price = math.ceil(product.price_inr * 1.2)
        for claim in true_claims(product, max_price):
            true_total += 1
            reason = verify(claim, product, max_price)
            if reason is not None:
                true_rejected += 1
                rejected_examples[f"{claim.field}:{claim.key or ''} — {reason[:70]}"] += 1
        for name, claim in mutations(product, keys_by_category[product.category], rng):
            total[name] += 1
            if verify(claim, product, max_price) is not None:
                caught[name] += 1
        # a budget claim for a product that IS over budget
        over = Claim(field="within_budget", value=True, text="It is within your budget.", source_tool_call_id=SEARCH_CALL)
        total["within_budget: product is over the budget"] += 1
        if verify(over, product, math.floor(product.price_inr * 0.8)) is not None:
            caught["within_budget: product is over the budget"] += 1
    classes = {name: {"injected": total[name], "caught": caught[name], "caught_pct": pct(caught[name], total[name])} for name in sorted(total)}
    return {
        "products": len(snapshot.products),
        "true_claims": true_total,
        "true_claims_wrongly_rejected": true_rejected,
        "false_reject_pct": pct(true_rejected, true_total),
        "false_reject_examples": rejected_examples.most_common(8),
        "faults_injected": sum(total.values()),
        "faults_caught": sum(caught.values()),
        "faults_caught_pct": pct(sum(caught.values()), sum(total.values())),
        "classes": classes,
    }


# ------------------------------------------------------------------- main


# ------------------------------------------------------- E. replanning


async def replan_one(query: dict) -> dict | None:
    """Follows the agent's replanning loop for one query using the gold intent. None = no replanning needed."""
    gold = query["gold"]
    category = get_snapshot_category(gold["category_slug"])
    if category is None:
        return None  # a category the catalog doesn't cover: nothing to loosen
    snapshot = snapshot_store.load_snapshot()
    brands = snapshot.brands(category)
    intent = ParsedIntent(
        category_slug=gold["category_slug"], category_label=category, max_price=gold["max_price"],
        must_have_attributes=list(gold["must_haves"]), raw_query=query["query"],
    )
    kept, _, _ = filter_by_requirements(await search_products(intent.category_slug, intent.max_price), intent.must_have_attributes, brands)
    if kept:
        return None
    row = {"id": query["id"], "type": query["type"], "steps": [], "rescued": False, "options_existed": False}
    for _ in range(MAX_REPLANS):
        options = build_options(snapshot.category(category), intent, brands)
        if not options:
            break
        row["options_existed"] = True
        option = choose_by_rule(options)
        intent, _ = apply_option(intent, option, category)
        row["steps"].append({
            "kind": option.kind, "products_unlocked": option.products_unlocked,
            "budget_raise_pct": round(100 * (option.new_budget - option.old_budget) / option.old_budget, 1) if option.kind == "raise_budget" else None,
        })
        kept, _, _ = filter_by_requirements(await search_products(intent.category_slug, intent.max_price), intent.must_have_attributes, brands)
        if kept:
            row["rescued"] = True
            row["products_returned"] = len(kept)
            break
    return row


def summarize_replanning(rows: list[dict], total_queries: int) -> dict:
    rescued = [r for r in rows if r["rescued"]]
    steps = [s for r in rows for s in r["steps"]]
    raises = [s["budget_raise_pct"] for s in steps if s["kind"] == "raise_budget"]
    return {
        "queries_checked": total_queries,
        "needed_replanning": len(rows),
        "had_at_least_one_option": sum(1 for r in rows if r["options_existed"]),
        "rescued": len(rescued),
        "rescued_pct_of_needed": pct(len(rescued), len(rows)),
        "not_rescued_ids": [r["id"] for r in rows if not r["rescued"]],
        "steps_by_kind": dict(Counter(s["kind"] for s in steps)),
        "rescued_in_one_step": sum(1 for r in rescued if len(r["steps"]) == 1),
        "budget_raise_pct_median": round(statistics.median(raises), 1) if raises else None,
        "budget_raise_pct_max": max(raises) if raises else None,
        "by_type": {t: {"needed": sum(1 for r in rows if r["type"] == t), "rescued": sum(1 for r in rescued if r["type"] == t)}
                    for t in sorted({r["type"] for r in rows})},
        "note": "Offline: the fixed rule makes the pick. Which option the language model picks is measured by live_eval --set replan.",
    }


async def _replan_all() -> dict:
    out = {}
    for name in ("core", "replan"):
        queries = load_queries(name)
        rows = [r for r in [await replan_one(q) for q in queries] if r is not None]
        out[name] = summarize_replanning(rows, len(queries))
    return out


def main() -> None:
    import os

    os.environ.pop("SERPAPI_ENABLED", None)  # this evaluation must never spend a web search
    assert not serpapi_client.is_enabled()
    snapshot = snapshot_store.load_snapshot(force=True)
    if snapshot is None:
        sys.exit("No snapshot found. Put the five JSON files in backend/data_private/ (or set SNAPSHOT_DIR).")

    queries = load_queries()
    rows = asyncio.run(_run_all(queries))
    results = {
        "snapshot": {"captured_at": snapshot.captured_at, "products": len(snapshot.products), "per_category": snapshot.counts},
        "A_coverage": coverage(snapshot),
        "B_extraction": extraction_check(snapshot),
        "C_queries": summarize_queries(rows),
        "D_verifier_faults": fault_test(snapshot),
        "E_replanning": asyncio.run(_replan_all()),
    }
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "offline_results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    print_report(results)
    print(f"\nSaved: {RESULTS_DIR / 'offline_results.json'}")


async def _run_all(queries):
    return [await run_query(q) for q in queries]


def print_report(r: dict) -> None:
    print("A. COVERAGE (share of products whose listing states the spec clearly)")
    for category, data in r["A_coverage"].items():
        specs = ", ".join(f"{s['label']} {s['stated_pct']:.0f}%" for s in data["specs"].values())
        print(f"  {category}: {data['products']} products / {data['distinct_models']} models; {specs}; self-contradicting: {data['with_any_conflict']}")
    print("\nB. EXTRACTION vs TITLE (RAM)")
    for category, data in r["B_extraction"].items():
        print(f"  {category}: {data['agree']} agree, {data['disagree']} disagree (of {data['title_and_fact_both_present']})")
    c = r["C_queries"]
    print(f"\nC. QUERIES: {c['queries']} total, {c['in_scope']} in scope, {c['answerable']} answerable; empty in scope: {c['empty_in_scope']}")
    print(f"  top-3 slots fully confirmed: {c['top_slots_fully_confirmed_pct']}%  requirement statuses: {c['requirement_pair_status_pct']}")
    print(f"  grouping: {c['grouping']}   review weighting: {c['review_weighting']}")
    d = r["D_verifier_faults"]
    print(f"\nD. VERIFIER FAULT TEST: {d['faults_caught']}/{d['faults_injected']} corrupted claims caught ({d['faults_caught_pct']}%); "
          f"{d['true_claims_wrongly_rejected']}/{d['true_claims']} true claims wrongly rejected ({d['false_reject_pct']}%)")
    for name, v in d["classes"].items():
        print(f"  {name:<52} {v['caught']:>5}/{v['injected']:<5} {v['caught_pct']}%")
    for example, n in d["false_reject_examples"]:
        print(f"  wrongly rejected x{n}: {example}")
    print("\nE. REPLANNING (gold intent; the fixed rule's pick)")
    for name, e in r["E_replanning"].items():
        print(f"  {name} set: {e['needed_replanning']} of {e['queries_checked']} queries needed replanning; rescued {e['rescued']} "
              f"({e['rescued_pct_of_needed']}%), in one step {e['rescued_in_one_step']}; steps {e['steps_by_kind']}; "
              f"budget raise median {e['budget_raise_pct_median']}% max {e['budget_raise_pct_max']}%; not rescued: {e['not_rescued_ids']}")


if __name__ == "__main__":
    main()