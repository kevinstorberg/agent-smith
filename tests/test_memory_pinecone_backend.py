"""Pinecone load_all reads every memory through one top_k-capped query."""
from __future__ import annotations

import pytest

import services.memory.backends.pinecone_backend as pinecone_backend


class _FakeIndex:
    def __init__(self, match_count: int):
        self.match_count = match_count

    def query(self, **kwargs):
        return {"matches": [{"id": f"m{i}", "metadata": {"text": f"memory {i}"}} for i in range(self.match_count)]}


def test_load_all_returns_every_match_below_the_ceiling(monkeypatch):
    monkeypatch.setattr(pinecone_backend, "_get_index", lambda: _FakeIndex(3))

    assert [row["text"] for row in pinecone_backend.load_all()] == ["memory 0", "memory 1", "memory 2"]


def test_load_all_refuses_to_truncate_at_the_query_ceiling(monkeypatch):
    monkeypatch.setattr(pinecone_backend, "_get_index", lambda: _FakeIndex(pinecone_backend.LOAD_ALL_CEILING))

    with pytest.raises(RuntimeError, match="ceiling"):
        pinecone_backend.load_all()
