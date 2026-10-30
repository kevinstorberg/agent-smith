from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import LATEST_PROTOCOL_VERSION

from services.action_items.server import create_server, mcp
from services.api.app import MCP_SERVERS, app
from services.api.routers.action_items import router
from tests.test_action_items import action_items_empty as action_items_empty


async def call(name: str, **arguments):
    result = await mcp.call_tool(name, arguments)
    if isinstance(result, tuple):
        return result[1]
    return json.loads(result[0].text)


@pytest.mark.asyncio
async def test_action_items_actual_mounted_mcp_and_rest_share_one_resource():
    assert mcp in MCP_SERVERS
    assert any(getattr(route, "path", None) == "/mcp/action-items" for route in app.routes)
    server = create_server()
    server.settings.stateless_http = True
    server.settings.streamable_http_path = "/"
    application = FastAPI()
    application.include_router(router, prefix="/api/action-items")
    application.mount("/mcp/action-items", server.streamable_http_app())
    async with server.session_manager.run(), httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://127.0.0.1:7654") as client:
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}

        async def rpc(method, params):
            response = await client.post("/mcp/action-items/", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
            assert response.status_code == 200
            event = response.json() if response.headers["content-type"].startswith("application/json") else json.loads(next(line[5:].strip() for line in response.text.splitlines() if line.startswith("data:")))
            assert "error" not in event
            assert not event["result"].get("isError"), event["result"]
            return event["result"]

        await rpc("initialize", {"protocolVersion": LATEST_PROTOCOL_VERSION, "capabilities": {}, "clientInfo": {"name": "action-items-tests", "version": "1"}})
        tools = (await rpc("tools/list", {}))["tools"]
        assert {tool["name"] for tool in tools} == {f"action_item_{suffix}" for suffix in ("list", "get", "create", "update", "delete", "move")}
        assert all(tool["inputSchema"]["additionalProperties"] is False for tool in tools)
        assert next(tool for tool in tools if tool["name"] == "action_item_delete")["annotations"]["destructiveHint"]
        assert next(tool for tool in tools if tool["name"] == "action_item_get")["annotations"]["readOnlyHint"]
        created = (await rpc("tools/call", {"name": "action_item_create", "arguments": {"title": "Real protocol task"}}))["structuredContent"]
        assert created["priority"] == 1
        listed = (await rpc("tools/call", {"name": "action_item_list", "arguments": {}}))["structuredContent"]
        assert listed["items"][0]["priority"] == 1
        assert (await client.get(f"/api/action-items/{created['id']}")).json() == created
        edited = (await client.patch(f"/api/action-items/{created['id']}", json={"expected_revision": created["revision"], "description": "Shared content"})).json()
        assert (await rpc("tools/call", {"name": "action_item_get", "arguments": {"item_id": created["id"]}}))["structuredContent"] == edited
        completed = await call("action_item_update", item_id=created["id"], changes={"expected_revision": edited["revision"], "status": "completed"})
        assert completed["completed_at"] and completed["status"] == "completed" and completed["priority"] is None
        reopened = await call("action_item_update", item_id=created["id"], changes={"expected_revision": completed["revision"], "status": "open"})
        assert reopened["completed_at"] is None
        assert (await call("action_item_list"))["total"] == 1
        await call("action_item_delete", item_id=created["id"], expected_revision=reopened["revision"])
        assert (await client.get(f"/api/action-items/{created['id']}")).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,arguments", [
    ("action_item_create", {"title": "Task", "revision": 99}),
    ("action_item_create", {"title": "Task", "priority": 1}),
    ("action_item_create", {"title": 12}),
    ("action_item_get", {"item_id": True}),
    ("action_item_get", {"item_id": "1"}),
    ("action_item_list", {"limit": "10"}),
    ("action_item_update", {"item_id": 1, "changes": {"expected_revision": 1, "sort_key": 7}}),
    ("action_item_update", {"item_id": 1, "changes": {"expected_revision": 1, "priority": 7}}),
    ("action_item_move", {"item_id": 1, "expected_revision": 1}),
])
async def test_action_items_mcp_raw_inputs_are_strict(tool, arguments):
    with pytest.raises(ToolError):
        await call(tool, **arguments)
