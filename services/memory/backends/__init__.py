"""Pluggable vector store backends for agent memory."""

from __future__ import annotations

import os


def get_backend():
    """Return the backend module selected by MEMORY_BACKEND env var."""
    name = os.environ.get("MEMORY_BACKEND", "lancedb")

    if name == "lancedb":
        from services.memory.backends import lancedb_backend
        return lancedb_backend
    elif name == "pinecone":
        from services.memory.backends import pinecone_backend
        return pinecone_backend
    else:
        raise ValueError(f"Unknown memory backend: {name}")
