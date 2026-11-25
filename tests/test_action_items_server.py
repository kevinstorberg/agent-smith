from __future__ import annotations

import json
from uuid import uuid4

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
    assert any(
        getattr(route, "path", None) == "/mcp/action-items" for route in app.routes
    )
    server = create_server()
    server.settings.stateless_http = True
    server.settings.streamable_http_path = "/"
    application = FastAPI()
    application.include_router(router, prefix="/api/action-items")
    application.mount("/mcp/action-items", server.streamable_http_app())
    async with (
        server.session_manager.run(),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://127.0.0.1:7654",
        ) as client,
    ):
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }

        async def rpc(method, params):
            response = await client.post(
                "/mcp/action-items/",
                headers=headers,
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            )
            assert response.status_code == 200
            event = (
                response.json()
                if response.headers["content-type"].startswith("application/json")
                else json.loads(
                    next(
                        line[5:].strip()
                        for line in response.text.splitlines()
                        if line.startswith("data:")
                    )
                )
            )
            assert "error" not in event
            assert not event["result"].get("isError"), event["result"]
            return event["result"]

        await rpc(
            "initialize",
            {
                "protocolVersion": LATEST_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "action-items-tests", "version": "1"},
            },
        )
        tools = (await rpc("tools/list", {}))["tools"]
        assert {tool["name"] for tool in tools} == {
            f"action_item_{suffix}"
            for suffix in ("list", "get", "create", "update", "delete", "move")
        } | {
            f"action_item_project_{suffix}" for suffix in ("list", "create", "delete")
        } | {
            f"action_item_epic_{suffix}"
            for suffix in ("list", "create", "rename", "delete")
        } | {"action_item_set_epic", "action_item_queue_list", "action_item_queue_move"}
        assert all(
            tool["inputSchema"]["additionalProperties"] is False for tool in tools
        )
        assert next(tool for tool in tools if tool["name"] == "action_item_delete")[
            "annotations"
        ]["destructiveHint"]
        assert next(tool for tool in tools if tool["name"] == "action_item_get")[
            "annotations"
        ]["readOnlyHint"]
        assert next(
            tool for tool in tools if tool["name"] == "action_item_epic_delete"
        )["annotations"]["destructiveHint"]
        for name in ("action_item_epic_list", "action_item_queue_list"):
            assert next(tool for tool in tools if tool["name"] == name)["annotations"][
                "readOnlyHint"
            ]
        created = (
            await rpc(
                "tools/call",
                {
                    "name": "action_item_create",
                    "arguments": {"title": "Real protocol task"},
                },
            )
        )["structuredContent"]
        assert created["priority"] == 1
        listed = (
            await rpc("tools/call", {"name": "action_item_list", "arguments": {}})
        )["structuredContent"]
        assert listed["items"][0]["priority"] == 1
        assert (
            await client.get(f"/api/action-items/{created['id']}")
        ).json() == created
        edited = (
            await client.patch(
                f"/api/action-items/{created['id']}",
                json={
                    "expected_revision": created["revision"],
                    "description": "Shared content",
                },
            )
        ).json()
        assert (
            await rpc(
                "tools/call",
                {"name": "action_item_get", "arguments": {"item_id": created["id"]}},
            )
        )["structuredContent"] == edited
        completed = await call(
            "action_item_update",
            item_id=created["id"],
            changes={"expected_revision": edited["revision"], "status": "completed"},
        )
        assert (
            completed["completed_at"]
            and completed["status"] == "completed"
            and completed["priority"] is None
        )
        reopened = await call(
            "action_item_update",
            item_id=created["id"],
            changes={"expected_revision": completed["revision"], "status": "open"},
        )
        assert reopened["completed_at"] is None
        assert (await call("action_item_list"))["total"] == 1
        await call(
            "action_item_delete",
            item_id=created["id"],
            expected_revision=reopened["revision"],
        )
        assert (
            await client.get(f"/api/action-items/{created['id']}")
        ).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool,arguments",
    [
        ("action_item_create", {"title": "Task", "revision": 99}),
        ("action_item_create", {"title": "Task", "priority": 1}),
        ("action_item_create", {"title": 12}),
        ("action_item_get", {"item_id": True}),
        ("action_item_get", {"item_id": "1"}),
        ("action_item_list", {"limit": "10"}),
        ("action_item_list", {"kind": "epic"}),
        (
            "action_item_update",
            {"item_id": 1, "changes": {"expected_revision": 1, "sort_key": 7}},
        ),
        (
            "action_item_update",
            {"item_id": 1, "changes": {"expected_revision": 1, "priority": 7}},
        ),
        ("action_item_move", {"item_id": 1, "expected_revision": 1}),
        ("action_item_queue_list", {"filters": {"limit": "10"}}),
        ("action_item_queue_list", {"filters": {"epic_id": 1}}),
        ("action_item_queue_list", {"filters": {"kind": "single"}}),
        ("action_item_queue_list", {"filters": {"kind": True}}),
        ("action_item_epic_create", {"title": "Epic", "request_id": "bad"}),
        (
            "action_item_epic_create",
            {"title": "Epic", "request_id": str(uuid4()), "item_id": 1},
        ),
        (
            "action_item_epic_rename",
            {"epic_id": True, "title": "Epic", "expected_revision": 1},
        ),
        (
            "action_item_epic_delete",
            {"epic_id": 1, "expected_revision": 1, "cohort": "bad"},
        ),
        (
            "action_item_set_epic",
            {
                "item_id": 1,
                "expected_revision": 1,
                "destination": {"id": 1, "expected_revision": 1},
            },
        ),
        (
            "action_item_queue_move",
            {"source": {"kind": "item", "id": 1, "expected_revision": 1}},
        ),
    ],
)
async def test_action_items_mcp_raw_inputs_are_strict(tool, arguments):
    with pytest.raises(ToolError):
        await call(tool, **arguments)


@pytest.mark.asyncio
async def test_action_items_mcp_groups_maintains_and_orders_existing_tasks_with_live_snapshots(
    caplog,
):
    from tests.test_action_item_epics import ref, root_ref

    first = await call("action_item_create", title="First", description="Preserve this")
    second = await call("action_item_create", title="Second")
    outside = await call("action_item_create", title="Outside")
    payload = {
        "title": "Delivery",
        "request_id": str(uuid4()),
        "item_id": first["id"],
        "membership": {"expected_revision": first["revision"]},
    }
    group = await call("action_item_epic_create", **payload)
    assert (await call("action_item_epic_create", **payload))["id"] == group["id"]
    assert (await call("action_item_epic_list"))["items"][0]["cohort"] == group[
        "cohort"
    ]
    grouped = await call(
        "action_item_set_epic",
        item_id=second["id"],
        expected_revision=second["revision"],
        destination=ref(group),
    )
    with pytest.raises(ToolError, match="changed"):
        await call(
            "action_item_set_epic",
            item_id=outside["id"],
            expected_revision=outside["revision"],
            destination=ref(group),
        )

    async def read_group():
        queue = await call(
            "action_item_queue_list", filters={"status": "all", "sort": "title"}
        )
        return next(root for root in queue["items"] if root["kind"] == "epic")

    current = await read_group()
    epics_only = await call(
        "action_item_queue_list", filters={"kind": "epic", "limit": 1}
    )
    assert epics_only["total"] == 1 and epics_only["matching_count"] == 2
    assert epics_only["items"][0]["kind"] == "epic"
    singles_only = await call("action_item_queue_list", filters={"kind": "item"})
    assert singles_only["total"] == singles_only["matching_count"] == 1
    assert singles_only["items"][0]["item"]["id"] == outside["id"]
    assert [child["item"]["title"] for child in current["children"]] == [
        "First",
        "Second",
    ]
    await call(
        "action_item_queue_move",
        source=root_ref(grouped),
        parent=ref(current["epic"]),
        before=root_ref(current["children"][0]["item"]),
    )
    queue = await call("action_item_queue_list", filters={"sort": "manual"})
    current = next(root for root in queue["items"] if root["kind"] == "epic")
    assert [child["item"]["id"] for child in current["children"]] == [
        second["id"],
        first["id"],
    ]
    assert any(
        root["kind"] == "item" and root["item"]["id"] == outside["id"]
        for root in queue["items"]
    )
    renamed = await call(
        "action_item_epic_rename",
        epic_id=group["id"],
        expected_revision=current["epic"]["revision"],
        title="Release delivery",
    )
    assert renamed["title"] == "Release delivery"
    child = current["children"][0]["item"]
    await call(
        "action_item_set_epic",
        item_id=child["id"],
        expected_revision=child["revision"],
        expected_parent=ref(renamed),
        destination=None,
    )
    current = await read_group()
    assert [child["item"]["id"] for child in current["children"]] == [first["id"]]
    await call(
        "action_item_epic_delete",
        epic_id=group["id"],
        expected_revision=current["epic"]["revision"],
        cohort=current["epic"]["cohort"],
    )
    assert (await call("action_item_epic_list"))["items"] == []
    assert (await call("action_item_get", item_id=first["id"]))[
        "description"
    ] == "Preserve this"
    assert (await call("action_item_list", status="all"))["total"] == 3
    events = [
        record.operation_event
        for record in caplog.records
        if hasattr(record, "operation_event")
    ]
    epic_tools = {
        "action_item_epic_list",
        "action_item_epic_create",
        "action_item_epic_rename",
        "action_item_epic_delete",
        "action_item_set_epic",
        "action_item_queue_list",
        "action_item_queue_move",
    }
    assert epic_tools <= {event.get("tool") for event in events}
    assert all(
        event["billing"] == "nonbillable"
        for event in events
        if event.get("tool") in epic_tools
    )
