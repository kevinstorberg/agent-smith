#!/usr/bin/env -S .venv/bin/python3
"""Migrate memories from LanceDB to DocumentDB.

Usage:
    DOCUMENTDB_URI='mongodb://...' ./scripts/migrate_lancedb_to_documentdb.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.shared.paths import bootstrap  # noqa: E402
bootstrap()

from scripts.shared.validation import require_env, extract_memory_metadata  # noqa: E402
from scripts.shared.migration import (  # noqa: E402
    load_source_rows, check_target_empty, verify_count, verify_sample, print_complete,
)
from services.memory.backends.documentdb_backend import (  # noqa: E402
    _get_client, _get_collection, TEXT_KEY, EMBEDDING_KEY, INDEX_NAME,
)

BATCH_SIZE = 128


def main() -> None:
    require_env("DOCUMENTDB_URI", "Example: DOCUMENTDB_URI='mongodb://user:pass@host:27017/?tls=true&retryWrites=false'")

    print("[1/5] Reading from LanceDB...")
    rows = load_source_rows()
    print(f"  Found {len(rows)} memories")

    print("[2/5] Connecting to DocumentDB...")
    _get_client()
    collection = _get_collection()
    check_target_empty(lambda: collection.count_documents({}), "collection")

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

    print("[4/5] Creating indexes...")
    collection.create_index("id", unique=True, name="id_unique")

    from langchain_community.vectorstores.documentdb import (
        DocumentDBSimilarityType, DocumentDBVectorSearch,
    )
    from services.memory.db import _get_embeddings

    store = DocumentDBVectorSearch(
        collection=collection, embedding=_get_embeddings(), index_name=INDEX_NAME,
    )
    if not store.index_exists():
        dims = len(rows[0].get("vector", []))
        assert dims > 0, "First row has no vector data — cannot determine dimensions."
        store.create_index(
            dimensions=dims, similarity=DocumentDBSimilarityType.COS,
            m=16, ef_construction=64,
        )
        print(f"  Created vector index ({dims} dims, cosine, HNSW)")
    else:
        print("  Vector index already exists")

    print("[5/5] Verifying migration...")
    verify_count(len(rows), collection.count_documents({}))

    def fetch_text(sid: str) -> str | None:
        doc = collection.find_one({"id": sid}, {"_id": 0, EMBEDDING_KEY: 0})
        return doc[TEXT_KEY] if doc else None

    verify_sample(rows, fetch_text)
    print_complete(len(rows))


if __name__ == "__main__":
    main()
