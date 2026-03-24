from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

import services.memory.db as db
import services.memory.backends.lancedb_backend as lancedb_backend
from services.memory.server import mcp


@pytest.fixture(autouse=True)
def isolated_store(tmp_path: Path):
    """Point the memory store at a temp directory and reset caches for every test."""
    store = tmp_path / "store"
    with patch.object(lancedb_backend, "STORE_PATH", store):
        db._embeddings = None
        db._retriever = None
        yield
        db._retriever = None


@pytest.fixture
def client():
    app = mcp.streamable_http_app()
    return TestClient(app, raise_server_exceptions=True)


def test_ui_returns_html(client: TestClient):
    resp = client.get("/ui/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Memory Browser" in resp.text


def test_api_list_empty(client: TestClient):
    db.init()
    resp = client.get("/api/memories")
    assert resp.status_code == 200
    assert resp.json() == []


def test_api_list_with_data(client: TestClient):
    db.add("first memory", repo="r1")
    db.add("second memory", repo="r2")
    resp = client.get("/api/memories")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    contents = {m["content"] for m in data}
    assert "first memory" in contents
    assert "second memory" in contents


def test_api_list_filters_by_repo(client: TestClient):
    db.add("in repo", repo="target")
    db.add("other repo", repo="other")
    resp = client.get("/api/memories?repo=target")
    data = resp.json()
    assert all(m["repo"] == "target" for m in data)


def test_api_search_requires_query(client: TestClient):
    resp = client.get("/api/memories/search")
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_api_search_returns_results(client: TestClient):
    db.add("Python is a programming language")
    db.add("The weather in Paris is sunny")
    resp = client.get("/api/memories/search?q=programming")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1


def test_api_get_found(client: TestClient):
    mem_id = db.add("findable memory", repo="r")
    resp = client.get(f"/api/memories/{mem_id}")
    assert resp.status_code == 200
    assert resp.json()["content"] == "findable memory"


def test_api_get_not_found(client: TestClient):
    db.init()
    resp = client.get("/api/memories/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


def test_api_repos(client: TestClient):
    db.add("a", repo="alpha")
    db.add("b", repo="beta")
    db.add("c", repo="alpha")
    resp = client.get("/api/repos")
    assert resp.status_code == 200
    repos = resp.json()
    assert repos == ["alpha", "beta"]
