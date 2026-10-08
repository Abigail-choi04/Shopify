"""
ShopMate AI — Offline Sample Catalog (fallback for Phase 1/3)

Used ONLY when the live FakeStoreAPI cannot be reached (outage, 5xx,
no internet). The records are hand-written SAMPLE data, not a copy of
FakeStoreAPI's real catalog, written in FakeStoreAPI's raw JSON shape
so they pass through the same normalizer as live data.

Whenever this is used, the agent's trace must say so (see
app/agent/graph.py search_node) — results must never silently pass
off sample data as live data.
"""

OFFLINE_RAW_PRODUCTS: list[dict] = [
    {"id": 9001, "title": "Sample Portable SSD 1TB", "price": 109.0, "description": "Offline sample item.", "category": "electronics", "image": None, "rating": {"rate": 4.6, "count": 420}},
    {"id": 9002, "title": "Sample Internal SSD 512GB", "price": 79.0, "description": "Offline sample item.", "category": "electronics", "image": None, "rating": {"rate": 4.4, "count": 310}},
    {"id": 9003, "title": "Sample 4TB External Hard Drive", "price": 114.0, "description": "Offline sample item.", "category": "electronics", "image": None, "rating": {"rate": 4.1, "count": 205}},
    {"id": 9004, "title": "Sample 24-inch Monitor", "price": 189.0, "description": "Offline sample item.", "category": "electronics", "image": None, "rating": {"rate": 3.8, "count": 150}},
    {"id": 9005, "title": "Sample 27-inch Gaming Monitor", "price": 329.0, "description": "Offline sample item.", "category": "electronics", "image": None, "rating": {"rate": 4.3, "count": 98}},
    {"id": 9006, "title": "Sample Wireless Mouse", "price": 19.0, "description": "Offline sample item.", "category": "electronics", "image": None, "rating": {"rate": 4.0, "count": 760}},
    {"id": 9007, "title": "Sample Men's Cotton Jacket", "price": 55.0, "description": "Offline sample item.", "category": "men's clothing", "image": None, "rating": {"rate": 4.2, "count": 130}},
    {"id": 9008, "title": "Sample Women's Rain Jacket", "price": 40.0, "description": "Offline sample item.", "category": "women's clothing", "image": None, "rating": {"rate": 3.9, "count": 80}},
    {"id": 9009, "title": "Sample Silver Bracelet", "price": 70.0, "description": "Offline sample item.", "category": "jewelery", "image": None, "rating": {"rate": 4.5, "count": 60}},
]