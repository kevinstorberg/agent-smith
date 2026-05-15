from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import services.memory.db as db
import services.memory.backends.lancedb_backend as lancedb_backend


@pytest.fixture(autouse=True)
def isolated_store(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MEMORY_BACKEND", "lancedb")
    store = tmp_path / "store"
    with patch.object(lancedb_backend, "STORE_PATH", store):
        db._embeddings = None
        db._retriever = None
        yield
        db._retriever = None


def _seed(n: int) -> list[str]:
    return [db.add(f"memory number {i}", repo="r", tags=[f"t{i}"]) for i in range(n)]


class TestListPagination:
    def test_list_total_reflects_full_store_count(self):
        _seed(30)
        from services.api.routers.memory import list_all

        result = list_all(repo="", tags=[], sort="", limit=10, offset=0)
        assert result["total"] == 30
        assert len(result["items"]) == 10

    def test_list_offset_returns_different_items(self):
        _seed(30)
        from services.api.routers.memory import list_all

        page1 = list_all(repo="", tags=[], sort="", limit=10, offset=0)
        page3 = list_all(repo="", tags=[], sort="", limit=10, offset=20)
        ids_page1 = {m["id"] for m in page1["items"]}
        ids_page3 = {m["id"] for m in page3["items"]}
        assert ids_page1.isdisjoint(ids_page3)
        assert len(page3["items"]) == 10


class TestListFilters:
    def test_list_forwards_tags_query_param(self):
        db.add("both", tags=["a", "b"])
        db.add("only a", tags=["a"])
        from services.api.routers.memory import list_all

        result = list_all(repo="", tags=["a", "b"], sort="", limit=10, offset=0)
        assert result["total"] == 1
        assert result["items"][0]["content"] == "both"

    def test_list_forwards_sort_query_param(self):
        ids = [db.add(f"m{i}") for i in range(3)]
        from services.api.routers.memory import list_all

        result = list_all(repo="", tags=[], sort="created_at_asc", limit=10, offset=0)
        assert [m["id"] for m in result["items"]] == ids


class TestSearchFilters:
    def test_search_forwards_tags_and_sort(self):
        a_b = db.add("findme alpha", tags=["a", "b"])
        db.add("findme alpha", tags=["a"])
        db.add("findme alpha", tags=["b"])
        from services.api.routers.memory import search_memories

        tagged = search_memories(q="findme", repo="", tags=["a", "b"], sort="", limit=10, offset=0)
        ids = [m["id"] for m in tagged["items"]]
        assert ids == [a_b]

        c1 = db.add("orderable item one")
        c2 = db.add("orderable item two")
        sorted_result = search_memories(
            q="orderable", repo="", tags=[], sort="created_at_asc", limit=10, offset=0
        )
        returned = [m["id"] for m in sorted_result["items"] if m["id"] in (c1, c2)]
        assert returned == [c1, c2]
