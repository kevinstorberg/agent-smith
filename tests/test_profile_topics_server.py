from __future__ import annotations

import json
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import LATEST_PROTOCOL_VERSION

from services.action_items import db
from services.action_items.server import create_server as create_action_items_server
from services.api.app import MCP_SERVERS, app
from services.api.routers.action_items import router as action_items_router
from services.api.routers.profile_topics import router as topics_router
from services.api.routers.profiles import router as profiles_router
from services.db import get_connection
from services.meetings import profile_db
from services.profiles.server import create_server, mcp
from tests.test_action_items import action_items_empty as action_items_empty

_READ_TOOLS = {"profile_list", "profile_get", "profile_topic_list", "profile_topic_get"}
_TOPIC_TOOLS = {"profile_topic_" + name for name in ("list", "get", "create", "update", "delete", "move")}
_PROFILE_ID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture(autouse=True)
def no_inference(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Profile discovery and discussion topics must not run models, graphs, or providers")

    monkeypatch.setattr("services.graphs.model_factory.build_chat_model", forbidden)
    monkeypatch.setattr("services.graphs.runtime.dispatch", forbidden)
    monkeypatch.setattr("services.meetings.factory.build_meeting_provider", forbidden)


@pytest.fixture
def people():
    marker = "MCP discussion " + uuid4().hex
    rows = [profile_db.create_profile(marker + " A"), profile_db.create_profile(marker + " B")]
    yield rows
    ids = tuple(row["id"] for row in rows)
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("DELETE FROM action_items WHERE profile_id IN %s", (ids,))
        cursor.execute("DELETE FROM participant_profiles WHERE merged_into IN %s", (ids,))
        cursor.execute("DELETE FROM participant_profiles WHERE id IN %s", (ids,))


@asynccontextmanager
async def mounted_protocol():
    server = create_server()
    server.settings.stateless_http = True
    server.settings.streamable_http_path = "/"
    application = FastAPI()
    application.include_router(profiles_router, prefix="/api/profiles")
    application.include_router(topics_router, prefix="/api/profiles")
    application.include_router(action_items_router, prefix="/api/action-items")
    application.mount("/mcp/profiles", server.streamable_http_app())
    async with server.session_manager.run(), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://127.0.0.1:7654") as client:
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        request_id = 0

        async def rpc(method, params, *, allow_error=False):
            nonlocal request_id
            request_id += 1
            response = await client.post("/mcp/profiles/", headers=headers, json={
                "jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            assert response.status_code == 200, response.text
            event = response.json() if response.headers["content-type"].startswith("application/json") else json.loads(
                next(line[5:].strip() for line in response.text.splitlines() if line.startswith("data:")))
            assert "error" not in event, event
            result = event["result"]
            if not allow_error:
                assert not result.get("isError"), result
            return result

        await rpc("initialize", {"protocolVersion": LATEST_PROTOCOL_VERSION, "capabilities": {},
                                  "clientInfo": {"name": "profile-topic-tests", "version": "1"}})
        initialized = await client.post("/mcp/profiles/", headers=headers, json={
            "jsonrpc": "2.0", "method": "notifications/initialized"})
        assert initialized.status_code == 202
        yield client, rpc


async def tool(rpc, name, **arguments):
    return (await rpc("tools/call", {"name": name, "arguments": arguments}))["structuredContent"]


@pytest.mark.asyncio
async def test_profile_and_global_list_direct_calls_default_omitted_arguments_to_bounded_readonly_results(people):
    people.extend(profile_db.create_profile("Default arguments " + uuid4().hex) for _ in range(10))
    tasks = [db.create({"title": f"Default arguments {index}"}) for index in range(12)]
    profiles_before = [profile_db.get_profile(row["id"], include_evidence=False) for row in people]

    for server, name in ((create_server(), "profile_list"), (create_action_items_server(), "action_item_list")):
        omitted = (await server.call_tool(name))[1]
        explicit = (await server.call_tool(name, {}))[1]
        assert omitted == explicit
        assert len(omitted["items"]) == 10 and omitted["total"] >= 12
        listed_tool = next(item for item in await server.list_tools() if item.name == name)
        assert listed_tool.annotations.readOnlyHint is True

    assert [profile_db.get_profile(row["id"], include_evidence=False) for row in people] == profiles_before
    assert [db.get(row["id"]) for row in tasks] == tasks


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["null", "[]", "{}", "false"])
async def test_profile_and_global_queries_preserve_json_looking_literal_strings(people, query):
    match = profile_db.create_profile(f"Literal {query} " + uuid4().hex)
    people.append(match)
    matching_topic = db.profile_queue(people[0]["id"]).create({"title": f"Literal {query}"})
    db.profile_queue(people[0]["id"]).create({"title": "Unrelated topic"})
    global_server = create_action_items_server()
    matching_task = (await global_server.call_tool("action_item_create", {
        "title": f"Literal {query}", "project": "null"}))[1]
    assert matching_task["project"] == "null"
    db.create({"title": "Unrelated task"})

    async with mounted_protocol() as (_, rpc):
        profiles = await tool(rpc, "profile_list", q=query)
        assert profiles["total"] == 1 and [row["id"] for row in profiles["items"]] == [match["id"]]
        topics = await tool(rpc, "profile_topic_list", profile_id=people[0]["id"], q=query)
        assert topics["total"] == 1 and [row["id"] for row in topics["items"]] == [matching_topic["id"]]

    tasks = (await global_server.call_tool("action_item_list", {"q": query, "project": "null"}))[1]
    assert tasks["total"] == 1 and [row["id"] for row in tasks["items"]] == [matching_task["id"]]


@pytest.mark.asyncio
async def test_profile_topics_actual_mounted_protocol_and_rest_share_scoped_records(people):
    async with mounted_protocol() as (client, rpc):
        assert mcp in MCP_SERVERS
        assert any(getattr(route, "path", None) == "/mcp/profiles" for route in app.routes)
        a, b = people
        a_path = f"/api/profiles/{a['id']}/discussion-topics"
        b_path = f"/api/profiles/{b['id']}/discussion-topics"
        profiles_before = [profile_db.get_profile(row["id"], include_evidence=False) for row in people]
        discovered = await tool(rpc, "profile_list", q=a["display_name"], limit=1)
        assert discovered["total"] == 1 and discovered["items"][0]["id"] == a["id"]
        identity = await tool(rpc, "profile_get", profile_id=a["id"])
        assert identity["id"] == a["id"] and identity["display_name"] == a["display_name"]
        assert not {"claims", "relationships", "merge_history", "assessment"}.intersection(identity)
        assert await tool(rpc, "profile_topic_list", profile_id=a["id"]) == {"items": [], "total": 0, "profile_id": a["id"]}

        global_task = (await client.post("/api/action-items", json={"title": "Global concern"})).json()
        other = (await client.post(b_path, json={"title": "Other person's discussion"})).json()
        notes = "## Ask about staffing\n\n" + "Retain the complete confidential preparation note. " * 180
        original = {"profile_id": a["id"], "title": "Staffing concern", "description": notes,
                    "tags": [" Prep "], "request_id": str(uuid4())}
        created = await tool(rpc, "profile_topic_create", **original)
        assert created["profile_id"] == a["id"] and created["priority"] == other["priority"] == global_task["priority"] == 1
        assert created["description"] == notes
        assert (await client.get(f"{a_path}/{created['id']}")).json() == created
        listed = await tool(rpc, "profile_topic_list", profile_id=a["id"], q="confidential", tags=["prep"])
        assert listed["total"] == 1 and listed["profile_id"] == a["id"]
        assert listed["items"][0]["id"] == created["id"] and "description" not in listed["items"][0]
        assert (await client.get("/api/action-items")).json()["items"] == [
            {key: value for key, value in global_task.items() if key != "description"}]

        edited = (await client.patch(f"{a_path}/{created['id']}", json={
            "expected_revision": created["revision"], "title": "Updated concern", "description": notes + "\nREST edit", "tags": []})).json()
        assert await tool(rpc, "profile_topic_get", profile_id=a["id"], item_id=created["id"]) == edited
        assert await tool(rpc, "profile_topic_create", **original) == edited
        second = await tool(rpc, "profile_topic_create", profile_id=a["id"], title="Second concern")
        third = await tool(rpc, "profile_topic_create", profile_id=a["id"], title="Third concern")
        moved = await tool(rpc, "profile_topic_move", profile_id=a["id"], item_id=third["id"], expected_revision=1, before_id=created["id"])
        assert moved["priority"] == 1 and moved["revision"] == 2
        assert [row["id"] for row in (await client.get(a_path)).json()["items"]] == [third["id"], created["id"], second["id"]]

        completed = await tool(rpc, "profile_topic_update", profile_id=a["id"], item_id=created["id"],
                               changes={"expected_revision": edited["revision"], "status": "completed"})
        assert completed["priority"] is None and completed["completed_at"]
        reopened = (await client.patch(f"{a_path}/{created['id']}", json={
            "expected_revision": completed["revision"], "status": "open"})).json()
        assert reopened["priority"] == 3 and reopened["completed_at"] is None
        assert await tool(rpc, "profile_topic_get", profile_id=a["id"], item_id=created["id"]) == reopened
        stale = await rpc("tools/call", {"name": "profile_topic_update", "arguments": {
            "profile_id": a["id"], "item_id": created["id"], "changes": {"expected_revision": edited["revision"], "title": "Stale"}}}, allow_error=True)
        assert stale["isError"] is True
        assert (await client.patch(f"{a_path}/{created['id']}", json={"expected_revision": edited["revision"], "title": "Stale"})).status_code == 409

        assert (await client.get(f"{b_path}/{created['id']}")).status_code == 404
        assert (await client.get(f"{a_path}/{global_task['id']}")).status_code == 404
        assert (await client.get(f"/api/action-items/{created['id']}")).status_code == 404
        cross_anchor = await rpc("tools/call", {"name": "profile_topic_move", "arguments": {
            "profile_id": a["id"], "item_id": third["id"], "expected_revision": moved["revision"], "after_id": other["id"]}}, allow_error=True)
        assert cross_anchor["isError"] is True
        deleted = await tool(rpc, "profile_topic_delete", profile_id=a["id"], item_id=created["id"], expected_revision=reopened["revision"])
        assert deleted == {"deleted": True, "id": created["id"]}
        assert (await client.get(f"{a_path}/{created['id']}")).status_code == 404
        replay = await rpc("tools/call", {"name": "profile_topic_create", "arguments": original}, allow_error=True)
        assert replay["isError"] is True
        assert [row["priority"] for row in (await client.get(a_path)).json()["items"]] == [1, 2]
        assert db.get(global_task["id"]) == global_task
        assert db.profile_queue(b["id"]).get(other["id"]) == other
        assert [profile_db.get_profile(row["id"], include_evidence=False) for row in people] == profiles_before


@pytest.mark.asyncio
async def test_profile_topics_schemas_are_authoritative_and_all_tools_have_owner_scopes():
    async with mounted_protocol() as (client, rpc):
        tools = {item["name"]: item for item in (await rpc("tools/list", {}))["tools"]}
        assert set(tools) == _TOPIC_TOOLS | {"profile_list", "profile_get"}
        for name, item in tools.items():
            schema = item["inputSchema"]
            assert schema["additionalProperties"] is False
            assert item["annotations"]["readOnlyHint"] == (name in _READ_TOOLS)
            assert item["annotations"]["destructiveHint"] == (name == "profile_topic_delete")
            if name in _TOPIC_TOOLS:
                assert "profile_id" in schema["required"] and "project" not in schema["properties"]
            if name == "profile_topic_update":
                assert "project" not in schema["$defs"]["ItemPatch"]["properties"]


@pytest.mark.asyncio
async def test_profiles_discovery_and_empty_alias_queue_use_canonical_owner_and_hide_deleted_people(people):
    owner = profile_db.link_alias(people[0]["id"], f"topic-alias-{uuid4().hex}@example.test", people[0]["revision"])
    alias = owner["aliases"][0]
    async with mounted_protocol() as (_, rpc):
        found = await tool(rpc, "profile_list", q=alias["email"])
        assert found["total"] == 1 and found["items"][0]["id"] == owner["id"]
        assert (await tool(rpc, "profile_get", profile_id=alias["id"]))["id"] == owner["id"]
        assert await tool(rpc, "profile_topic_list", profile_id=alias["id"]) == {
            "items": [], "total": 0, "profile_id": owner["id"]}
        topic = await tool(rpc, "profile_topic_create", profile_id=alias["id"], title="Alias discussion")
        assert topic["profile_id"] == owner["id"]
        assert await tool(rpc, "profile_topic_get", profile_id=owner["id"], item_id=topic["id"]) == topic
        profile_db.delete_profile(owner["id"], owner["revision"])
        assert (await tool(rpc, "profile_list", q=alias["email"]))["total"] == 0
        for name, arguments in (("profile_get", {"profile_id": alias["id"]}),
                                ("profile_topic_list", {"profile_id": owner["id"]})):
            result = await rpc("tools/call", {"name": name, "arguments": arguments}, allow_error=True)
            assert result["isError"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("name,arguments", [
    ("profile_list", {"q": " "}), ("profile_list", {"query": "name"}),
    ("profile_list", {"limit": "10"}), ("profile_list", {"limit": True}),
    ("profile_get", {"profile_id": "not-a-uuid"}), ("profile_get", {"profile_id": True}),
    ("profile_get", {"profile_id": _PROFILE_ID, "extra": 1}),
    ("profile_topic_list", {"profile_id": _PROFILE_ID, "project": "work"}),
    ("profile_topic_list", {"profile_id": _PROFILE_ID, "status": "completed", "sort": "manual"}),
    ("profile_topic_get", {"profile_id": _PROFILE_ID, "item_id": True}),
    ("profile_topic_get", {"profile_id": _PROFILE_ID, "item_id": "1"}),
    ("profile_topic_create", {"profile_id": _PROFILE_ID, "title": "Topic", "owner_id": _PROFILE_ID}),
    ("profile_topic_create", {"profile_id": _PROFILE_ID, "title": "Topic", "project": None}),
    ("profile_topic_create", {"profile_id": _PROFILE_ID, "title": 123}),
    ("profile_topic_update", {"profile_id": _PROFILE_ID, "item_id": 1, "changes": {"expected_revision": "1", "title": "Topic"}}),
    ("profile_topic_update", {"profile_id": _PROFILE_ID, "item_id": 1, "changes": {"expected_revision": 1, "profile_id": _PROFILE_ID}}),
    ("profile_topic_update", {"profile_id": _PROFILE_ID, "item_id": 1, "changes": {"expected_revision": 1, "project": "work"}}),
    ("profile_topic_update", {"profile_id": _PROFILE_ID, "item_id": 1, "changes": {"expected_revision": 1, "priority": 1}}),
    ("profile_topic_delete", {"profile_id": _PROFILE_ID, "item_id": 1, "expected_revision": True}),
    ("profile_topic_move", {"profile_id": _PROFILE_ID, "item_id": 1, "expected_revision": 1}),
    ("profile_topic_move", {"profile_id": _PROFILE_ID, "item_id": 1, "expected_revision": 1, "before_id": 2, "after_id": 3}),
])
async def test_profile_topics_raw_inputs_fail_before_domain_calls(monkeypatch, name, arguments):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid raw input must fail before domain or storage calls")

    monkeypatch.setattr(db, "profile_queue", forbidden)
    monkeypatch.setattr(profile_db, "list_profiles", forbidden)
    monkeypatch.setattr(profile_db, "get_profile", forbidden)
    with pytest.raises(ToolError):
        await mcp.call_tool(name, arguments)


@pytest.mark.asyncio
async def test_profiles_http_rejects_owner_or_project_mutation_without_changing_topic(people):
    async with mounted_protocol() as (client, rpc):
        owner, other = people
        created = await tool(rpc, "profile_topic_create", profile_id=owner["id"], title="Stay with owner")
        path = f"/api/profiles/{owner['id']}/discussion-topics/{created['id']}"
        for changes in ({"project": "work"}, {"profile_id": other["id"]}, {"expected_revision": "1"}, {"priority": 2}):
            response = await client.patch(path, json={"expected_revision": 1, **changes})
            assert response.status_code == 422
            assert (await client.get(path)).json() == created
        raw = await rpc("tools/call", {"name": "profile_topic_update", "arguments": {
            "profile_id": owner["id"], "item_id": created["id"], "changes": {"expected_revision": 1, "profile_id": other["id"]}}}, allow_error=True)
        assert raw["isError"] is True
        assert await tool(rpc, "profile_topic_get", profile_id=owner["id"], item_id=created["id"]) == created
