from __future__ import annotations

import sys
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from scripts import memory as cli
from services.api.routers.memory import router
from services.memory import db, server
from tests.test_memory_content import OVERSIZED, PREFIX, content_store as content_store


@pytest.mark.asyncio
async def test_mcp_declares_the_limit_and_both_writers_apply_it_at_real_storage(content_store):
    backend, embeddings = content_store
    tools = {tool.name: tool for tool in await server.mcp.list_tools()}
    for name in ("memory_add", "memory_update"):
        description = tools[name].inputSchema["properties"]["content"]["description"]
        assert "at most 250 whitespace-separated words" in description
        assert "Rewrite oversized drafts" in description and "never pad" in description
    result = await server.mcp.call_tool("memory_add", {"content": OVERSIZED, "repo": "entrypoints", "tags": ["word-limit"]})
    id = result[1]["result"] if isinstance(result, tuple) else result[0].text
    UUID(id)
    assert backend.get_row(id)["text"] == PREFIX
    replacement = OVERSIZED.replace("word0", "changed0", 1)
    await server.mcp.call_tool("memory_update", {"id": id, "content": replacement})
    assert backend.get_row(id)["text"] == PREFIX.replace("word0", "changed0", 1)
    assert embeddings.documents == [PREFIX, PREFIX.replace("word0", "changed0", 1)]


def test_http_edit_returns_the_same_capped_text_given_to_embedding(content_store):
    backend, embeddings = content_store
    id = db.add("Original")
    original_created = backend.get_row(id)["metadata"]["created_at"]
    embeddings.documents.clear()
    app = FastAPI()
    app.include_router(router, prefix="/api/memory")
    with TestClient(app) as client:
        response = client.put(f"/api/memory/{id}", json={"content": OVERSIZED})
    assert response.status_code == 200
    assert response.json()["content"] == backend.get_row(id)["text"] == PREFIX
    assert response.json()["created_at"] == original_created
    assert embeddings.documents == [PREFIX]


@pytest.mark.parametrize("content", ["", " \t\u2003"])
def test_http_invalid_content_is_422_without_changing_or_reembedding_memory(content_store, content):
    backend, embeddings = content_store
    id = db.add("Original")
    before = backend.get_row(id)
    embeddings.documents.clear()
    app = FastAPI()
    app.include_router(router, prefix="/api/memory")
    with TestClient(app) as client:
        response = client.put(f"/api/memory/{id}", json={"content": content})
    assert response.status_code == 422
    assert response.json()["detail"] == "Memory content must be a nonblank string"
    assert backend.get_row(id) == before and embeddings.documents == []


def test_cli_add_uses_the_same_backend_limit_and_reports_the_real_id(content_store, monkeypatch, capsys):
    backend, embeddings = content_store
    monkeypatch.setattr(sys, "argv", ["scripts/memory.py", "add", OVERSIZED, "--repo", "entrypoints"])
    assert cli.main() == 0
    id = capsys.readouterr().out.strip().removeprefix("Added: ")
    UUID(id)
    assert backend.get_row(id)["text"] == PREFIX
    assert embeddings.documents == [PREFIX]
