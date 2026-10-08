"""
Shared test setup (no internet, no keys, no real data files needed).

Every test starts with the saved Flipkart snapshot pointed at an EMPTY folder and
SerpAPI switched off, so the older tests keep using the toy catalog and nothing
touches your real data_private folder. Tests that want a snapshot build a tiny
fake one with the `write_snapshot` fixture.
"""

import json

import pytest

from app.services import snapshot_store


@pytest.fixture(autouse=True)
def _isolated_data_sources(monkeypatch, tmp_path):
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "empty_snapshot"))
    monkeypatch.delenv("DATA_SOURCE", raising=False)
    monkeypatch.delenv("SERPAPI_ENABLED", raising=False)
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    snapshot_store.reset_cache()
    yield
    snapshot_store.reset_cache()


def flipkart_record(product_id="ACC1", title="Test Earbuds", price=999, rating=4.2, rating_count=1000, brand="Acme",
                    item_id=None, sections=None, **extra):
    """One record shaped like the Apify Flipkart scrape (only the fields we read)."""
    record = {
        "type": "product", "productId": product_id, "itemId": item_id or f"itm-{product_id}", "title": title, "fullTitle": title,
        "brand": brand, "price": price, "mrp": price * 2 if price else None, "currency": "INR", "inStock": True, "rating": rating,
        "ratingCount": rating_count, "sponsored": False, "image": "https://img/x.jpg", "url": f"https://www.flipkart.com/p/{product_id}",
        "breadcrumb": ["Audio", "Headset", "Earphones", "Wireless Earphones", "True Wireless", "Acme True Wireless"],
        "specifications": sections or {"General": {"Brand": brand}}, "scrapedAt": "2026-10-08T09:16:08.360Z",
    }
    record.update(extra)
    return record


@pytest.fixture
def write_snapshot(tmp_path, monkeypatch):
    """write_snapshot({"earphones": [records...], ...}) -> makes that the active snapshot."""

    def _write(by_category: dict):
        folder = tmp_path / "snapshot"
        folder.mkdir(exist_ok=True)
        for category, records in by_category.items():
            (folder / snapshot_store.SNAPSHOT_FILES[category]).write_text(json.dumps(records), encoding="utf-8")
        monkeypatch.setenv("SNAPSHOT_DIR", str(folder))
        snapshot_store.reset_cache()
        return folder

    return _write