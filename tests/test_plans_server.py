from __future__ import annotations

import json

import psycopg2
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from services.api.models.plan import create_plan, get_plan
from services.config import DATABASE_URL
from services.plans.server import mcp
from tests.test_plans_db import _clean_plans as _clean_plans


async def call(name: str, **arguments):
    result = await mcp.call_tool(name, arguments)
    if isinstance(result, tuple):
        structured = result[1]
        return structured.get("result", structured)
    return json.loads(result[0].text) if result else None


@pytest.mark.asyncio
async def test_plans_search_is_discoverable_with_read_only_contract_and_bounded_schema():
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    assert set(tools) == {"save", "get", "search"}
    for name in ("get", "search"):
        assert tools[name].annotations.readOnlyHint and not tools[name].annotations.destructiveHint
    assert "Only call when the user explicitly asks" not in tools["get"].description
    assert "full Planning Doc" in tools["get"].description
    assert "title or markdown body" in tools["search"].description
    fields = tools["search"].inputSchema["properties"]
    assert fields["limit"]["minimum"] == 1 and fields["limit"]["maximum"] == 20
    assert fields["offset"]["minimum"] == 0 and fields["offset"]["maximum"] == 10000
    assert tools["search"].inputSchema["required"] == ["query"]


@pytest.mark.asyncio
async def test_sdk_search_finds_body_context_then_get_returns_full_document_without_writes():
    body = "Unrelated prefix. " * 100 + "Retain the immutable snapshot for reconciliation." + " More detail." * 100
    target = create_plan("An implementation plan", body, project="agent-smith")
    create_plan("Another plan", "immutable snapshot", project="other")
    before = get_plan(target)
    result = await call("search", query="IMMUTABLE snapshot", project="agent-smith", status="final")
    assert [item["id"] for item in result["items"]] == [target]
    assert "immutable snapshot" in result["items"][0]["excerpt"]
    assert len(result["items"][0]["excerpt"]) <= 600 and "body" not in result["items"][0]
    assert result["has_more"] is False and result["next_offset"] is None and result["pagination_capped"] is False
    full = await call("get", plan_id=result["items"][0]["id"])
    assert full == before and full["body"] == body
    assert get_plan(target) == before


@pytest.mark.asyncio
async def test_sdk_search_paginates_after_project_and_status_filters():
    first = create_plan("First document", "scope proof", project="selected", status="draft")
    second = create_plan("Second document", "scope proof", project="selected", status="draft")
    create_plan("Other project", "scope proof", project="Selected", status="draft")
    create_plan("Other status", "scope proof", project="selected", status="final")
    page = await call("search", query="scope proof", project="selected", status="draft", limit=1)
    assert [item["id"] for item in page["items"]] == [second]
    assert page["has_more"] is True and page["next_offset"] == 1
    next_page = await call("search", query="scope proof", project="selected", status="draft", limit=1, offset=page["next_offset"])
    assert [item["id"] for item in next_page["items"]] == [first]
    assert next_page["has_more"] is False and next_page["next_offset"] is None


@pytest.mark.asyncio
async def test_sdk_search_reads_another_connections_edits_immediately():
    target = create_plan("Saved document", "OriginalUniqueTerm")
    assert (await call("search", query="originaluniqueterm"))["items"][0]["id"] == target
    with psycopg2.connect(DATABASE_URL, connect_timeout=2) as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE plans SET body=%s,updated_at=clock_timestamp() WHERE id=%s", ("FreshUniqueTerm", target))
    assert (await call("search", query="originaluniqueterm"))["items"] == []
    assert (await call("search", query="freshuniqueterm"))["items"][0]["id"] == target
    assert (await call("get", plan_id=target))["body"] == "FreshUniqueTerm"


@pytest.mark.asyncio
async def test_legacy_get_query_stays_title_only_and_returns_full_body():
    target = create_plan("Legacy title match", "Full body with BodyOnlyKeyword")
    assert await call("get", query="BodyOnlyKeyword") == []
    assert await call("get", query="Legacy title") == [get_plan(target)]
    assert await call("get") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", [
    {"query": ""}, {"query": " "}, {"query": "x" * 501}, {"query": " ".join(["x"] * 11)},
    {"query": 123}, {"query": None},
    {"project": " "}, {"project": "x" * 201}, {"project": 123},
    {"status": "approved"}, {"status": True},
    {"limit": 0}, {"limit": 21}, {"limit": True}, {"limit": "10"}, {"limit": 1.0},
    {"offset": -1}, {"offset": 10001}, {"offset": True}, {"offset": "0"}, {"offset": 0.0},
])
async def test_sdk_rejects_invalid_search_arguments_without_accessing_the_database(monkeypatch, arguments):
    def forbidden():
        pytest.fail("Invalid tool arguments must fail before opening a database connection")

    monkeypatch.setattr("services.api.models.plan.get_connection", forbidden)
    with pytest.raises(ToolError):
        await call("search", **{"query": "keyword", **arguments})
