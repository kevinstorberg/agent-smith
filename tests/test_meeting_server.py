from __future__ import annotations

import json
from dataclasses import replace

import psycopg2
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from services.config import DATABASE_URL
from services.meetings import db
from services.meetings.server import mcp
from tests.test_meeting_db import config as config, summary as summary


async def call(name: str, **arguments):
    result = await mcp.call_tool(name, arguments)
    if isinstance(result, tuple):
        structured = result[1]
        return structured.get("result", structured)
    return json.loads(result[0].text) if result else None


@pytest.mark.asyncio
async def test_meeting_server_exposes_only_readers():
    tools = await mcp.list_tools()
    assert [tool.name for tool in tools] == ["meeting_list", "meeting_get", "meeting_search", "meeting_sync_status"]
    assert all(tool.annotations.readOnlyHint and not tool.annotations.destructiveHint for tool in tools)
    assert "include_unavailable" not in next(tool for tool in tools if tool.name == "meeting_get").inputSchema["properties"]


@pytest.mark.asyncio
async def test_readers_see_another_connections_committed_update_immediately(config, summary):
    db.claim_source(config, "writer")
    saved = db.save_progress(config, "writer", {}, summary=summary)
    assert (await call("meeting_get", summary_id=saved["id"]))["summary_text"] == summary.summary_text
    with psycopg2.connect(DATABASE_URL, connect_timeout=2) as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE meeting_summaries SET summary_text = %s, revision = revision + 1 WHERE id = %s",
            ("Newly committed context", saved["id"]),
        )
    row = await call("meeting_get", summary_id=saved["id"])
    assert row["summary_text"] == "Newly committed context"
    assert row["revision"] == 2
    assert row["provider"] == config.provider and row["external_id"] == summary.external_id
    assert (await call("meeting_search", query="NEWLY COMMITTED", source=config.name))["total"] == 1


@pytest.mark.asyncio
async def test_context_filters_and_unavailable_records_follow_the_storage_contract(config, summary):
    config = replace(config, project="reader-project")
    db.claim_source(config, "writer")
    saved = db.save_progress(config, "writer", {}, summary=summary)
    result = await call("meeting_list", source=config.name, project="reader-project", after="2026-01-01T00:00:00Z", limit=1)
    assert result["total"] == 1 and result["items"][0]["id"] == saved["id"]
    assert (await call("meeting_list", source=config.name, project="other"))["total"] == 0
    assert (await call("meeting_search", source=config.name, query="' OR true --"))["total"] == 0
    for _ in range(3):
        db.save_progress(config, "writer", {}, unavailable_id=summary.external_id)
    assert await call("meeting_get", summary_id=saved["id"]) is None
    assert (await call("meeting_list", source=config.name))["total"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "arguments"), [
    ("meeting_list", {"limit": 0}),
    ("meeting_list", {"offset": -1}),
    ("meeting_list", {"after": "2026-01-01"}),
    ("meeting_get", {"summary_id": "not-a-uuid"}),
    ("meeting_search", {"query": ""}),
    ("meeting_search", {"query": "x" * 1001}),
    ("meeting_sync_status", {"source": " "}),
])
async def test_tool_boundaries_reject_invalid_inputs(tool, arguments):
    with pytest.raises(ToolError):
        await call(tool, **arguments)


@pytest.mark.asyncio
async def test_sync_status_excludes_private_checkpoints_and_note_content(config):
    db.claim_source(config, "writer")
    db.save_progress(config, "writer", {
        "id": "private-scan", "cursor": "private-cursor", "pending": ["private-note"],
        "counts": {"created": 2, "private": "private-note-content"},
    })
    db.release_source(config, "writer", "failed", "private-provider-response")
    result = await call("meeting_sync_status", source=config.name)
    assert result[0]["outcome"] == "failed" and result[0]["counts"] == {"created": 2}
    assert "private-" not in json.dumps(result)
