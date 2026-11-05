from __future__ import annotations

import sys
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.server.fastmcp.exceptions import ToolError

from scripts import memory as cli
from services.api.routers.memory import router
from services.memory import db, server
from tests.embedding_fakes import FakeEmbeddingClient
from tests.test_memory_content import OVERSIZED, content_store as content_store


@pytest.mark.asyncio
async def test_mcp_declares_the_native_embedding_limit():
    tools = {tool.name: tool for tool in await server.mcp.list_tools()}
    for name in ("memory_add", "memory_update"):
        description = tools[name].inputSchema["properties"]["content"]["description"]
        assert "256 total embedding tokens" in description
        assert "Rewrite oversized drafts" in description and "never pad" in description


@pytest.mark.asyncio
async def test_mcp_agent_writes_reject_oversize_then_accept_complete_revisions(
    content_store,
):
    backend, embeddings = content_store
    with pytest.raises(ToolError) as rejected:
        await server.mcp.call_tool("memory_add", {"content": OVERSIZED})
    assert "254" in str(rejected.value) and "256" in str(rejected.value)
    assert backend.load_all() == [] and embeddings.documents == []
    revised = "A complete supported fact with its scope."
    result = await server.mcp.call_tool(
        "memory_add",
        {"content": revised, "repo": "entrypoints", "tags": ["token-limit"]},
    )
    id = result[1]["result"] if isinstance(result, tuple) else result[0].text
    UUID(id)
    before = backend.get_row(id)
    assert before["text"] == revised
    with pytest.raises(ToolError):
        await server.mcp.call_tool("memory_update", {"id": id, "content": OVERSIZED})
    assert backend.get_row(id) == before and embeddings.documents == [revised]
    replacement = "A revised complete fact preserving its identifiers."
    await server.mcp.call_tool("memory_update", {"id": id, "content": replacement})
    assert backend.get_row(id)["text"] == replacement
    assert embeddings.documents == [revised, replacement]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["add", "update"])
async def test_mcp_configuration_drift_rejects_instead_of_silently_rewriting_an_accepted_draft(
    content_store, monkeypatch, operation
):
    backend, model = content_store
    id = db.add("Original") if operation == "update" else None
    before = backend.get_row(id) if id else None
    model.documents.clear()
    client = model._client = FakeEmbeddingClient(len)
    original = client.preprocess
    calls = []

    def drift(*args, **kwargs):
        result = original(*args, **kwargs)
        if not calls:
            client.max_seq_length = 128
        calls.append(True)
        return result

    client.preprocess = drift
    monkeypatch.setattr(db, "_embeddings", db._SerializedEmbeddings(model))
    monkeypatch.setattr(db, "_retriever", None)
    arguments = {"content": "z" * 200, **({"id": id} if id else {})}
    with pytest.raises(ToolError):
        await server.mcp.call_tool("memory_" + operation, arguments)
    assert model.documents == []
    if id:
        assert backend.get_row(id) == before
    else:
        assert backend.load_all() == []


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
    stored = backend.get_row(id)["text"]
    assert response.json()["content"] == stored
    assert OVERSIZED.startswith(stored) and len(stored.split()) + 2 <= 256
    assert response.json()["created_at"] == original_created
    assert embeddings.documents == [stored]


@pytest.mark.parametrize("content", ["", " \t\u2003"])
def test_http_invalid_content_is_422_without_changing_or_reembedding_memory(
    content_store, content
):
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


def test_cli_add_uses_the_same_backend_limit_and_reports_the_real_id(
    content_store, monkeypatch, capsys
):
    backend, embeddings = content_store
    monkeypatch.setattr(
        sys, "argv", ["scripts/memory.py", "add", OVERSIZED, "--repo", "entrypoints"]
    )
    assert cli.main() == 0
    id = capsys.readouterr().out.strip().removeprefix("Added: ")
    UUID(id)
    stored = backend.get_row(id)["text"]
    assert OVERSIZED.startswith(stored) and len(stored.split()) + 2 <= 256
    assert embeddings.documents == [stored]
