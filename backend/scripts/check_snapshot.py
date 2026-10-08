"""
ShopMate AI — Snapshot Health Check (Phase 4)

Run from the backend folder:
    python -m scripts.check_snapshot

Prints, for each of the five categories: how many products loaded, how many
were skipped (and why), and how many products have each key spec fact.
Use it to confirm your five Apify files are in backend/data_private/ and read correctly.
"""

from app.normalizers.spec_facts import COMPARISON_SPECS
from app.services import snapshot_store


def main() -> None:
    snapshot = snapshot_store.load_snapshot(force=True)
    print(f"Folder: {snapshot_store.snapshot_dir()}")
    if snapshot is None:
        print("No snapshot loaded. Check DATA_SOURCE (must be 'snapshot') and that the five .json files are in the folder.")
        print("Expected files:", ", ".join(snapshot_store.SNAPSHOT_FILES.values()))
        return

    print(f"Captured: {snapshot.captured_label}   Total products: {len(snapshot.products)}\n")
    for category, filename in snapshot_store.SNAPSHOT_FILES.items():
        products = snapshot.category(category)
        if not products:
            print(f"[MISSING] {category}: {filename} not found or empty\n")
            continue
        skipped = snapshot.skipped.get(category, {})
        skipped_text = ", ".join(f"{n} {reason}" for reason, n in skipped.items()) or "none"
        models = len({p.group_id for p in products})
        print(f"{category}: {len(products)} products ({models} distinct models); skipped: {skipped_text}")
        conflicts = sum(1 for p in products if p.spec_conflicts)
        for key, label in COMPARISON_SPECS.get(category, []):
            have = sum(1 for p in products if key in p.spec_facts)
            print(f"    {label:<24} {have:>3}/{len(products)} ({have * 100 // len(products)}%)")
        print(f"    products with a spec conflict: {conflicts}\n")


if __name__ == "__main__":
    main()