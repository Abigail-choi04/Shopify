"""
ShopMate AI — tests for the evaluation scripts (evaluation/), so the numbers in the paper come from tested code.

Run from the backend/ folder:   python -m pytest tests -q
"""

import asyncio
import csv

from conftest import flipkart_record

from app.schemas.agent import TraceStep
from evaluation import label_requirements, live_eval, offline_eval
from evaluation.common import load_queries

PHONE = lambda pid, ram, price: flipkart_record(  # noqa: E731
    pid, title=f"Model {pid} ({ram} GB RAM)", price=price, rating=4.3, rating_count=900,
    sections={"S": {"RAM": f"{ram} GB", "Network Type": "5G", "Internal Storage": "128 GB"}},
)


def test_query_set_is_well_formed():
    queries = load_queries()
    assert len(queries) == 66
    assert len({q["id"] for q in queries}) == 66
    for q in queries:
        assert q["query"].strip() and q["type"]
        assert set(q["gold"]) == {"category_slug", "max_price", "must_haves"}
        assert isinstance(q["gold"]["must_haves"], list)


def test_offline_pipeline_and_fault_test_on_a_tiny_snapshot(write_snapshot):
    write_snapshot({"smartphones": [PHONE("A", 8, 15000), PHONE("B", 8, 17000), PHONE("C", 4, 9000)]})
    from app.services import snapshot_store

    snapshot = snapshot_store.load_snapshot()
    row = asyncio.run(offline_eval.run_query({"id": "t", "type": "multi", "gold": {"category_slug": "smartphone", "max_price": 20000, "must_haves": ["8GB RAM"]}}))
    assert (row["in_budget"], row["kept"], row["excluded"], row["top"]) == (3, 2, 1, 2)
    assert row["top_fully_confirmed"] == 2

    out_of_scope = asyncio.run(offline_eval.run_query({"id": "o", "type": "out_of_scope", "gold": {"category_slug": "backpack", "max_price": None, "must_haves": []}}))
    assert out_of_scope["covered"] is False and out_of_scope["top"] == 0

    faults = offline_eval.fault_test(snapshot)
    assert faults["true_claims_wrongly_rejected"] == 0
    assert faults["faults_caught_pct"] >= 95


def test_planner_scoring():
    gold = {"category_slug": "smartphone", "max_price": 25000, "must_haves": ["8GB RAM", "5G"]}
    perfect = live_eval.score_planner(gold, "smartphone", 25000.0, ["8 GB RAM", "5G"])
    assert perfect["intent_exact"] is True
    wrong = live_eval.score_planner(gold, "laptop", None, ["8GB RAM"])
    assert wrong["category_ok"] is False and wrong["budget_ok"] is False
    assert wrong["must_have_recall"] == 0.5 and wrong["must_have_precision"] == 1.0
    both_out = live_eval.score_planner({"category_slug": "backpack", "max_price": None, "must_haves": []}, "kitchen_appliance", None, [])
    assert both_out["category_ok"] is True  # neither is a snapshot category


def test_trace_parsing():
    trace = [
        TraceStep(type="action", text='search_products(category="smartphone", max_price=25000.0)', toolCallId="call_002"),
        TraceStep(type="observation", text="9 of 12 claim(s) verified; 3 failed. Asking for one rewrite."),
    ]
    info = live_eval.parse_trace(trace)
    assert (info["slug"], info["budget"], info["first_checked"], info["first_failed"]) == ("smartphone", 25000.0, 12, 3)
    none_budget = live_eval.parse_trace([TraceStep(type="action", text='search_products(category="laptop", max_price=None)')])
    assert none_budget["budget"] is None


def test_baseline_grounding_and_price_check(write_snapshot):
    write_snapshot({"smartphones": [PHONE("A", 8, 15000)]})

    async def fake_groq(system, user):
        return {"products": [{"name": "Model A (8 GB RAM)", "price_inr": 15500}, {"name": "Totally Invented Phone X1", "price_inr": 9999}]}

    query = {"id": "t", "type": "easy", "query": "phone", "gold": {"category_slug": "smartphone", "max_price": None, "must_haves": []}}
    record = asyncio.run(live_eval.run_baseline_once(query, fake_groq))
    first, second = record["recommendations"]
    assert first["grounded"] is True and first["price_within_10pct"] is True
    assert second["grounded"] is False
    summary = live_eval.summarize_baseline([record])
    assert summary["grounded_in_catalog_pct"] == 50.0


def test_label_scoring(tmp_path):
    def write(name, columns, rows):
        with (tmp_path / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                writer.writerow({column: row.get(column, "") for column in columns})

    statuses = {1: "met", 2: "met", 3: "not_met", 4: "unknown", 5: "not_met"}
    write("label_key.csv", label_requirements.KEY_COLUMNS, [{"pair_id": k, "system_status": v} for k, v in statuses.items()])
    labels_a = {1: "yes", 2: "no", 3: "no", 4: "cannot_tell"}  # pair 5 not labelled yet
    labels_b = {1: "yes", 2: "no", 3: "yes", 4: "cannot_tell"}
    write("labeler_A.csv", label_requirements.LABELER_COLUMNS, [{"pair_id": k, "label": v} for k, v in labels_a.items()])
    write("labeler_B.csv", label_requirements.LABELER_COLUMNS, [{"pair_id": k, "label": v} for k, v in labels_b.items()])
    result = label_requirements.score(tmp_path)
    # pair 3: the two labelers disagree, so it is left out of the reference; 4 pairs are labelled, 3 are in the reference
    assert result["pairs_labeled_by_A"] == 4 and result["pairs_labeled_by_both"] == 4 and result["pairs_in_reference"] == 3
    assert result["met_but_listing_says_no"] == 1 and result["met_total"] == 2
    assert result["overall_agree_pct"] == round(100 * 2 / 3, 1)
    assert result["labelers_raw_agreement_pct"] == 75.0
    assert result["kappa_between_labelers"] is not None


def test_kappa_perfect_and_chance():
    assert label_requirements.kappa(["yes", "no", "cannot_tell"], ["yes", "no", "cannot_tell"]) == 1.0


def test_baseline_matching_is_strict_about_model_numbers():
    titles = ["realme P4 Pro 5G (Midnight Ivy, 256 GB) (8 GB RAM)", "Samsung Galaxy A36 5G (Lavender, 128 GB)", "Mivi Duopods K2 Fast Charging"]
    assert live_eval.match_title("Realme 11 Pro+ 5G (8GB RAM+128GB Storage)", titles)[0] is None
    assert live_eval.match_title("Samsung Galaxy M53 5G", titles)[0] is None
    assert live_eval.match_title("Mivi DuoPods", titles)[0] == titles[2]


def test_rate_limit_helpers():
    text = "RateLimitError: Rate limit reached for model on tokens per day (TPD): Limit 200000. Please try again in 1h2m3.5s."
    assert live_eval.is_rate_limit(text) and live_eval.is_daily_limit(text)
    assert abs(live_eval.wait_seconds(text) - 3723.5) < 0.1
    assert live_eval.wait_seconds("try again in 12.5s") == 12.5
    assert not live_eval.is_daily_limit("Rate limit reached on tokens per minute (TPM). try again in 5s")


def test_live_run_is_resumable_and_stops_on_daily_limit(tmp_path, monkeypatch, write_snapshot):
    write_snapshot({"smartphones": [PHONE("A", 8, 15000)]})
    calls = []

    async def fake_once(query):
        calls.append(query["id"])
        if query["id"] == "q3":
            return {"id": "q3", "type": "easy", "query": "x", "error": "RateLimitError: tokens per day (TPD) try again in 1h"}
        return {"id": query["id"], "type": "easy", "query": "x", "seconds": 1.0}

    monkeypatch.setattr(live_eval, "run_pipeline_once", fake_once)
    import app.services.groq_client  # noqa: F401  (run_all imports it)

    path = tmp_path / "live.jsonl"
    queries = [{"id": f"q{i}", "type": "easy"} for i in range(1, 5)]
    first = asyncio.run(live_eval.run_all(queries, False, 1, 0, path))
    assert [r["id"] for r in first] == ["q1", "q2"] and calls == ["q1", "q2", "q3"]  # stopped at the daily limit, kept what finished
    calls.clear()

    async def fine(query):
        calls.append(query["id"])
        return {"id": query["id"], "type": "easy", "query": "x", "seconds": 1.0}

    monkeypatch.setattr(live_eval, "run_pipeline_once", fine)
    second = asyncio.run(live_eval.run_all(queries, False, 1, 0, path))
    assert calls == ["q3", "q4"] and [r["id"] for r in second] == ["q1", "q2", "q3", "q4"]


def test_saved_file_with_two_records_on_one_line_is_repaired(tmp_path):
    path = tmp_path / "live.jsonl"
    path.write_text('{"id": "a", "repeat": 1}{"id": "b", "repeat": 1}\n{"id": "c", "error": "x"}\n', encoding="utf-8")
    rows = live_eval.load_saved(path)
    assert [r["id"] for r in rows] == ["a", "b"]  # the failed one is dropped
    live_eval.save_all(path, rows)
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2