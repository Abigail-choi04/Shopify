"""
ShopMate AI — Category-Adaptive Ranking Logic (Phase 3, snapshot categories added in Phase 4)

Lookup tables:

1. CATEGORY_ATTRIBUTES — maps a fine-grained category_slug (from the
   planner's parsed intent) to the attributes that matter in that
   category. This is what makes ranking "category-adaptive" instead of
   always sorting by price: headphones care about noise cancellation and
   battery, shoes about materials and fit, etc.

2. SNAPSHOT_CATEGORY_MAP — maps the planner's slug (and common synonyms)
   to one of the five categories collected in the saved Flipkart
   snapshot: earphones, smartphones, laptops, running_shoes, smartwatches.
   A slug that maps to nothing means "the snapshot does not cover this".

3. FAKESTORE_CATEGORY_MAP — the old Phase 3 mapping onto FakeStoreAPI's
   4 categories. It is only used when the snapshot is switched off or
   missing (see app/services/snapshot_store.py).

All tables are deliberately plain Python dicts ("start hardcoded", per
the project's context report).
"""

CATEGORY_ATTRIBUTES: dict[str, list[str]] = {
    "headphones": ["anc", "battery_life", "rating"],
    "smartphone": ["ram", "storage", "battery_life", "rating"],
    "running_shoes": ["cushioning", "breathability", "rating"],
    "laptop": ["ram", "storage", "battery_life", "rating"],
    "backpack": ["capacity", "water_resistance", "rating"],
    "smartwatch": ["battery_life", "sensors", "display", "rating"],
    "kitchen_appliance": ["motor_power", "jar_count", "warranty", "rating"],
}

ATTRIBUTE_LABELS: dict[str, str] = {
    "anc": "ANC",
    "battery_life": "Battery Life",
    "rating": "Rating",
    "cushioning": "Cushioning",
    "breathability": "Breathability",
    "ram": "RAM",
    "storage": "Storage",
    "capacity": "Capacity",
    "water_resistance": "Water Resistance",
    "sensors": "Sensors",
    "display": "Display",
    "motor_power": "Motor Power",
    "jar_count": "Jars",
    "warranty": "Warranty",
}

DEFAULT_ATTRIBUTES = ["rating"]

# Planner slug (or synonym) -> snapshot category. Keys are lower-case with underscores.
SNAPSHOT_CATEGORY_MAP: dict[str, str] = {
    "headphones": "earphones",
    "earphones": "earphones",
    "earbuds": "earphones",
    "headset": "earphones",
    "bluetooth_headset": "earphones",
    "smartphone": "smartphones",
    "smartphones": "smartphones",
    "phone": "smartphones",
    "phones": "smartphones",
    "mobile": "smartphones",
    "mobiles": "smartphones",
    "mobile_phone": "smartphones",
    "laptop": "laptops",
    "laptops": "laptops",
    "notebook": "laptops",
    "running_shoes": "running_shoes",
    "running_shoe": "running_shoes",
    "shoes": "running_shoes",
    "sports_shoes": "running_shoes",
    "sneakers": "running_shoes",
    "smartwatch": "smartwatches",
    "smartwatches": "smartwatches",
    "smart_watch": "smartwatches",
    "watch": "smartwatches",
    "fitness_band": "smartwatches",
}

FAKESTORE_CATEGORY_MAP: dict[str, str] = {
    "headphones": "electronics",
    "smartphone": "electronics",
    "laptop": "electronics",
    "smartwatch": "electronics",
    "running_shoes": "electronics",  # no real footwear in FakeStoreAPI — nearest available bucket
    "backpack": "electronics",  # no real bags in FakeStoreAPI — nearest available bucket
    "kitchen_appliance": "electronics",  # no real kitchen goods in FakeStoreAPI — nearest available bucket
}

DEFAULT_FAKESTORE_CATEGORY = "electronics"

# Words used when a web search has to be phrased for a category (see services/serpapi_client.py).
SEARCH_WORDS: dict[str, str] = {
    "earphones": "earphones",
    "smartphones": "smartphone",
    "laptops": "laptop",
    "running_shoes": "running shoes",
    "smartwatches": "smartwatch",
}

CATEGORY_ICONS: dict[str, str] = {
    "earphones": "🎧",
    "smartphones": "📱",
    "laptops": "💻",
    "running_shoes": "👟",
    "smartwatches": "⌚",
}


def normalize_slug(category_slug: str) -> str:
    return category_slug.strip().lower().replace("-", "_").replace(" ", "_")


def get_ranking_attributes(category_slug: str) -> list[str]:
    """Returns the ranking attribute keys for a given category, or a sane default."""
    return CATEGORY_ATTRIBUTES.get(normalize_slug(category_slug), DEFAULT_ATTRIBUTES)


def get_snapshot_category(category_slug: str) -> str | None:
    """The snapshot category for a planner slug, or None if the snapshot does not cover it."""
    return SNAPSHOT_CATEGORY_MAP.get(normalize_slug(category_slug))


def get_fakestore_category(category_slug: str) -> str:
    """Maps a fine-grained category to the closest real FakeStoreAPI category for searching."""
    return FAKESTORE_CATEGORY_MAP.get(normalize_slug(category_slug), DEFAULT_FAKESTORE_CATEGORY)


def attribute_label(attribute_key: str) -> str:
    """Human-readable label for a comparison-table column header."""
    return ATTRIBUTE_LABELS.get(attribute_key, attribute_key.replace("_", " ").title())