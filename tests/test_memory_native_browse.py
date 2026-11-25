from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.server.fastmcp.exceptions import ToolError
from pinecone.core.openapi.db_data.model.list_item import ListItem
from pinecone.core.openapi.db_data.model.list_response import ListResponse
from pinecone.core.openapi.db_data.model.pagination import Pagination
from pinecone.exceptions import PineconeApiException

from services.api.routers.memory import router
from services.memory import catalog, db, maintenance, server
from services.memory.backends import pinecone_backend as backend
from tests.test_memory_catalog_maintenance import sdk_transport as sdk_transport


def memory_id(number):
    return str(UUID(int=number))


class PageIndex:
    def __init__(self):
        self.calls = []
        self.pages = {
            None: {
                "vectors": [{"id": memory_id(1)}, {"id": memory_id(2)}],
                "pagination": {"next": "second"},
            },
            "second": {
                "vectors": [{"id": memory_id(3)}],
                "pagination": {"next": "empty"},
            },
            "empty": {"vectors": [], "pagination": {"next": "last"}},
            "last": {"vectors": [{"id": memory_id(4)}]},
        }
        self.missing = set()

    def list_paginated(self, **kwargs):
        self.calls.append(("list", kwargs))
        assert kwargs["namespace"] == ""
        assert 0 < kwargs["_request_timeout"] <= 10
        page = self.pages[kwargs["pagination_token"]]
        return deepcopy(page) if isinstance(page, dict) else page

    def fetch(self, ids, **kwargs):
        self.calls.append(("fetch", {"ids": ids, **kwargs}))
        assert kwargs["namespace"] == ""
        assert 0 < kwargs["_request_timeout"] <= 10
        return {
            "vectors": {
                id: {
                    "metadata": {
                        "text": f"Memory {id}",
                        "tags": '["own"]',
                        "last_accessed_at": "2026-01-01T00:00:00Z",
                    }
                }
                for id in reversed(ids)
                if id not in self.missing
            }
        }


@pytest.fixture
def native(monkeypatch):
    index = PageIndex()
    monkeypatch.setattr(db, "get_backend", lambda: backend)
    monkeypatch.setattr(backend, "INDEX_NAME", "native-page-tests")
    monkeypatch.setattr(backend, "_get_index", lambda: index)

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "Native browsing must not access catalog, hydrate, embed, or enumerate"
        )

    monkeypatch.setattr(catalog, "select_page", forbidden)
    monkeypatch.setattr(db, "_get_retriever", forbidden)
    monkeypatch.setattr(db, "_get_embeddings", forbidden)
    monkeypatch.setattr(backend, "load_all", forbidden)
    monkeypatch.setattr(backend, "touch_accessed", forbidden)
    monkeypatch.setattr(maintenance, "iter_rows", forbidden)
    monkeypatch.setattr(maintenance, "open_index", forbidden)
    monkeypatch.setattr(db, "iter_recent_memories", forbidden)
    app = FastAPI()
    app.include_router(router, prefix="/api/memory")
    with TestClient(app) as client:
        yield index, client


def test_native_http_pages_preserve_id_order_cursors_and_access_without_catalog(native):
    index, client = native
    first = client.get("/api/memory/list", params={"limit": 2}).json()
    assert first["mode"] == "cursor" and first["order"] == "id_asc"
    assert "total" not in first
    assert [row["id"] for row in first["items"]] == [memory_id(1), memory_id(2)]
    assert all(
        row["last_accessed_at"] == "2026-01-01T00:00:00+00:00" for row in first["items"]
    )
    assert all(row["tags"] == ["own"] for row in first["items"])

    second = client.get(
        "/api/memory/list", params={"limit": 2, "cursor": first["next_cursor"]}
    ).json()
    empty = client.get(
        "/api/memory/list", params={"limit": 2, "cursor": second["next_cursor"]}
    ).json()
    last = client.get(
        "/api/memory/list", params={"limit": 2, "cursor": empty["next_cursor"]}
    ).json()
    replay = client.get("/api/memory/list", params={"limit": 2}).json()
    assert [row["id"] for row in second["items"]] == [memory_id(3)]
    assert empty["items"] == [] and empty["next_cursor"]
    assert [row["id"] for row in last["items"]] == [memory_id(4)] and last[
        "next_cursor"
    ] is None
    assert replay == first
    assert [kind for kind, _ in index.calls] == [
        "list",
        "fetch",
        "list",
        "fetch",
        "list",
        "list",
        "fetch",
        "list",
        "fetch",
    ]
    assert [call["limit"] for kind, call in index.calls if kind == "list"] == [2] * 5
    assert [
        call["pagination_token"] for kind, call in index.calls if kind == "list"
    ] == [None, "second", "empty", "last", None]


def test_deleted_ids_do_not_trigger_page_fill(native):
    index, client = native
    index.missing = {memory_id(1), memory_id(2)}
    response = client.get("/api/memory/list", params={"limit": 2})
    assert response.status_code == 200
    assert response.json()["items"] == [] and response.json()["next_cursor"]
    assert len(index.calls) == 2


def test_backend_list_rows_also_uses_only_one_bounded_page(native):
    index, _ = native
    assert [row["id"] for row in backend.list_rows(limit=2)] == [
        memory_id(1),
        memory_id(2),
    ]
    with pytest.raises(ValueError, match="memory_search"):
        backend.list_rows(repo="project", limit=2)
    assert len(index.calls) == 2


@pytest.mark.parametrize(
    "params",
    [
        {"repo": "project"},
        {"tags": "own"},
        {"meeting_only": True},
        {"sort": "created_at_desc"},
        {"offset": 1},
        {"cursor": "opaque-but-not-our-format"},
        {"cursor": "x" * (db.BROWSE_CURSOR_MAX_LENGTH + 1)},
        {"limit": 101},
        {"limit": 0},
    ],
)
def test_unsupported_native_requests_fail_before_opening_provider(
    native, monkeypatch, params
):
    _, client = native
    monkeypatch.setattr(
        backend, "_get_index", lambda: pytest.fail("Invalid request opened provider")
    )
    response = client.get("/api/memory/list", params=params)
    assert response.status_code == 422


def test_cross_source_cursor_is_rejected_before_provider(native, monkeypatch):
    _, client = native
    first = client.get("/api/memory/list", params={"limit": 2}).json()
    monkeypatch.setattr(backend, "INDEX_NAME", "changed-source")
    monkeypatch.setattr(
        backend,
        "_get_index",
        lambda: pytest.fail("Wrong-source cursor opened provider"),
    )
    response = client.get(
        "/api/memory/list", params={"limit": 2, "cursor": first["next_cursor"]}
    )
    assert response.status_code == 422 and "restart" in response.json()["detail"]


def test_config_is_local_and_exposes_only_nonsecret_source_identity(
    native, monkeypatch
):
    _, client = native
    monkeypatch.setattr(
        backend, "_get_index", lambda: pytest.fail("Config opened provider")
    )
    response = client.get("/api/memory/config")
    assert response.status_code == 200
    config = response.json()
    assert config["listing"] == {
        "mode": "cursor",
        "filters": False,
        "sort_options": ["id_asc"],
        "total": False,
        "source": db._browse_source_key(catalog.Source("native-page-tests")),
    }
    assert config["search"] == {"max_candidates": 50}
    assert "native-page-tests" not in str(config)


@pytest.mark.parametrize(
    "page",
    [
        {},
        {"vectors": "invalid"},
        {"vectors": [{"id": memory_id(1)}] * 2},
        {"vectors": [{"id": "bad-id"}]},
        {"vectors": [], "pagination": "invalid"},
        {"vectors": [], "pagination": {"next": ""}},
        {"vectors": [], "pagination": {"next": "x" * 8193}},
        {"vectors": [{"id": memory_id(1)}], "namespace": "another-namespace"},
    ],
)
def test_malformed_native_pages_fail_without_following_or_fetching(native, page):
    index, client = native
    index.pages[None] = page
    response = client.get("/api/memory/list", params={"limit": 2})
    assert response.status_code == 503
    assert [kind for kind, _ in index.calls] == ["list"]


def test_sdk_models_are_supported_and_cursor_echo_is_rejected(native):
    index, client = native
    index.pages[None] = ListResponse(
        vectors=[ListItem(id=memory_id(1))], pagination=Pagination(next="second")
    )
    first = client.get("/api/memory/list", params={"limit": 2})
    assert first.status_code == 200
    index.pages["second"] = ListResponse(
        vectors=[], pagination=Pagination(next="second")
    )
    response = client.get(
        "/api/memory/list", params={"limit": 2, "cursor": first.json()["next_cursor"]}
    )
    assert response.status_code == 503
    assert [kind for kind, _ in index.calls] == ["list", "fetch", "list"]


def test_native_deadline_stops_before_fetch(native, monkeypatch):
    index, client = native
    clock = [100.0]
    original = index.list_paginated

    def delayed(**kwargs):
        page = original(**kwargs)
        clock[0] += backend.ACCESS_BATCH_SECONDS
        return page

    monkeypatch.setattr(backend, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(index, "list_paginated", delayed)
    response = client.get("/api/memory/list", params={"limit": 2})
    assert response.status_code == 503
    assert [kind for kind, _ in index.calls] == ["list"]


def test_provider_rejected_cursor_has_explicit_restart_error(native, monkeypatch):
    index, client = native
    token = client.get("/api/memory/list", params={"limit": 2}).json()["next_cursor"]
    monkeypatch.setattr(
        index,
        "list_paginated",
        lambda **kwargs: (_ for _ in ()).throw(PineconeApiException(status=400)),
    )
    response = client.get("/api/memory/list", params={"limit": 2, "cursor": token})
    assert response.status_code == 422 and "restart" in response.json()["detail"]


@pytest.mark.asyncio
async def test_mcp_native_listing_is_first_page_and_rejects_filters_before_io(native):
    index, _ = native
    result = await server.mcp.call_tool("memory_list", {"limit": 2})
    assert [row["id"] for row in result[1]["result"]] == [memory_id(1), memory_id(2)]
    assert len(index.calls) == 2
    for arguments in [
        {"repo": "project"},
        {"tags": ["own"]},
        {"meeting_only": True},
        {"limit": 51},
    ]:
        with pytest.raises(ToolError):
            await server.mcp.call_tool("memory_list", arguments)
    assert len(index.calls) == 2


def test_nonpinecone_capabilities_and_offset_contract_are_preserved(monkeypatch):
    from services.memory.backends import lancedb_backend

    monkeypatch.setattr(db, "get_backend", lambda: lancedb_backend)
    calls = []
    monkeypatch.setattr(
        db,
        "list_page",
        lambda **kwargs: calls.append(kwargs) or ([{"id": "offset-row"}], 42),
    )
    config = db.listing_config()
    assert config["listing"]["mode"] == "offset" and config["listing"]["filters"]
    page = db.browse_page(
        limit=10,
        offset=20,
        repo="project",
        tags=["own"],
        sort="updated_at_desc",
        meeting_only=True,
    )
    assert page == {"mode": "offset", "items": [{"id": "offset-row"}], "total": 42}
    assert calls[0] == {
        "limit": 10,
        "offset": 20,
        "repo": "project",
        "tags": ["own"],
        "sort": "updated_at_desc",
        "meeting_only": True,
    }
    with pytest.raises(ValueError, match="offsets"):
        db.browse_page(limit=10, cursor="unsupported")
    assert len(calls) == 1


def test_real_sdk_native_browse_sets_actual_limits_cursor_namespace_and_zero_retries(
    sdk_transport, monkeypatch
):
    monkeypatch.setattr(backend, "_index", None)
    monkeypatch.setattr(backend, "INDEX_NAME", sdk_transport.state["index"])
    try:
        rows, token = backend.browse_page(limit=2, cursor="provider-token")
        assert [row["id"] for row in rows] == [memory_id(1)] and token is None
        paths = [path for path, _, _ in sdk_transport.calls]
        assert paths == ["/indexes/{index_name}", "/vectors/list", "/vectors/fetch"]
        query = dict(sdk_transport.calls[1][2]["query_params"])
        assert (
            query["limit"] == 2
            and query["paginationToken"] == "provider-token"
            and query["namespace"] == ""
        )
        assert dict(sdk_transport.calls[2][2]["query_params"])["namespace"] == ""
        assert [name for name, _ in sdk_transport.events] == [
            "describe_index",
            "list_paginated",
            "fetch",
        ]
        assert sdk_transport.events[1][1]["count"] == 2
    finally:
        if backend._index is not None:
            backend._index.close()
