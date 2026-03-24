from __future__ import annotations

from typing import Callable

from services.memory.backends import lancedb_backend


def load_source_rows() -> list[dict]:
    lancedb_backend.init()
    rows = lancedb_backend.load_all()
    if not rows:
        raise SystemExit("LanceDB has no memories. Nothing to migrate.")
    return rows


def check_target_empty(count_fn: Callable[[], int], label: str) -> None:
    existing = count_fn()
    if existing > 0:
        raise SystemExit(
            f"Target {label} already has {existing} entries. "
            "Aborting to prevent duplicates. "
            "Clear the target first if this is intentional."
        )


def verify_count(source_count: int, target_count: int) -> None:
    if target_count != source_count:
        raise SystemExit(
            f"COUNT MISMATCH: source={source_count}, target={target_count}. "
            "Investigate before proceeding."
        )


def verify_sample(
    source_rows: list[dict],
    fetch_text: Callable[[str], str | None],
    sample_size: int = 3,
) -> None:
    sample_ids = [r["id"] for r in source_rows[:sample_size]]
    for sid in sample_ids:
        target_text = fetch_text(sid)
        source_text = next(r for r in source_rows if r["id"] == sid).get("text", "")
        assert target_text is not None, f"Sample row {sid} not found in target."
        assert target_text == source_text, f"Text mismatch for {sid}"
    print(f"  Sample verification passed ({len(sample_ids)} rows compared)")


def print_complete(count: int) -> None:
    print(f"\nMigration complete: {count} memories transferred successfully.")
    print("LanceDB store has NOT been deleted — verify before removing it.")
