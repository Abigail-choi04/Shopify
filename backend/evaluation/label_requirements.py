"""
ShopMate AI — Human check of requirement matching (BLIND version)

Is the system's "met / not met / couldn't confirm" decision actually right? Only a person
reading the real listing can say. To keep the check fair, the people labelling must NOT see the
system's answer, and the two labellers must work separately.

    python -m evaluation.label_requirements make     # writes labeler_A.csv, labeler_B.csv and label_key.csv
    python -m evaluation.label_requirements score    # reads the filled files back and reports accuracy

`make` picks about 130 (product, requirement) pairs from the 66 evaluation queries (balanced
across the system's five answers) and writes, in data_private/eval/ (git-ignored):
  labeler_A.csv / labeler_B.csv   same pairs, NO system answer. One file per person.
  label_key.csv                   the system's answers. Nobody labelling opens this file.

How to label (fill the `label` column with exactly one of:  yes   no   cannot_tell):
  Read `requirement`, then read `listing_specs` (the raw spec lines of that listing).
  The question is NOT "is this a good product". It is:
      "Does the LISTING clearly say that this product MEETS the requirement?"
  yes          the listing clearly says it does (e.g. requirement '8GB RAM', listing says RAM: 8 GB)
  no           the listing clearly says it does NOT (e.g. listing says RAM: 4 GB)
  cannot_tell  the listing is silent, unclear or contradicts itself
`score` compares the labels with the system, and the two people with each other (Cohen's kappa).
Partly filled files are fine: only rows with a label are counted, and the report says how many.
"""

import asyncio
import csv
import random
import sys
from collections import Counter, defaultdict

from app.agent.ranking import get_snapshot_category
from app.agent.requirements import CONFLICT, MET, NOT_MET, UNKNOWN, UNSUPPORTED, check_requirements
from app.agent.tools import search_products
from app.services import snapshot_store
from evaluation.common import load_queries, private_dir, pct

PER_STATUS = {MET: 40, NOT_MET: 40, UNKNOWN: 30, CONFLICT: 10, UNSUPPORTED: 10}
SYSTEM_TO_LABEL = {MET: "yes", NOT_MET: "no", UNKNOWN: "cannot_tell", CONFLICT: "cannot_tell", UNSUPPORTED: "cannot_tell"}
VALID = {"yes", "no", "cannot_tell"}
LABELER_COLUMNS = ["pair_id", "category", "requirement", "product_title", "listing_specs", "label"]
KEY_COLUMNS = ["pair_id", "system_status", "system_evidence"]


async def collect_pairs() -> dict[str, list[dict]]:
    snapshot = snapshot_store.load_snapshot()
    pool: dict[str, list[dict]] = defaultdict(list)
    for query in load_queries():
        gold = query["gold"]
        category = get_snapshot_category(gold["category_slug"])
        if category is None or not gold["must_haves"]:
            continue
        candidates = await search_products(gold["category_slug"], gold["max_price"])
        for product in candidates:
            for result in check_requirements(product, gold["must_haves"], snapshot.brands(category)):
                pool[result.status].append({"category": category, "requirement": result.requirement, "product": product, "evidence": result.evidence or ""})
    return pool


def specs_text(product) -> str:
    lines = [f"{k}: {v}" for k, v in product.specs.items()]
    return " | ".join(lines)[:900]


def make(seed: int = 11) -> None:
    pool = asyncio.run(collect_pairs())
    rng = random.Random(seed)
    rows, seen = [], set()
    for status, wanted in PER_STATUS.items():
        options = pool.get(status, [])
        rng.shuffle(options)
        taken = 0
        for item in options:
            key = (item["product"].id, item["requirement"])
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "category": item["category"], "requirement": item["requirement"], "product_title": item["product"].title,
                "system_status": status, "system_evidence": item["evidence"], "listing_specs": specs_text(item["product"]),
                "label": "",
            })
            taken += 1
            if taken >= wanted:
                break
    rng.shuffle(rows)  # so the labeler cannot guess from the order
    for index, row in enumerate(rows, 1):
        row["pair_id"] = index
    folder = private_dir()
    for name, columns in (("labeler_A.csv", LABELER_COLUMNS), ("labeler_B.csv", LABELER_COLUMNS), ("label_key.csv", KEY_COLUMNS)):
        with (folder / name).open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    print(f"Wrote {len(rows)} pairs to {folder}: labeler_A.csv, labeler_B.csv (give one each to two people) and label_key.csv (keep closed).")
    print("Available per status:", {s: len(pool.get(s, [])) for s in PER_STATUS})


def kappa(a: list[str], b: list[str]) -> float | None:
    n = len(a)
    if n == 0:
        return None
    observed = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum((ca[k] / n) * (cb[k] / n) for k in VALID)
    return None if expected == 1 else round((observed - expected) / (1 - expected), 3)


def _read(path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _clean(value) -> str:
    return (value or "").strip().lower().replace(" ", "_")


def score(folder=None) -> dict:
    folder = folder or private_dir()
    key = {str(r["pair_id"]): r for r in _read(folder / "label_key.csv")}
    a = {str(r["pair_id"]): _clean(r["label"]) for r in _read(folder / "labeler_A.csv") if _clean(r["label"]) in VALID}
    b_path = folder / "labeler_B.csv"
    b = {str(r["pair_id"]): _clean(r["label"]) for r in _read(b_path) if _clean(r["label"]) in VALID} if b_path.exists() else {}
    if not a:
        sys.exit("No labels found yet. Fill the `label` column of labeler_A.csv with yes / no / cannot_tell.")

    both = [pid for pid in a if pid in b]
    agreed = [pid for pid in both if a[pid] == b[pid]]
    # The reference answer: where two people were asked and agree, that; otherwise labeler A alone.
    reference = {pid: (a[pid] if (pid not in b or a[pid] == b[pid]) else None) for pid in a}
    reference = {pid: label for pid, label in reference.items() if label is not None}

    per_status = {}
    for status in PER_STATUS:
        ids = [pid for pid in reference if key[pid]["system_status"] == status]
        right = sum(1 for pid in ids if reference[pid] == SYSTEM_TO_LABEL[status])
        per_status[status] = {"labeled": len(ids), "agree": right, "agree_pct": pct(right, len(ids))}
    met_ids = [pid for pid in reference if key[pid]["system_status"] == MET]
    not_ids = [pid for pid in reference if key[pid]["system_status"] == NOT_MET]
    unsure_ids = [pid for pid in reference if key[pid]["system_status"] in (UNKNOWN, CONFLICT, UNSUPPORTED)]
    result = {
        "pairs_labeled_by_A": len(a),
        "pairs_labeled_by_both": len(both),
        "pairs_in_reference": len(reference),
        "overall_agree_pct": pct(sum(1 for pid in reference if reference[pid] == SYSTEM_TO_LABEL[key[pid]["system_status"]]), len(reference)),
        "per_system_answer": per_status,
        "met_but_listing_says_no": sum(1 for pid in met_ids if reference[pid] == "no"),
        "met_total": len(met_ids),
        "excluded_but_listing_says_yes": sum(1 for pid in not_ids if reference[pid] == "yes"),
        "excluded_total": len(not_ids),
        "unconfirmed_but_listing_was_clear": sum(1 for pid in unsure_ids if reference[pid] in ("yes", "no")),
        "unconfirmed_total": len(unsure_ids),
        "labelers_raw_agreement_pct": pct(len(agreed), len(both)),
        "kappa_between_labelers": kappa([a[pid] for pid in both], [b[pid] for pid in both]) if both else None,
    }
    for name, value in result.items():
        print(f"{name}: {value}")
    if len(set(a.values())) == 1:
        print("WARNING: labeler A used the same label for every row. Check the instructions in this file's header; the result is probably not meaningful.")
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("make", "score"):
        sys.exit("Usage: python -m evaluation.label_requirements make|score")
    make() if sys.argv[1] == "make" else score()