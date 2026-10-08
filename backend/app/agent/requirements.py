"""
ShopMate AI — Requirement Matching (Phase 4)

Checks a shopper's must-have requirements ("noise cancellation", "8GB
RAM", "5G", "under 1.5 kg") against each product's CHECKED spec facts
(app/normalizers/spec_facts.py). Plain Python rules, not an LLM, so the
result can be trusted and repeated exactly.

Each requirement gets one status per product:
  met          the listing clearly satisfies it
  not_met      the listing clearly does NOT (the product is left out)
  unknown      the listing is silent about it (kept, but shown as unconfirmed)
  conflict     the listing contradicts itself (kept, shown as unconfirmed)
  unsupported  we have no rule for this kind of requirement (kept, unconfirmed)

Only the FIRST matching rule for a requirement is used. Rules are tried
in order, and brand names come last, so "noise cancellation" is never
mistaken for the watch brand "Noise".
"""

import re
from dataclasses import dataclass
from typing import Callable

from app.schemas.product import Product

MET, NOT_MET, UNKNOWN, CONFLICT, UNSUPPORTED = "met", "not_met", "unknown", "conflict", "unsupported"
UNCONFIRMED = {UNKNOWN, CONFLICT, UNSUPPORTED}

LIGHTWEIGHT_LAPTOP_KG = 1.5  # what "lightweight" is taken to mean for laptops (stated in the evidence text)

BRAND_ALIASES = {
    "macbook": "apple", "iphone": "apple", "airpods": "apple", "galaxy": "samsung", "thinkpad": "lenovo",
    "pixel": "google", "redmi": "xiaomi", "airdopes": "boat", "rockerz": "boat",
}


@dataclass(frozen=True)
class RequirementResult:
    requirement: str
    status: str
    spec_key: str | None = None
    evidence: str | None = None  # e.g. "Noise cancellation: Yes"


Rule = Callable[[str, "re.Match[str]", Product], RequirementResult]


def _lookup(product: Product, key: str):
    fact = product.spec_facts.get(key)
    if fact is not None:
        return fact, None
    return None, (CONFLICT if key in product.spec_conflicts else UNKNOWN)


def _result(req: str, status: str, key: str, label: str, fact=None) -> RequirementResult:
    return RequirementResult(req, status, key, f"{label}: {fact.display}" if fact is not None else None)


def bool_rule(key: str, label: str, want: bool = True) -> Rule:
    def run(req, match, product):
        fact, missing = _lookup(product, key)
        if fact is None:
            return _result(req, missing, key, label)
        return _result(req, MET if (fact.value is True) == want else NOT_MET, key, label, fact)
    return run


def min_rule(key: str, label: str, threshold: Callable[["re.Match[str]"], float]) -> Rule:
    def run(req, match, product):
        fact, missing = _lookup(product, key)
        if fact is None or isinstance(fact.value, (bool, str)):
            return _result(req, missing or UNKNOWN, key, label)
        return _result(req, MET if fact.value >= threshold(match) - 1e-9 else NOT_MET, key, label, fact)
    return run


def max_rule(key: str, label: str, threshold: Callable[["re.Match[str]"], float]) -> Rule:
    def run(req, match, product):
        fact, missing = _lookup(product, key)
        if fact is None or isinstance(fact.value, (bool, str)):
            return _result(req, missing or UNKNOWN, key, label)
        return _result(req, MET if fact.value <= threshold(match) + 1e-9 else NOT_MET, key, label, fact)
    return run


def near_rule(key: str, label: str, size: Callable[["re.Match[str]"], float], tolerance: float) -> Rule:
    def run(req, match, product):
        fact, missing = _lookup(product, key)
        if fact is None or isinstance(fact.value, (bool, str)):
            return _result(req, missing or UNKNOWN, key, label)
        return _result(req, MET if abs(fact.value - size(match)) <= tolerance + 1e-9 else NOT_MET, key, label, fact)
    return run


def contains_rule(key: str, label: str, needles: Callable[["re.Match[str]"], list[str]]) -> Rule:
    """Met when the fact's text contains any of the needles (spaces and dashes ignored)."""
    def squash(text: str) -> str:
        return re.sub(r"[\s\-]+", "", text.lower())

    def run(req, match, product):
        fact, missing = _lookup(product, key)
        if fact is None:
            return _result(req, missing, key, label)
        haystack = squash(str(fact.value))
        wanted = [squash(n) for n in needles(match)]
        if key == "processor" and any(re.fullmatch(r"i\d", n) for n in wanted) and re.search(r"core(?:ultra)?\d", haystack) and not any(n in haystack for n in wanted):
            return _result(req, UNKNOWN, key, label, fact)  # Intel's newer "Core 5" naming does not map cleanly onto "i5"
        return _result(req, MET if any(n in haystack for n in wanted) else NOT_MET, key, label, fact)
    return run


def in_rule(key: str, label: str, accepted: set[str]) -> Rule:
    def run(req, match, product):
        fact, missing = _lookup(product, key)
        if fact is None:
            return _result(req, missing, key, label)
        return _result(req, MET if str(fact.value) in accepted else NOT_MET, key, label, fact)
    return run


def equals_rule(key: str, label: str, wanted: str) -> Rule:
    return in_rule(key, label, {wanted})


def _g(index: int = 1) -> Callable[["re.Match[str]"], float]:
    return lambda m: float(m.group(index).replace(",", ""))


def _first_group(m: "re.Match[str]") -> float:
    return next(float(g) for g in m.groups() if g and re.fullmatch(r"\d+(?:\.\d+)?", g))


def _storage_gb(m: "re.Match[str]") -> float:
    groups = [g for g in m.groups() if g]
    number, unit = float(groups[0]), groups[1].lower()
    return number * 1024 if unit == "tb" else number


def _word(m: "re.Match[str]") -> list[str]:
    return [m.group(0).lower()]


RAM = (r"(\d+)\s*gb\s*(?:of\s*)?ram|ram\s*(?:of\s*)?(\d+)\s*gb", min_rule("ram_gb", "RAM", _first_group))
STORAGE = (
    r"(\d+(?:\.\d+)?)\s*(gb|tb)\s*(?:of\s*)?(?:storage|rom|internal)|(?:storage|rom)\s*(?:of\s*)?(\d+(?:\.\d+)?)\s*(gb|tb)",
    min_rule("storage_gb", "Storage", _storage_gb),
)
BATTERY_HOURS = (r"(\d+(?:\.\d+)?)\s*\+?\s*(?:h|hr|hrs|hours?)\b", None)  # filled per category below

RULES: dict[str, list[tuple[str, Rule]]] = {
    "earphones": [
        (r"bluetooth\s*(?:v\s*)?(\d(?:\.\d)?)", min_rule("bluetooth_version", "Bluetooth version", _g())),
        (r"noise[\s-]*cancel|\banc\b", bool_rule("noise_cancellation", "Noise cancellation")),
        (r"true[\s-]*wireless|\btws\b|\bearbuds?\b", bool_rule("true_wireless", "True wireless")),
        (r"\bwired\b", equals_rule("connectivity", "Connectivity", "wired")),
        (r"wireless|bluetooth", equals_rule("connectivity", "Connectivity", "wireless")),
        (BATTERY_HOURS[0], min_rule("battery_hours", "Battery life", _g())),
        (r"sweat", bool_rule("sweat_proof", "Sweat proof")),
        (r"water|splash|\bip[x]?\d", bool_rule("water_resistant", "Water resistant")),
        (r"\bmic(?:rophone)?\b", bool_rule("microphone", "Microphone")),
        (r"fast[\s-]*charg|quick[\s-]*charg|asap", bool_rule("fast_charging", "Fast charging")),
    ],
    "smartphones": [
        RAM,
        STORAGE,
        (r"(\d{4,5})\s*mah", min_rule("battery_mah", "Battery", _g())),
        (r"\b5g\b", bool_rule("network_5g", "5G")),
        (r"(\d+)\s*mp\b.*\b(?:front|selfie)\b|\b(?:front|selfie)\b.*?(\d+)\s*mp\b", min_rule("front_camera_mp", "Front camera", _first_group)),
        (r"(\d+)\s*mp\b", min_rule("rear_camera_mp", "Rear camera", _g())),
        (r"(\d{2,3})\s*hz", min_rule("refresh_rate_hz", "Refresh rate", _g())),
        (r"\bnfc\b", bool_rule("nfc", "NFC")),
        (r"\bamoled\b|\boled\b", bool_rule("amoled", "AMOLED display")),
        (r"fast[\s-]*charg|quick[\s-]*charg", bool_rule("fast_charging", "Fast charging")),
        (r"\bios\b|iphone", contains_rule("os", "Operating system", lambda m: ["ios"])),
        (r"android", contains_rule("os", "Operating system", lambda m: ["android"])),
        (r"(\d(?:\.\d+)?)\s*(?:inch|inches|\")", near_rule("display_inches", "Display", _g(), 0.3)),
    ],
    "laptops": [
        RAM,
        STORAGE,
        (r"\bssd\b", bool_rule("ssd", "SSD storage")),
        (r"touch\s*screen", bool_rule("touchscreen", "Touchscreen")),
        (r"gaming", contains_rule("laptop_type", "Type", lambda m: ["gaming"])),
        (r"chromebook", contains_rule("laptop_type", "Type", lambda m: ["chromebook"])),
        (r"windows", contains_rule("os", "Operating system", lambda m: ["windows"])),
        (r"dedicated\s*graphics|graphics\s*card|\bgpu\b|\brtx\b|\bgtx\b|nvidia", bool_rule("dedicated_graphics", "Dedicated graphics")),
        (r"backlit", bool_rule("backlit_keyboard", "Backlit keyboard")),
        (r"(\d(?:\.\d+)?)\s*kg", max_rule("weight_kg", "Weight", _g())),
        (r"light[\s-]*weight|thin and light", max_rule("weight_kg", f"Weight (lightweight taken as up to {LIGHTWEIGHT_LAPTOP_KG:g} kg)", lambda m: LIGHTWEIGHT_LAPTOP_KG)),
        (r"(\d{2}(?:\.\d)?)\s*(?:inch|inches|\")", near_rule("screen_inches", "Screen", _g(), 0.5)),
        (BATTERY_HOURS[0], min_rule("battery_hours", "Battery life", _g())),
        (
            r"\bi[3579]\b|core\s*(?:ultra\s*)?\d|ryzen\s*\d|snapdragon|apple\s*m\d|\bm[1-4]\b|celeron|pentium",
            contains_rule("processor", "Processor", _word),
        ),
    ],
    "running_shoes": [
        (r"\bmesh\b|\bleather\b|\bcanvas\b|\bfabric\b|\bsynthetic\b|\btextile\b|\bflyknit\b", contains_rule("outer_material", "Outer material", _word)),
        (r"lace|slip[\s-]*on", contains_rule("closure", "Closure", lambda m: [m.group(0)[:4]])),
        (r"\bwomen'?s?\b|\bladies\b|\bfemale\b", in_rule("ideal_for", "Ideal for", {"women", "unisex"})),
        (r"\bmen'?s?\b|\bmale\b", in_rule("ideal_for", "Ideal for", {"men", "unisex"})),
        (r"\beva\b|\brubber\b|\bphylon\b|\bpvc\b|\bpu\b|\btpr\b", contains_rule("sole_material", "Sole", _word)),
        (r"(?:under|below|less than|up\s*to|max(?:imum)?|lighter than)\s*(\d+)\s*g\b", max_rule("weight_g", "Weight (per shoe)", _g())),
    ],
    "smartwatches": [
        (r"\bcall(?:ing|s)?\b", bool_rule("calling", "Calling")),
        (r"\bsim\b|\besim\b|\blte\b", bool_rule("sim", "SIM / LTE")),
        (r"heart[\s-]*rate", bool_rule("heart_rate", "Heart rate monitor")),
        (r"spo2|oxygen", contains_rule("sensors", "Sensors", lambda m: ["spo2", "oxygen"])),
        (r"\bgps\b", bool_rule("gps", "GPS")),
        (r"water|swim|splash|\bip\d+", bool_rule("water_resistant", "Water resistant")),
        (r"\bamoled\b", contains_rule("display_type", "Display type", lambda m: ["amoled"])),
        (r"(\d+)\s*(?:days?|d)\b", min_rule("battery_days", "Battery life", _g())),
        (r"android|\bios\b|iphone", contains_rule("compatible_os", "Compatible with", _word)),
        (r"\bround\b|\bsquare\b|rectang", contains_rule("dial_shape", "Dial shape", lambda m: [m.group(0)[:4]])),
        (r"silicone|leather|metal|steel|nylon", contains_rule("strap_material", "Strap", _word)),
        (r"(\d(?:\.\d+)?)\s*(?:inch|inches|\")", near_rule("display_inches", "Display", _g(), 0.2)),
    ],
}


def _brand_result(requirement: str, product: Product, known_brands: set[str] | None) -> RequirementResult | None:
    text = requirement.lower()
    mentioned = {BRAND_ALIASES[a] for a in BRAND_ALIASES if re.search(rf"\b{re.escape(a)}\b", text)}
    for brand in known_brands or set():
        if re.search(rf"(?<![\w]){re.escape(brand)}(?![\w])", text):
            mentioned.add(brand)
    if not mentioned:
        return None
    if not product.brand:
        return RequirementResult(requirement, UNKNOWN, "brand", None)
    actual = product.brand.lower()
    ok = any(actual == m or actual.startswith(m) or m.startswith(actual) for m in mentioned)
    return RequirementResult(requirement, MET if ok else NOT_MET, "brand", f"Brand: {product.brand}")


def check_requirement(requirement: str, product: Product, known_brands: set[str] | None = None) -> RequirementResult:
    # No spec data at all (toy catalog, web-search results): nothing can be confirmed.
    if not product.spec_facts and not product.spec_conflicts:
        brand = _brand_result(requirement, product, known_brands) if product.brand else None
        return brand or RequirementResult(requirement, UNKNOWN, None, None)

    for pattern, rule in RULES.get(product.category, []):
        match = re.search(pattern, requirement, re.I)
        if match:
            return rule(requirement, match, product)

    brand = _brand_result(requirement, product, known_brands)
    return brand or RequirementResult(requirement, UNSUPPORTED, None, None)


def check_requirements(product: Product, must_haves: list[str], known_brands: set[str] | None = None) -> list[RequirementResult]:
    return [check_requirement(req, product, known_brands) for req in must_haves if req and req.strip()]