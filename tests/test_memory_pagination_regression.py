from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.server.fastmcp.exceptions import ToolError

from services.api.routers.memory import router
from services.memory import db, server
from services.memory.backends import pinecone_backend
from tests.test_memory_content import SyntheticPineconeIndex
from tests.test_pgvector_backend import FakeEmbeddings


class RecordingIndex(SyntheticPineconeIndex):
    def __init__(self):
        super().__init__()
        self.pages = []
        self.queries = []
        self.fetches = []
        self.touches = []
        self.forbid_listing = False

    def list_paginated(self, **kwargs):
        if self.forbid_listing:
            raise AssertionError("Agent operations must not enumerate the catalog")
        self.pages.append(kwargs)
        return super().list_paginated(**kwargs)

    def query(self, **kwargs):
        self.queries.append(kwargs)
        return {
            "matches": [
                {
                    "id": id,
                    "score": 1 - position / 100,
                    "metadata": deepcopy(row["metadata"]),
                }
                for position, (id, row) in enumerate(
                    list(self.rows.items())[: kwargs["top_k"]]
                )
            ]
        }

    def fetch(self, ids, **kwargs):
        self.fetches.append(list(ids))
        return super().fetch(ids, **kwargs)

    def update(self, *, id, set_metadata, **kwargs):
        self.touches.append(id)
        self.rows[id]["metadata"].update(set_metadata)


@pytest.fixture
def catalog(monkeypatch):
    index = RecordingIndex()
    monkeypatch.setattr(db, "_embeddings", FakeEmbeddings())
    monkeypatch.setattr(db, "_retriever", None)
    monkeypatch.setattr(db, "get_backend", lambda: pinecone_backend)
    monkeypatch.setattr(pinecone_backend, "_get_index", lambda: index)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def seed(count):
        for position in range(count):
            id = str(UUID(int=position + 1))
            stamp = (base + timedelta(seconds=position)).isoformat()
            index.rows[id] = {
                "values": [0.0],
                "metadata": {
                    "id": id,
                    "text": f"Synthetic memory {position}",
                    "repo": "project" if position % 3 == 0 else "other",
                    "tags": '["keep"]' if position % 5 == 0 else "[]",
                    "created_at": stamp,
                    "updated_at": stamp,
                    "last_accessed_at": stamp,
                    "source_type": "meeting" if position % 7 == 0 else "general",
                    "source_id": str(UUID(int=999999)) if position % 7 == 0 else id,
                },
            }
        return index

    return seed


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/api/memory")
    with TestClient(app) as instance:
        yield instance


@pytest.mark.parametrize(
    "sort", ["created_at_asc", "created_at_desc", "updated_at_asc", "updated_at_desc"]
)
def test_http_pages_cross_old_ceiling_without_reenumerating(catalog, client, sort):
    index = catalog(10051)
    ordered = list(index.rows)
    if sort.endswith("desc"):
        ordered.reverse()

    first = client.get(
        "/api/memory/list", params={"sort": sort, "limit": 10, "offset": 0}
    )
    assert first.status_code == 200
    assert first.json()["total"] == 10051
    assert [row["id"] for row in first.json()["items"]] == ordered[:10]
    assert len(index.pages) == 101
    index.forbid_listing = True

    last = client.get(
        "/api/memory/list", params={"sort": sort, "limit": 10, "offset": 10040}
    )
    assert last.status_code == 200
    assert last.json()["total"] == 10051
    assert [row["id"] for row in last.json()["items"]] == ordered[10040:10050]
    assert len(index.pages) == 101
    assert index.queries == index.touches == []


def test_http_page_total_and_offsets_apply_after_all_filters(catalog, client):
    index = catalog(10051)
    expected = [
        id
        for position, id in enumerate(index.rows)
        if position % 3 == position % 5 == position % 7 == 0
    ]
    params = {
        "repo": "project",
        "tags": "keep",
        "meeting_only": "true",
        "sort": "created_at_asc",
        "limit": 10,
    }

    first = client.get("/api/memory/list", params=params)
    later = client.get("/api/memory/list", params={**params, "offset": 90})

    assert first.status_code == later.status_code == 200
    assert first.json()["total"] == later.json()["total"] == len(expected)
    assert [row["id"] for row in first.json()["items"]] == expected[:10]
    assert [row["id"] for row in later.json()["items"]] == expected[90:100]
    assert len(index.pages) == 101
    assert index.touches == []


def test_cold_http_search_queries_fifty_and_touches_only_its_page(catalog, client):
    index = catalog(10051)
    index.forbid_listing = True

    response = client.get(
        "/api/memory/search",
        params={"q": "synthetic", "sort": "created_at_asc", "limit": 10, "offset": 40},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 50
    assert [row["id"] for row in payload["items"]] == list(index.rows)[40:50]
    assert len(index.queries) == 1 and index.queries[0]["top_k"] == 50
    assert len(index.fetches[0]) == 50
    assert set(index.touches) == set(list(index.rows)[40:50])
    assert db._retriever is None

    beyond = client.get(
        "/api/memory/search", params={"q": "synthetic", "limit": 100, "offset": 50}
    )
    assert beyond.status_code == 200 and beyond.json() == {"items": [], "total": 50}
    assert len(index.touches) == 10
    assert all(query["top_k"] == 50 for query in index.queries)


@pytest.mark.parametrize("warm_catalog", [False, True])
def test_search_caps_overlong_provider_results_before_fetch(
    catalog, monkeypatch, warm_catalog
):
    index = catalog(10051)
    if warm_catalog:
        db.list_page(limit=1)
    index.forbid_listing = True
    index.fetches.clear()
    original = index.query

    def oversized_query(**kwargs):
        response = original(**kwargs)
        response["matches"].extend(
            {"id": id, "score": 0.1, "metadata": deepcopy(row["metadata"])}
            for id, row in list(index.rows.items())[50:60]
        )
        return response

    monkeypatch.setattr(index, "query", oversized_query)
    rows, total = db.search_page("synthetic", limit=100)

    assert len(rows) == total == 50
    assert {row["id"] for row in rows} == set(list(index.rows)[:50])
    assert index.queries[0]["top_k"] == 50
    assert index.fetches[0] == list(index.rows)[:50]


@pytest.mark.asyncio
async def test_cold_mcp_search_schema_and_actual_results_are_bounded(catalog):
    index = catalog(10051)
    index.forbid_listing = True
    tools = {tool.name: tool for tool in await server.mcp.list_tools()}
    limit_schema = tools["memory_search"].inputSchema["properties"]["limit"]
    assert limit_schema["minimum"] == 1 and limit_schema["maximum"] == 50
    assert limit_schema["default"] == 20

    response = await server.mcp.call_tool(
        "memory_search", {"query": "synthetic", "limit": 50}
    )
    rows = response[1]["result"]

    assert len(rows) == 50
    assert {row["id"] for row in rows} == set(list(index.rows)[:50])
    assert len(index.queries) == 1 and index.queries[0]["top_k"] == 50
    assert db._retriever is None
    with pytest.raises(ToolError):
        await server.mcp.call_tool("memory_search", {"query": "synthetic", "limit": 51})
    assert len(index.queries) == 1
