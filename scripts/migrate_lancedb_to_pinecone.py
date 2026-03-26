#!/usr/bin/env -S .venv/bin/python3
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.shared.paths import bootstrap  # noqa: E402
bootstrap()

from scripts.shared.validation import require_env, extract_memory_metadata  # noqa: E402
from scripts.shared.migration import (  # noqa: E402
    load_source_rows, check_target_empty, verify_count, verify_sample, print_complete,
)
from services.memory.backends import pinecone_backend as pb  # noqa: E402

BATCH_SIZE = 100


def main() -> None:
    require_env("PINECONE_API_KEY", "Sign up at https://pinecone.io for a free API key.")

    print("[1/4] Reading from LanceDB...")
    rows = load_source_rows()
    print(f"  Found {len(rows)} memories")

    print("[2/4] Connecting to Pinecone...")
    pb.init()
    check_target_empty(pb.count, "index")

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

    verify_count(len(rows), pb.count())

    def fetch_text(sid: str) -> str | None:
        vectors = (index.fetch(ids=[sid]).vectors or {})
        if sid not in vectors:
            return None
        return (vectors[sid].metadata or {}).get("text")

    verify_sample(rows, fetch_text)
    print_complete(len(rows))


if __name__ == "__main__":
    main()
