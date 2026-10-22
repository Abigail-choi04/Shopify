"""
ShopMate AI — Replanning by loosening one requirement (constraint relaxation)

When the search finds NO product that meets everything the shopper asked for, the agent
does not just stop. It works out which single change would bring back real products, and
picks one:

    raise_budget       raise the budget to the cheapest price at which every requirement is met
                       (only offered if that is at most MAX_BUDGET_RAISE above the shopper's budget)
    drop_requirement   keep the budget, give up ONE must-have (offered once per must-have)

Who decides what:
  - CODE builds the options from the real catalog, so every option is guaranteed to bring
    back at least one product, and each one says exactly how many.
  - The MODEL picks one option (it can judge which requirement the shopper cares about least).
  - CODE checks the pick. If the model's reply is unusable or names an option that wasn't
    offered, a fixed rule decides instead (choose_by_rule below), and the trace says so.

Nothing here invents a product or a price: every number comes from the catalog.
"""

import math
from dataclasses import dataclass, field

from app.agent.tools import filter_by_requirements
from app.schemas.intent import ParsedIntent
from app.schemas.product import Product
from app.services.currency import format_inr

MAX_REPLANS = 2  # at most this many loosening steps per request (each one is a full new search)
MAX_BUDGET_RAISE = 0.5  # never offer a budget more than 50% above what the shopper said
SMALL_BUDGET_RAISE = 0.2  # the fixed rule prefers a raise of up to 20% over dropping a requirement
BUDGET_STEP = 100  # new budgets are rounded up to the next ₹100

RAISE_BUDGET = "raise_budget"
DROP_REQUIREMENT = "drop_requirement"


@dataclass(frozen=True)
class RelaxOption:
    id: str  # e.g. "raise_budget" or "drop_requirement_2"
    kind: str  # RAISE_BUDGET | DROP_REQUIREMENT
    products_unlocked: int  # how many products would come back after this change
    requirement: str | None = None  # the must-have given up (drop_requirement only)
    old_budget: float | None = None
    new_budget: float | None = None

    def describe(self) -> str:
        if self.kind == RAISE_BUDGET:
            raise_pct = round(100 * (self.new_budget - self.old_budget) / self.old_budget)
            return (
                f"raise the budget from {format_inr(self.old_budget)} to {format_inr(self.new_budget)} "
                f"(+{raise_pct}%), keeping every requirement: {self.products_unlocked} product(s) match"
            )
        return f"keep the budget but drop '{self.requirement}': {self.products_unlocked} product(s) match"


@dataclass
class Relaxation:
    """One loosening step that was actually applied."""

    kind: str
    chosen_by: str  # "model" or "rule"
    message: str  # plain sentence for the shopper, built by code (not the model)
    requirement: str | None = None
    old_budget: float | None = None
    new_budget: float | None = None
    products_unlocked: int = 0
    options_offered: list[str] = field(default_factory=list)


def _requirements(intent: ParsedIntent) -> list[str]:
    return [m for m in intent.must_have_attributes if m and m.strip()]


def _within(products: list[Product], budget: float | None) -> list[Product]:
    """Same budget rule as tools.search_products: no rupee price -> kept, not silently dropped."""
    if budget is None:
        return list(products)
    return [p for p in products if p.price_inr is None or p.price_inr <= budget]


def build_options(category_products: list[Product], intent: ParsedIntent, known_brands: set[str] | None) -> list[RelaxOption]:
    """Every single change that would bring back at least one product, worked out from the real catalog."""
    musts = _requirements(intent)
    budget = intent.max_price
    options: list[RelaxOption] = []

    # 1) Raise the budget, keeping every requirement.
    if budget is not None and budget > 0:
        meets_all, _, _ = filter_by_requirements(category_products, musts, known_brands)
        over = sorted(p.price_inr for p in meets_all if p.price_inr is not None and p.price_inr > budget)
        if over and over[0] <= budget * (1 + MAX_BUDGET_RAISE):
            new_budget = float(math.ceil(over[0] / BUDGET_STEP) * BUDGET_STEP)
            unlocked = len(_within(meets_all, new_budget))
            options.append(RelaxOption(RAISE_BUDGET, RAISE_BUDGET, unlocked, old_budget=budget, new_budget=new_budget))

    # 2) Keep the budget, drop one must-have.
    in_budget = _within(category_products, budget)
    for index, requirement in enumerate(musts, start=1):
        rest = [m for m in musts if m != requirement]
        kept, _, _ = filter_by_requirements(in_budget, rest, known_brands)
        if kept:
            options.append(RelaxOption(f"{DROP_REQUIREMENT}_{index}", DROP_REQUIREMENT, len(kept), requirement=requirement))

    return options


def choose_by_rule(options: list[RelaxOption]) -> RelaxOption:
    """
    The fixed rule, used when the model's pick can't be used:
      1. a small budget raise (up to 20%) keeps everything the shopper asked for, so prefer it;
      2. otherwise drop the requirement whose removal brings back the most products;
      3. otherwise the (bigger) budget raise.
    """
    raises = [o for o in options if o.kind == RAISE_BUDGET]
    drops = [o for o in options if o.kind == DROP_REQUIREMENT]
    small = [o for o in raises if o.new_budget <= o.old_budget * (1 + SMALL_BUDGET_RAISE)]
    if small:
        return small[0]
    if drops:
        return max(drops, key=lambda o: o.products_unlocked)
    return raises[0]


def pick_option(reply, options: list[RelaxOption]) -> tuple[RelaxOption, str]:
    """Checks the model's reply. Returns (option, "model") if valid, else (rule's option, "rule")."""
    by_id = {o.id: o for o in options}
    chosen_id = reply.get("option_id") if isinstance(reply, dict) else None
    if isinstance(chosen_id, str) and chosen_id.strip() in by_id:
        return by_id[chosen_id.strip()], "model"
    return choose_by_rule(options), "rule"


def apply_option(intent: ParsedIntent, option: RelaxOption, category_label: str) -> tuple[ParsedIntent, str]:
    """The loosened intent, and the sentence that tells the shopper exactly what was given up."""
    what = category_label.split("—")[-1].strip().lower() or "products"
    if option.kind == RAISE_BUDGET:
        new_intent = intent.model_copy(update={"max_price": option.new_budget})
        message = (
            f"Nothing within {format_inr(option.old_budget)} met all your requirements, so the budget was raised to "
            f"{format_inr(option.new_budget)}. These products cost more than you asked for."
        )
    else:
        remaining = [m for m in intent.must_have_attributes if m != option.requirement]
        new_intent = intent.model_copy(update={"must_have_attributes": remaining})
        budget_part = f" within {format_inr(intent.max_price)}" if intent.max_price is not None else ""
        message = (
            f"No {what}{budget_part} met all your requirements, so '{option.requirement}' was dropped. "
            f"The listings of these products say they do not meet it."
        )
    return new_intent, message