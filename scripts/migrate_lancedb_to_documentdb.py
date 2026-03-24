#!/usr/bin/env -S .venv/bin/python3
"""Migrate memories from LanceDB to DocumentDB.

Usage:
    DOCUMENTDB_URI='mongodb://...' ./scripts/migrate_lancedb_to_documentdb.py

Preserves existing vector embeddings (no re-embedding needed).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.shared.paths import bootstrap, REPO_ROOT  # noqa: E402
bootstrap()

from scripts.shared.validation import require_env, extract_memory_metadata  # noqa: E402
from services.memory.backends import lancedb_backend  # noqa: E402
from services.memory.backends.documentdb_backend import (  # noqa: E402
    _get_client,
    _get_collection,
    TEXT_KEY,
    EMBEDDING_KEY,
    INDEX_NAME,
)

BATCH_SIZE = 128


def main() -> None:
    require_env("DOCUMENTDB_URI", "Example: DOCUMENTDB_URI='mongodb://user:pass@host:27017/?tls=true&retryWrites=false'")

    # --- Preconditions ---
    print("[1/5] Reading from LanceDB...")
    lancedb_backend.init()
    rows = lancedb_backend.load_all()
    if not rows:
        raise SystemExit("LanceDB has no memories. Nothing to migrate.")
    print(f"  Found {len(rows)} memories")

    print("[2/5] Connecting to DocumentDB...")
    client = _get_client()
    collection = _get_collection()

    existing = collection.count_documents({})
    if existing > 0:
        raise SystemExit(
            f"Target collection already has {existing} documents. "
            "Aborting to prevent duplicates. "
            "Drop the collection first if this is intentional."
        )

    # --- Transform & Insert ---
    print("[3/5] Migrating documents...")
    docs = []
    for row in rows:
        doc = {
            TEXT_KEY: row.get("text", ""),
            EMBEDDING_KEY: row.get("vector", []),
            "id": row.get("id", ""),
            **extract_memory_metadata(row),
        }
        docs.append(doc)

        if len(docs) >= BATCH_SIZE:
            collection.insert_many(docs)
            docs.clear()

    if docs:
        collection.insert_many(docs)

    # --- Create indexes ---
    print("[4/5] Creating indexes...")
    collection.create_index("id", unique=True, name="id_unique")

    from langchain_community.vectorstores.documentdb import (
        DocumentDBSimilarityType,
        DocumentDBVectorSearch,
    )
    from services.memory.db import _get_embeddings

    store = DocumentDBVectorSearch(
        collection=collection,
        embedding=_get_embeddings(),
        index_name=INDEX_NAME,
    )
    if not store.index_exists():
        dims = len(rows[0].get("vector", []))
        assert dims > 0, "First row has no vector data — cannot determine dimensions."
        store.create_index(
            dimensions=dims,
            similarity=DocumentDBSimilarityType.COS,
            m=16,
            ef_construction=64,
        )
        print(f"  Created vector index ({dims} dims, cosine, HNSW)")
    else:
        print("  Vector index already exists")

    # --- Postconditions ---
    print("[5/5] Verifying migration...")
    target_count = collection.count_documents({})
    source_count = len(rows)

    if target_count != source_count:
        raise SystemExit(
            f"ROW COUNT MISMATCH: source={source_count}, target={target_count}. "
            "Investigate before proceeding."
        )

    sample_ids = [r["id"] for r in rows[:3]]
    for sid in sample_ids:
        doc = collection.find_one({"id": sid}, {"_id": 0, EMBEDDING_KEY: 0})
        source = next(r for r in rows if r["id"] == sid)
        assert doc is not None, f"Sample row {sid} not found in target."
        assert doc[TEXT_KEY] == source.get("text", ""), (
            f"Text mismatch for {sid}"
        )

    print(f"  Sample verification passed ({len(sample_ids)} rows compared)")
    print(f"\nMigration complete: {target_count} memories transferred successfully.")
    print("LanceDB store has NOT been deleted — verify before removing it.")


if __name__ == "__main__":
    main()
