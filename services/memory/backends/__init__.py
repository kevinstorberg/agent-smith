from __future__ import annotations

import os


def get_backend():
    name = os.environ.get("MEMORY_BACKEND", "lancedb")

    if name == "lancedb":
        from services.memory.backends import lancedb_backend
        return lancedb_backend
    elif name == "pinecone":
        from services.memory.backends import pinecone_backend
        return pinecone_backend
    else:
        raise ValueError(f"Unknown memory backend: {name}")


def build_row(id: str, text: str, metadata: dict) -> dict:
    return {"id": id, "text": text, "metadata": dict(metadata)}
