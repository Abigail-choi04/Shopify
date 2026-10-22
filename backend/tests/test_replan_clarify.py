"""
ShopMate AI — tests for replanning (loosening one requirement) and clarifying questions

Run from the backend/ folder:   python -m pytest tests -q
Groq and the exchange-rate service are faked: no internet, no keys.
"""

import asyncio
import json

from conftest import flipkart_record
from fastapi.testclient import TestClient

from app.agent import graph as graph_module
from app.agent import replan
from app.schemas.intent import ParsedIntent
from app.services import currency, snapshot_store


def _phone(pid, ram, price, rating=4.3, count=2000):
    return flipkart_record(
        pid, title=f"Model {pid} ({ram} GB)", price=price, rating=rating, rating_count=count,
        sections={"Specs": {"RAM": f"{ram} GB", "Internal Storage": "128 GB", "Network Type": "5G"}},
    )


def _setup(monkeypatch, slug="smartphone", max_price=None, must_haves=("8GB RAM",), question=None,
           replan_reply=None, within_budget_claims=False):
    """Fakes Groq. replan_reply: what the 'model' answers when asked to choose a relaxation."""

    async def fixed_rate(cur):
        return currency.FxRate("INR", 1.0, "", "native")

    monkeypatch.setattr(currency, "get_rate", fixed_rate)
    graph_module._compiled_graph = None
    calls = {"planner": 0, "replan": 0, "explain": 0, "replan_requests": []}

    async def fake_groq(system, user):
        if "replanning component" in system:  # checked first: "replanning" also contains "planning"
            calls["replan"] += 1
            calls["replan_requests"].append(json.loads(user))
            if isinstance(replan_reply, Exception):
                raise replan_reply
            return replan_reply
        if "planning component" in system:
            calls["planner"] += 1
            return {"category_slug": slug, "category_label": slug.title(), "max_price": max_price,
                    "must_have_attributes": list(must_haves), "clarification_question": question}
        calls["explain"] += 1
        facts = json.loads(user.split("\n\n")[0])
        out = []
        for item in facts["products"]:
            claims = [{"field": "price", "value": item["price"], "text": f"Priced at ₹{item['price']:,.0f}.",
                       "source_tool_call_id": item["fact_call_id"]}]
            if within_budget_claims:
                claims.append({"field": "within_budget", "value": True, "text": "It is within your budget.",
                               "source_tool_call_id": item["fact_call_id"]})
            out.append({"product_id": item["product_id"], "claims": claims})
        return {"products": out}

    monkeypatch.setattr(graph_module, "call_groq_json", fake_groq)
    return calls


def _trace(response):
    return " | ".join(step.text for step in response.trace)


def _intent(max_price=None, must_haves=("8GB RAM",)):
    return ParsedIntent(category_slug="smartphone", category_label="Smartphone", max_price=max_price,
                        must_have_attributes=list(must_haves), raw_query="q")


# ---------------------------------------------------------------- the options (pure logic)


def test_options_are_worked_out_from_the_catalog(write_snapshot):
    write_snapshot({"smartphones": [_phone("A", 4, 9000), _phone("B", 8, 10400), _phone("C", 8, 11000), _phone("D", 4, 15000)]})
    snapshot = snapshot_store.load_snapshot(force=True)
    options = replan.build_options(snapshot.category("smartphones"), _intent(max_price=10000), snapshot.brands("smartphones"))
    by_kind = {o.kind: o for o in options}
    raise_option = by_kind["raise_budget"]
    assert (raise_option.old_budget, raise_option.new_budget, raise_option.products_unlocked) == (10000, 10400, 1)
    drop = by_kind["drop_requirement"]
    assert (drop.requirement, drop.products_unlocked) == ("8GB RAM", 1)  # only A is within ₹10,000


def test_no_budget_raise_offered_beyond_the_cap(write_snapshot):
    write_snapshot({"smartphones": [_phone("A", 4, 9000), _phone("B", 8, 30000)]})
    snapshot = snapshot_store.load_snapshot(force=True)
    options = replan.build_options(snapshot.category("smartphones"), _intent(max_price=10000), snapshot.brands("smartphones"))
    assert [o.kind for o in options] == ["drop_requirement"]  # ₹30,000 is +200%, far past the 50% cap


def test_rule_prefers_small_raise_then_biggest_drop():
    small = replan.RelaxOption("raise_budget", "raise_budget", 2, old_budget=10000, new_budget=11000)
    big = replan.RelaxOption("raise_budget", "raise_budget", 2, old_budget=10000, new_budget=14000)
    drop_a = replan.RelaxOption("drop_requirement_1", "drop_requirement", 3, requirement="a")
    drop_b = replan.RelaxOption("drop_requirement_2", "drop_requirement", 7, requirement="b")
    assert replan.choose_by_rule([drop_a, small, drop_b]) is small
    assert replan.choose_by_rule([big, drop_a, drop_b]) is drop_b
    assert replan.choose_by_rule([big]) is big


def test_model_pick_is_checked():
    options = [replan.RelaxOption("raise_budget", "raise_budget", 1, old_budget=100, new_budget=110),
               replan.RelaxOption("drop_requirement_1", "drop_requirement", 4, requirement="x")]
    assert replan.pick_option({"option_id": "drop_requirement_1"}, options) == (options[1], "model")
    assert replan.pick_option({"option_id": "drop_everything"}, options) == (options[0], "rule")  # not offered
    assert replan.pick_option(None, options) == (options[0], "rule")
    assert replan.pick_option("raise_budget", options) == (options[0], "rule")  # wrong shape


# ---------------------------------------------------------------- the whole agent


def test_model_chooses_budget_raise_and_search_runs_again(monkeypatch, write_snapshot):
    write_snapshot({"smartphones": [_phone("A", 4, 9000), _phone("B", 8, 10400), _phone("C", 8, 11000)]})
    calls = _setup(monkeypatch, max_price=10000, replan_reply={"option_id": "raise_budget"})
    response = asyncio.run(graph_module.run_agent("8GB RAM phone under 10000"))
    assert [p.title for p in response.products] == ["Model B (8 GB)"]
    relaxation = response.relaxations[0]
    assert (relaxation.kind, relaxation.chosenBy, relaxation.oldBudget, relaxation.newBudget) == ("raise_budget", "model", 10000, 10400)
    assert "₹10,400" in relaxation.message
    assert response.parsedIntent.budget == "₹10,000"  # the shopper's own budget is still what's shown
    assert calls["replan"] == 1
    assert 'max_price=10400.0' in _trace(response)  # the second search used the loosened budget
    assert calls["replan_requests"][0]["shopper_request"] == "8GB RAM phone under 10000"


def test_within_budget_claims_use_the_shoppers_budget_not_the_raised_one(monkeypatch, write_snapshot):
    write_snapshot({"smartphones": [_phone("A", 4, 9000), _phone("B", 8, 10400)]})
    _setup(monkeypatch, max_price=10000, replan_reply={"option_id": "raise_budget"}, within_budget_claims=True)
    response = asyncio.run(graph_module.run_agent("8GB RAM phone under 10000"))
    assert response.products and response.products[0].price == 10400
    assert all(c.field != "within_budget" for p in response.products for c in p.claims)
    assert response.verification.claimsDropped >= 1  # "within your budget" was false for ₹10,400 vs ₹10,000


def test_unusable_model_reply_falls_back_to_the_rule(monkeypatch, write_snapshot):
    write_snapshot({"smartphones": [_phone("A", 4, 9000), _phone("B", 8, 10400)]})
    _setup(monkeypatch, max_price=10000, replan_reply=json.JSONDecodeError("bad", "x", 0))
    response = asyncio.run(graph_module.run_agent("8GB RAM phone under 10000"))
    relaxation = response.relaxations[0]
    assert (relaxation.kind, relaxation.chosenBy) == ("raise_budget", "rule")  # +4% counts as a small raise
    assert "fixed rule" in _trace(response)


def test_model_can_choose_to_drop_a_requirement(monkeypatch, write_snapshot):
    write_snapshot({"smartphones": [_phone("A", 4, 9000), _phone("B", 8, 10400)]})
    _setup(monkeypatch, max_price=10000, replan_reply={"option_id": "drop_requirement_1"})
    response = asyncio.run(graph_module.run_agent("8GB RAM phone under 10000"))
    assert [p.title for p in response.products] == ["Model A (4 GB)"]
    assert response.relaxations[0].requirement == "8GB RAM"
    assert "listings of these products say they do not meet it" in response.relaxations[0].message


def test_no_replan_when_products_were_found(monkeypatch, write_snapshot):
    write_snapshot({"smartphones": [_phone("A", 8, 9000)]})
    calls = _setup(monkeypatch, max_price=10000, replan_reply={"option_id": "raise_budget"})
    response = asyncio.run(graph_module.run_agent("8GB RAM phone under 10000"))
    assert len(response.products) == 1 and response.relaxations == [] and calls["replan"] == 0


def test_no_replan_when_nothing_can_be_loosened(monkeypatch, write_snapshot):
    write_snapshot({"smartphones": [_phone("A", 8, 30000)]})
    calls = _setup(monkeypatch, max_price=5000, must_haves=())
    response = asyncio.run(graph_module.run_agent("phone under 5000"))
    assert response.products == [] and response.relaxations == [] and calls["replan"] == 0
    assert "No matching products were found" in _trace(response)


def test_no_replan_for_a_category_the_catalog_does_not_cover(monkeypatch, write_snapshot):
    write_snapshot({"smartphones": [_phone("A", 8, 9000)]})
    calls = _setup(monkeypatch, slug="backpack", must_haves=())
    response = asyncio.run(graph_module.run_agent("a backpack"))
    assert response.products == [] and calls["replan"] == 0
    assert "doesn't cover" in _trace(response)


# ---------------------------------------------------------------- clarifying questions


def test_asks_when_no_kind_of_product_is_named(monkeypatch, write_snapshot):
    write_snapshot({"smartphones": [_phone("A", 8, 9000)]})
    calls = _setup(monkeypatch, slug="other", must_haves=(), question="What kind of product are you looking for?")
    response = asyncio.run(graph_module.run_agent("something for my dad"))
    assert response.clarification == "What kind of product are you looking for?"
    assert response.products == []
    assert "ask_clarifying_question" in _trace(response)
    assert calls["explain"] == 0  # stopped before searching


def test_never_asks_twice(monkeypatch, write_snapshot):
    write_snapshot({"smartphones": [_phone("A", 8, 9000)]})
    _setup(monkeypatch, slug="other", must_haves=(), question="What kind of product?")
    response = asyncio.run(graph_module.run_agent("something for my dad. not sure", allow_clarification=False))
    assert response.clarification is None
    assert "doesn't cover" in _trace(response)


def test_question_ignored_when_a_covered_category_was_found(monkeypatch, write_snapshot):
    write_snapshot({"smartphones": [_phone("A", 8, 9000)]})
    _setup(monkeypatch, question="What budget?")  # the model asked anyway; a missing budget is no reason
    response = asyncio.run(graph_module.run_agent("8GB RAM phone"))
    assert response.clarification is None and len(response.products) == 1


def test_chat_endpoint_passes_allow_clarification(monkeypatch):
    from app.main import app
    from app.routers import chat as chat_router

    seen = {}

    async def fake_run_agent(query, allow_clarification=True):
        seen["args"] = (query, allow_clarification)
        raise RuntimeError("stop here")

    monkeypatch.setattr(chat_router, "run_agent", fake_run_agent)
    client = TestClient(app)
    client.post("/chat", json={"query": "gift. earphones", "allow_clarification": False})
    assert seen["args"] == ("gift. earphones", False)
    client.post("/chat", json={"query": "earphones"})
    assert seen["args"] == ("earphones", True)


# ---------------------------------------------------------------- evaluation support


def test_replan_query_set_loads_and_core_set_is_unchanged():
    from evaluation.common import load_queries

    core = load_queries()
    stress = load_queries("replan")
    assert len(core) == 66
    assert len({q["id"] for q in stress}) == len(stress) == 21
    assert {q["type"] for q in stress} == {"impossible", "unclear", "clear_control"}
    assert not {q["id"] for q in stress} & {q["id"] for q in core}


def test_parse_trace_takes_the_planner_budget_from_the_first_search():
    from app.schemas.agent import TraceStep
    from evaluation import live_eval

    info = live_eval.parse_trace([
        TraceStep(type="action", text='search_products(category="smartphone", max_price=10000.0)', toolCallId="call_002"),
        TraceStep(type="observation", text="No matching products were found: every product in range was left out ..."),
        TraceStep(type="action", text="choose_relaxation(options=[raise_budget, drop_requirement_1])", toolCallId="call_003"),
        TraceStep(type="action", text='search_products(category="smartphone", max_price=10400.0)', toolCallId="call_004"),
    ])
    assert (info["slug"], info["budget"], info["replans"], info["initial_no_match"], info["clarified"]) == ("smartphone", 10000.0, 1, True, False)


def test_summary_counts_replans_and_questions_and_tolerates_old_records():
    from evaluation import live_eval

    planner = {"category_ok": True, "budget_ok": True, "must_have_recall": 1.0, "must_have_precision": 1.0, "intent_exact": True}
    base = {"planner": planner, "seconds": 1.0, "first_draft_claims": 2, "first_draft_failed": 0, "rewritten": False,
            "final_claims_checked": 2, "final_claims_dropped": 0, "data_only_fallback": False}
    records = [
        {**base, "id": "imp-01", "type": "impossible", "products": 2, "initial_no_match": True, "replans": 1,
         "relaxations": [{"kind": "raise_budget", "chosen_by": "model"}], "clarification_asked": False, "gold_in_catalog": True},
        {**base, "id": "unc-01", "type": "unclear", "products": 0, "initial_no_match": False, "replans": 0,
         "relaxations": [], "clarification_asked": True, "gold_in_catalog": False},
        {**base, "id": "ctl-01", "type": "clear_control", "products": 3, "initial_no_match": False, "replans": 0,
         "relaxations": [], "clarification_asked": False, "gold_in_catalog": True},
        {**base, "id": "old-1", "type": "easy", "products": 3},  # saved before replanning existed
    ]
    summary = live_eval.summarize_pipeline(records, "replan")
    assert summary["replanning"]["runs_replanned"] == 1
    assert summary["replanning"]["replanned_runs_ending_with_products"] == 1
    assert summary["replanning"]["chosen_by"] == {"model": 1}
    assert summary["clarification"]["asked_when_no_covered_category_pct"] == 100.0
    assert summary["clarification"]["asked_when_category_covered_false_alarm_pct"] == 0.0
    assert summary["by_type"]["unclear"]["asked_question"] == 1