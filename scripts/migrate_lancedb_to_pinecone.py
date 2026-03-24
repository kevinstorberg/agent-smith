#!/usr/bin/env -S .venv/bin/python3
"""Migrate memories from LanceDB to Pinecone.

Usage:
    PINECONE_API_KEY='...' ./scripts/migrate_lancedb_to_pinecone.py

Preserves existing vector embeddings (no re-embedding needed).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.shared.paths import bootstrap, REPO_ROOT  # noqa: E402
bootstrap()

from scripts.shared.validation import require_env, extract_memory_metadata  # noqa: E402
from services.memory.backends import lancedb_backend  # noqa: E402
from services.memory.backends import pinecone_backend as pb  # noqa: E402

BATCH_SIZE = 100


def main() -> None:
    require_env("PINECONE_API_KEY", "Sign up at https://pinecone.io for a free API key.")

    print("[1/4] Reading from LanceDB...")
    lancedb_backend.init()
    rows = lancedb_backend.load_all()
    if not rows:
        raise SystemExit("LanceDB has no memories. Nothing to migrate.")
    print(f"  Found {len(rows)} memories")

    print("[2/4] Connecting to Pinecone...")
    pb.init()
    existing = pb.count()
    if existing > 0:
        raise SystemExit(
            f"Pinecone index already has {existing} vectors. "
            "Aborting to prevent duplicates. "
            "Delete the index first if this is intentional."
        )

    print("[3/4] Migrating vectors...")
    index = pb._get_index()
    batch = []

    for row in rows:
        vector = row.get("vector", [])
        if not vector:
            print(f"  WARNING: skipping {row['id']} — no vector data")
            continue

        pinecone_meta = {"text": row.get("text", ""), **extract_memory_metadata(row)}
        batch.append((row["id"], vector, pinecone_meta))

        if len(batch) >= BATCH_SIZE:
            index.upsert(vectors=batch)
            batch.clear()

    if batch:
        index.upsert(vectors=batch)

    print("[4/4] Verifying migration...")
    time.sleep(2)

    target_count = pb.count()
    source_count = len(rows)

    if target_count != source_count:
        raise SystemExit(
            f"COUNT MISMATCH: source={source_count}, target={target_count}. "
            "Pinecone indexing may still be in progress — wait and check again."
        )

    sample_ids = [r["id"] for r in rows[:3]]
    for sid in sample_ids:
        result = index.fetch(ids=[sid])
        vectors = result.vectors
        assert sid in vectors, f"Sample row {sid} not found in Pinecone."
        meta = vectors[sid].metadata or {}
        source = next(r for r in rows if r["id"] == sid)
        assert meta.get("text") == source.get("text", ""), f"Text mismatch for {sid}"

    print(f"  Sample verification passed ({len(sample_ids)} rows compared)")
    print(f"\nMigration complete: {target_count} memories transferred successfully.")
    print("LanceDB store has NOT been deleted — verify before removing it.")


if __name__ == "__main__":
    main()
