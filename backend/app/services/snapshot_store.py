"""
ShopMate AI — Snapshot Store (Phase 4)

Loads the saved Flipkart "snapshot": five JSON files collected once with
the Apify scraper (see the Phase 4 plan), kept in backend/data_private/
(git-ignored, because Flipkart's terms do not allow republishing).

    data_private/earphones.json   smartphones.json   laptops.json
                  running_shoes.json   smartwatches.json

The app searches these saved files instead of the live site: fast, free,
and the same answer every time (which also makes evaluation repeatable).
Every product carries its capture date so the shopper is told how old
the data is.

Settings (all optional, read from .env):
  DATA_SOURCE   "snapshot" (default) or "fakestore" (forces the old toy catalog)
  SNAPSHOT_DIR  folder holding the five files (default: backend/data_private)

If the folder or files are missing, load_snapshot() returns None and the
agent quietly falls back to the Phase 3 FakeStoreAPI catalog — and says so.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from app.normalizers.flipkart import SkipProduct, normalize_flipkart_product
from app.schemas.product import Product

logger = logging.getLogger("uvicorn.error")

SNAPSHOT_FILES: dict[str, str] = {
    "earphones": "earphones.json",
    "smartphones": "smartphones.json",
    "laptops": "laptops.json",
    "running_shoes": "running_shoes.json",
    "smartwatches": "smartwatches.json",
}

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "data_private"  # backend/data_private


@dataclass
class Snapshot:
    products: list[Product]
    captured_at: str | None
    counts: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, dict[str, int]] = field(default_factory=dict)  # category -> reason -> count

    def category(self, category: str) -> list[Product]:
        return [p for p in self.products if p.category == category]

    def brands(self, category: str) -> set[str]:
        return {p.brand.lower() for p in self.category(category) if p.brand}

    @property
    def captured_label(self) -> str:
        return format_date(self.captured_at)


_cache: dict = {"key": None, "snapshot": None}


def format_date(iso: str | None) -> str:
    """'2026-10-08' -> '8 Oct 2026'"""
    if not iso:
        return "an unknown date"
    try:
        parsed = date.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{parsed.day} {parsed.strftime('%b %Y')}"


def data_source() -> str:
    return os.getenv("DATA_SOURCE", "snapshot").strip().lower()


def snapshot_dir() -> Path:
    configured = os.getenv("SNAPSHOT_DIR")
    return Path(configured).expanduser() if configured else DEFAULT_DIR


def reset_cache() -> None:
    _cache.update({"key": None, "snapshot": None})


def _read_file(path: Path, category: str) -> tuple[list[Product], dict[str, int]]:
    products: list[Product] = []
    skipped: dict[str, int] = {}
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        logger.warning("Snapshot file %s could not be read (%s) — skipping it", path.name, error)
        return products, {"file unreadable": 1}

    seen: set[str] = set()
    for record in records if isinstance(records, list) else []:
        try:
            product = normalize_flipkart_product(record, category)
        except SkipProduct as reason:
            skipped[str(reason)] = skipped.get(str(reason), 0) + 1
            continue
        if product.id in seen:
            skipped["duplicate product id"] = skipped.get("duplicate product id", 0) + 1
            continue
        seen.add(product.id)
        products.append(product)
    return products, skipped


def load_snapshot(force: bool = False) -> Snapshot | None:
    """The saved snapshot, or None when it is switched off or no usable file exists. Cached per folder."""
    if data_source() != "snapshot":
        return None

    folder = snapshot_dir()
    if not force and _cache["key"] == str(folder):
        return _cache["snapshot"]

    all_products: list[Product] = []
    counts: dict[str, int] = {}
    skipped: dict[str, dict[str, int]] = {}
    for category, filename in SNAPSHOT_FILES.items():
        path = folder / filename
        if not path.is_file():
            continue
        products, skip_counts = _read_file(path, category)
        all_products.extend(products)
        counts[category] = len(products)
        if skip_counts:
            skipped[category] = skip_counts

    snapshot = None
    if all_products:
        dates = [p.captured_at for p in all_products if p.captured_at]
        snapshot = Snapshot(products=all_products, captured_at=max(dates) if dates else None, counts=counts, skipped=skipped)
        logger.info("Loaded Flipkart snapshot: %s", counts)
    else:
        logger.info("No Flipkart snapshot files found in %s — using the fallback catalog", folder)

    _cache.update({"key": str(folder), "snapshot": snapshot})
    return snapshot


def is_active() -> bool:
    return load_snapshot() is not None


def get_product(product_id: str) -> Product | None:
    snapshot = load_snapshot()
    if snapshot is None:
        return None
    return next((p for p in snapshot.products if p.id == product_id), None)