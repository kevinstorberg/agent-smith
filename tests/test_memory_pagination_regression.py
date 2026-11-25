from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from importlib import reload
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.server.fastmcp.exceptions import ToolError
from langchain_core.documents import Document
from psycopg2.extras import execute_values

from services.api.routers.memory import router
from services.db import get_connection
from services.memory import catalog as listing_catalog, db, server
from services.memory import maintenance
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
        self.upserts = []
        self.deletes = []
        self.opens = 0
        self.forbid_listing = True
        self.forbid_query = False

    def list_paginated(self, **kwargs):
        if self.forbid_listing:
            raise AssertionError("Agent operations must not enumerate the catalog")
        self.pages.append(kwargs)
        return super().list_paginated(**kwargs)

    def query(self, **kwargs):
        if self.forbid_query:
            raise AssertionError("A listing page must not run a vector query")
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

    def upsert(self, vectors, **kwargs):
        vectors = list(vectors)
        self.upserts.append([id for id, _, _ in vectors])
        return super().upsert(vectors, **kwargs)

    def delete(self, *, ids, **kwargs):
        self.deletes.append(list(ids))
        for id in ids:
            self.rows.pop(id, None)


@pytest.fixture
def catalog(monkeypatch):
    index = RecordingIndex()
    index.source = listing_catalog.Source(f"pagination-tests-{uuid4()}")
    monkeypatch.setattr(db, "_embeddings", FakeEmbeddings())
    monkeypatch.setattr(db, "_retriever", None)
    monkeypatch.setattr(db, "get_backend", lambda: pinecone_backend)
    monkeypatch.setattr(pinecone_backend, "INDEX_NAME", index.source.index_name)

    def open_index():
        index.opens += 1
        return index

    monkeypatch.setattr(pinecone_backend, "_get_index", open_index)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def seed(count, *, ready=True):
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
                    "updated_at": (
                        base + timedelta(seconds=count - position)
                    ).isoformat(),
                    "last_accessed_at": stamp,
                    "source_type": "meeting" if position % 7 == 0 else "general",
                    "source_id": str(UUID(int=999999)) if position % 7 == 0 else id,
                },
            }
        if ready:
            with get_connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO memory_catalog_sources (source_key, status) VALUES (%s, 'ready')",
                    (index.source.key,),
                )
                entries = []
                for id, row in index.rows.items():
                    meta = db.catalog_metadata(id, row["metadata"])
                    entries.append(
                        (
                            index.source.key,
                            id,
                            meta["repo"],
                            meta["tags"],
                            meta["source_type"],
                            meta["source_id"],
                            meta["source_id"] if meta["from_meeting"] else None,
                            meta["created_at"],
                            meta["updated_at"],
                        )
                    )
                if entries:
                    execute_values(
                        cursor,
                        """INSERT INTO memory_catalog_entries
                        (source_key, id, repo, tags, source_type, source_id, meeting_id, created_at, updated_at)
                        VALUES %s""",
                        entries,
                        page_size=1000,
                    )
        return index

    yield seed
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM memory_catalog_pending WHERE source_key = %s",
            (index.source.key,),
        )
        cursor.execute(
            "DELETE FROM memory_catalog_entries WHERE source_key = %s",
            (index.source.key,),
        )
        cursor.execute(
            "DELETE FROM memory_catalog_sources WHERE source_key = %s",
            (index.source.key,),
        )


def forbid_listing_hydration(monkeypatch, index):
    index.forbid_query = True

    def forbidden(*args, **kwargs):
        raise AssertionError("A listing page must not initialize or embed the catalog")

    monkeypatch.setattr(db, "_get_retriever", forbidden)
    monkeypatch.setattr(db, "_get_embeddings", forbidden)
    monkeypatch.setattr(pinecone_backend, "load_all", forbidden)


def install_explicit_bulk(monkeypatch, index):
    lifecycle = []

    @contextmanager
    def open_index(source, budget):
        assert source == index.source
        budget.request()
        lifecycle.append("opened")
        try:
            yield index
        finally:
            lifecycle.append("closed")

    monkeypatch.setattr(maintenance, "open_index", open_index)
    return lifecycle


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/api/memory")
    with TestClient(app) as instance:
        yield instance


@pytest.mark.parametrize(
    "sort", ["created_at_asc", "created_at_desc", "updated_at_asc", "updated_at_desc"]
)
def test_explicit_catalog_pages_fetch_only_requested_ids_across_old_ceiling(
    catalog, monkeypatch, sort
):
    index = catalog(10051)
    forbid_listing_hydration(monkeypatch, index)
    ordered = list(index.rows)
    if sort.startswith("updated_at"):
        ordered.reverse()
    if sort.endswith("desc"):
        ordered.reverse()

    for offset, limit in [(0, 10), (10, 10), (10040, 10), (0, 100)]:
        items, total = db.list_page(sort=sort, limit=limit, offset=offset)
        assert total == 10051
        assert [row["id"] for row in items] == ordered[offset : offset + limit]
    assert index.fetches == [
        ordered[:10],
        ordered[10:20],
        ordered[10040:10050],
        ordered[:100],
    ]
    assert index.pages == []
    assert index.queries == index.touches == []
    assert db._retriever is None


def test_explicit_catalog_total_and_offsets_apply_after_all_filters(
    catalog, monkeypatch
):
    index = catalog(10051)
    forbid_listing_hydration(monkeypatch, index)
    expected = [
        id
        for position, id in enumerate(index.rows)
        if position % 3 == position % 5 == position % 7 == 0
    ]
    params = {
        "repo": "project",
        "tags": ["keep"],
        "meeting_only": True,
        "sort": "created_at_asc",
        "limit": 10,
    }

    first, total = db.list_page(**params)
    later, later_total = db.list_page(**params, offset=90)
    assert total == later_total == len(expected)
    assert [row["id"] for row in first] == expected[:10]
    assert [row["id"] for row in later] == expected[90:100]
    assert index.fetches == [expected[:10], expected[90:100]]
    assert index.pages == index.queries == []
    assert index.touches == []


def test_empty_explicit_catalog_page_returns_total_without_opening_provider(
    catalog, monkeypatch
):
    index = catalog(10051)
    forbid_listing_hydration(monkeypatch, index)

    assert db.list_page(limit=10, offset=20000) == ([], 10051)
    assert index.opens == 0
    assert index.fetches == index.pages == index.queries == index.touches == []


def test_missing_explicit_catalog_fails_before_any_provider_call(catalog, monkeypatch):
    index = catalog(3, ready=False)
    forbid_listing_hydration(monkeypatch, index)

    with pytest.raises(listing_catalog.Unavailable):
        db.list_page(limit=10)
    assert index.opens == 0
    assert index.fetches == index.pages == index.queries == index.touches == []


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"sort": "relevance"},
        {"tags": ["too-many"] * 21},
    ],
)
def test_invalid_listing_request_fails_before_sql_or_provider(
    catalog, client, monkeypatch, params
):
    index = catalog(3, ready=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid page must fail before SQL")

    monkeypatch.setattr(listing_catalog, "select_page", forbidden)
    response = client.get("/api/memory/list", params=params)

    assert response.status_code == 422
    assert index.opens == 0


def test_explicit_catalog_generation_change_during_fetch_fails_without_retry(
    catalog, monkeypatch
):
    index = catalog(10051)
    forbid_listing_hydration(monkeypatch, index)
    original_fetch = index.fetch

    def changed_during_fetch(ids, **kwargs):
        result = original_fetch(ids, **kwargs)
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE memory_catalog_sources SET generation = generation + 1 WHERE source_key = %s",
                (index.source.key,),
            )
        return result

    monkeypatch.setattr(index, "fetch", changed_during_fetch)
    with pytest.raises(listing_catalog.Unavailable):
        db.list_page(limit=10)
    assert len(index.fetches) == 1 and len(index.fetches[0]) == 10
    assert index.pages == index.queries == index.touches == []


def test_cold_http_search_queries_fifty_and_touches_only_its_page(catalog, client):
    index = catalog(10051, ready=False)
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
        retriever = db._new_retriever()
        retriever.memory_stream = [
            Document(
                page_content=row["metadata"]["text"], metadata=deepcopy(row["metadata"])
            )
            for row in list(index.rows.values())[60:120]
        ]
        monkeypatch.setattr(db, "_retriever", retriever)
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
    index = catalog(10051, ready=False)
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


def test_pinecone_full_hydration_is_forbidden_before_provider_or_embedding_calls(
    catalog, monkeypatch
):
    index = catalog(3, ready=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("Full hydration must be rejected before I/O")

    monkeypatch.setattr(db, "_get_embeddings", forbidden)
    monkeypatch.setattr(pinecone_backend, "load_all", forbidden)
    with pytest.raises(RuntimeError, match="Full Pinecone hydration is disabled"):
        db._get_retriever()
    assert index.opens == 0


@pytest.mark.asyncio
async def test_mcp_listing_fetches_one_native_page_of_at_most_fifty(
    catalog, monkeypatch
):
    index = catalog(10051)
    index.forbid_listing = False
    forbid_listing_hydration(monkeypatch, index)
    tools = {tool.name: tool for tool in await server.mcp.list_tools()}
    limit_schema = tools["memory_list"].inputSchema["properties"]["limit"]
    assert limit_schema["minimum"] == 1 and limit_schema["maximum"] == 50
    assert limit_schema["default"] == 20

    response = await server.mcp.call_tool("memory_list", {"limit": 50})

    assert len(response[1]["result"]) == 50
    assert len(index.fetches) == 1 and len(index.fetches[0]) == 50
    assert len(index.pages) == 1 and index.pages[0]["limit"] == 50
    assert index.queries == index.touches == []
    with pytest.raises(ToolError):
        await server.mcp.call_tool("memory_list", {"limit": 51})
    assert len(index.fetches) == 1


@pytest.mark.asyncio
async def test_large_configured_default_is_bounded_in_actual_mcp_schema_and_listing(
    catalog, monkeypatch
):
    index = catalog(10051)
    index.forbid_listing = False
    forbid_listing_hydration(monkeypatch, index)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(db, "DEFAULT_LIMIT", 200)
            reload(server)
            tools = {tool.name: tool for tool in await server.mcp.list_tools()}
            for name in ("memory_search", "memory_list"):
                assert tools[name].inputSchema["properties"]["limit"]["default"] == 50
            response = await server.mcp.call_tool("memory_list", {})
            assert len(response[1]["result"]) == 50
    finally:
        reload(server)
    assert len(index.fetches) == 1 and len(index.fetches[0]) == 50


def test_invalid_configured_listing_default_fails_before_sql_or_provider(
    catalog, monkeypatch
):
    index = catalog(3)
    forbid_listing_hydration(monkeypatch, index)

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid page default must fail before SQL")

    monkeypatch.setattr(db, "DEFAULT_LIMIT", 200)
    monkeypatch.setattr(listing_catalog, "select_page", forbidden)
    with pytest.raises(ValueError, match="limit must not exceed 100"):
        db.list_page()
    assert index.opens == 0


def test_acknowledged_writes_keep_listing_counts_filters_and_dates_current(
    catalog, monkeypatch
):
    index = catalog(3)
    monkeypatch.setattr(
        db, "_utcnow", lambda: datetime(2027, 1, 1, tzinfo=timezone.utc)
    )

    id = db.add("A new Python memory", repo="new-project", tags=["before"])
    first, total = db.list_page(limit=10)
    assert total == 4
    assert first[0]["id"] == id

    db.update(id, repo="changed-project", tags=["after"])
    filtered, total = db.list_page(repo="changed-project", tags=["after"])
    assert total == 1
    assert filtered[0]["id"] == id

    db.delete(id.upper())
    after, total = db.list_page(limit=10)
    assert total == 3
    assert id not in {row["id"] for row in after}
    assert index.upserts == [[id], [id]] and index.deletes == [[id]]
    assert index.pages == index.queries == index.touches == []


@pytest.mark.parametrize("ghost_entry", [False, True])
def test_missing_delete_clears_only_its_known_absence_and_keeps_listing_ready(
    catalog, ghost_entry
):
    index = catalog(3)
    id = str(UUID(int=9999999))
    if ghost_entry:
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO memory_catalog_entries(source_key,id) VALUES (%s,%s)",
                (index.source.key, id),
            )

    with pytest.raises(listing_catalog.NoWritePerformed):
        db.delete(id.upper())

    assert listing_catalog.select_page(index.source).total == 3
    assert listing_catalog.pending(index.source) == []
    assert index.fetches == [[id]]
    assert index.deletes == index.upserts == index.pages == index.queries == []


def test_missing_delete_cleanup_failure_remains_dirty(catalog, monkeypatch):
    index = catalog(3)

    def failed_finalize(*args, **kwargs):
        raise listing_catalog.Unavailable("Synthetic cleanup storage failure")

    monkeypatch.setattr(listing_catalog, "finalize", failed_finalize)
    with pytest.raises(
        listing_catalog.Unavailable, match="Synthetic cleanup storage failure"
    ):
        db.delete(str(UUID(int=9999999)))

    assert index.deletes == []
    pending = listing_catalog.pending(index.source)
    assert len(pending) == 1 and pending[0].phase == "acknowledged"
    with pytest.raises(listing_catalog.Unavailable, match="unresolved writes"):
        listing_catalog.select_page(index.source)


def test_recent_job_reads_all_501_qualifying_bodies_in_fifty_row_pages(
    catalog, monkeypatch
):
    from services.graphs.library import improve

    index = catalog(503)
    lifecycle = install_explicit_bulk(monkeypatch, index)
    forbid_listing_hydration(monkeypatch, index)
    ids = list(index.rows)
    now = datetime.now(timezone.utc).isoformat()
    for id in ids[:500]:
        index.rows[id]["metadata"]["updated_at"] = now
    for id in ids[500:502]:
        index.rows[id]["metadata"]["created_at"] = now
    index.rows[ids[500]]["metadata"]["updated_at"] = None
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE memory_catalog_entries SET updated_at=%s WHERE source_key=%s AND id=ANY(%s::uuid[])",
            (now, index.source.key, ids[:500]),
        )
        cursor.execute(
            "UPDATE memory_catalog_entries SET created_at=%s WHERE source_key=%s AND id=ANY(%s::uuid[])",
            (now, index.source.key, ids[500:502]),
        )
        cursor.execute(
            "UPDATE memory_catalog_entries SET updated_at=NULL WHERE source_key=%s AND id=%s",
            (index.source.key, ids[500]),
        )

    entries = improve._recent_memory_entries(None, 7)

    assert len(entries) == 501
    assert {id for id, _ in entries} == set(ids[:501])
    assert [len(batch) for batch in index.fetches] == [50] * 10 + [1]
    assert {id for batch in index.fetches for id in batch} == set(ids[:501])
    assert index.pages == index.queries == index.touches == []
    assert lifecycle == ["opened", "closed"]


def test_explicit_legacy_lookback_reads_last_match_after_500_without_catalog(
    catalog, monkeypatch
):
    index = catalog(503, ready=False)
    index.forbid_listing = False
    forbid_listing_hydration(monkeypatch, index)
    lifecycle = install_explicit_bulk(monkeypatch, index)
    ids = list(index.rows)
    now = datetime.now(timezone.utc)
    for id in ids[:500] + ids[-1:]:
        index.rows[id]["metadata"]["updated_at"] = now.isoformat()
    monkeypatch.setattr(
        listing_catalog,
        "select_page",
        lambda *a, **k: pytest.fail(
            "Uninitialized legacy lookback used catalog entries"
        ),
    )

    rows = list(
        db.iter_recent_memories(
            changed_after=now - timedelta(days=7), max_records=503, max_requests=23
        )
    )

    assert [row["id"] for row in rows] == ids[:500] + ids[-1:]
    assert len(index.pages) == len(index.fetches) == 11
    assert all(page["limit"] == 50 for page in index.pages[:-1])
    assert index.pages[-1]["limit"] == 3
    assert sum(map(len, index.fetches)) == 503
    assert index.queries == index.touches == []
    assert lifecycle == ["opened", "closed"]


@pytest.mark.parametrize("ready", [False, True])
def test_explicit_lookback_rejects_generation_drift_and_closes_client(
    catalog, monkeypatch, ready
):
    index = catalog(3, ready=ready)
    index.forbid_listing = False
    lifecycle = install_explicit_bulk(monkeypatch, index)
    original = index.fetch

    def changed(ids, **kwargs):
        result = original(ids, **kwargs)
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO memory_catalog_sources(source_key) VALUES(%s) ON CONFLICT DO NOTHING",
                (index.source.key,),
            )
            cursor.execute(
                "UPDATE memory_catalog_sources SET generation=generation+1 WHERE source_key=%s",
                (index.source.key,),
            )
        return result

    monkeypatch.setattr(index, "fetch", changed)
    with pytest.raises(listing_catalog.Unavailable, match="changed"):
        list(
            db.iter_recent_memories(
                changed_after=datetime(2020, 1, 1, tzinfo=timezone.utc)
            )
        )
    assert len(index.fetches) == 1
    assert lifecycle == ["opened", "closed"]


@pytest.mark.parametrize("ready", [False, True])
@pytest.mark.parametrize("budgets", [{"max_records": 1}, {"max_requests": 2}])
def test_explicit_lookback_budget_fails_instead_of_returning_partial_corpus(
    catalog, monkeypatch, ready, budgets
):
    index = catalog(3, ready=ready)
    index.forbid_listing = False
    lifecycle = install_explicit_bulk(monkeypatch, index)
    with pytest.raises(maintenance.BudgetExceeded):
        list(
            db.iter_recent_memories(
                changed_after=datetime(2020, 1, 1, tzinfo=timezone.utc),
                batch_size=1,
                **budgets,
            )
        )
    assert lifecycle == ["opened", "closed"]
    assert sum(map(len, index.fetches)) <= budgets.get("max_records", 100000)
    assert len(index.pages) + len(index.fetches) + 1 <= budgets.get(
        "max_requests", 5000
    )
