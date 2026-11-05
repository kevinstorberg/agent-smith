from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import ValidationError

from services.action_items import db
from services.action_items.contracts import ItemQuery, Query
from services.action_items.server import create_server
from services.api.app import app
from services.db import get_connection


def clear_projects() -> None:
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('public.action_item_projects')")
        tables = (
            "action_items, action_item_projects"
            if cursor.fetchone()[0]
            else "action_items"
        )
        cursor.execute(f"TRUNCATE {tables}")


@pytest.fixture(autouse=True)
def empty_project_catalog():
    clear_projects()
    yield
    clear_projects()


@pytest.fixture
def client():
    return TestClient(app)


def names() -> set[str]:
    return {item["name"] for item in db.list_projects()["items"]}


def test_concurrent_catalog_creation_has_one_immutable_identity():
    ready = Barrier(2)

    def create():
        ready.wait(timeout=5)
        return db.create_project({"name": "Shared project"})

    with ThreadPoolExecutor(max_workers=2) as executor:
        calls = [executor.submit(create) for _ in range(2)]
        rows = [call.result(timeout=10) for call in calls]
    assert rows[0] == rows[1]
    assert db.list_projects() == {"items": [rows[0]], "total": 1}


def test_optional_blank_assignment_remains_clear_without_creating_a_project():
    item = db.create({"title": "No project", "project": "   "})
    assert item["project"] is None and names() == set()
    assert db.list_items({"project": "   "})["items"][0]["id"] == item["id"]


def test_invalid_new_assignment_cannot_change_task_or_create_catalog_rows():
    item = db.create({"title": "Keep this task"})
    with pytest.raises(ValidationError):
        db.update(item["id"], {"expected_revision": 1, "project": "new\nproject"})
    with pytest.raises(ValidationError):
        db.create({"title": "Rejected", "project": "new\tproject"})
    assert db.get(item["id"]) == item and names() == set()


def legacy_project(name: str) -> int:
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO action_item_projects(name) VALUES(%s) RETURNING id", (name,)
        )
        return cursor.fetchone()[0]


async def call(server, tool: str, **arguments) -> dict:
    result = await server.call_tool(tool, arguments)
    return result[1] if isinstance(result, tuple) else json.loads(result[0].text)


def test_empty_catalog_projects_persist_and_creation_is_exact_and_idempotent():
    first = db.create_project({"name": "  Pharmacy support  "})
    assert set(first) == {"id", "name", "created_at"}
    assert type(first["id"]) is int and first["id"] > 0
    assert first["name"] == "Pharmacy support"
    assert datetime.fromisoformat(first["created_at"]).tzinfo is not None
    assert db.create_project({"name": "Pharmacy support"}) == first
    different = db.create_project({"name": "pharmacy support"})
    assert different["id"] != first["id"]
    listed = db.list_projects()
    assert listed["total"] == 2 and {item["id"] for item in listed["items"]} == {
        first["id"],
        different["id"],
    }
    assert db.list_items({"status": "all"}) == {"items": [], "total": 0}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 201},
        {"name": 1},
        {"name": None},
        {"name": "bad\nname"},
        {"name": "bad\tname"},
        {"name": "bad\x7fname"},
        {"name": "bad\x85name"},
        {"name": "valid", "id": 99},
    ],
)
def test_new_project_validation_is_shared_and_never_creates_rows(client, payload):
    assert client.post("/api/action-items/projects", json=payload).status_code == 422
    with pytest.raises((ValueError, ValidationError)):
        db.create_project(payload)
    assert names() == set()


def test_project_rest_routes_precede_item_ids_and_delete_only_unreferenced_projects(
    client,
):
    response = client.post("/api/action-items/projects", json={"name": "Empty project"})
    assert response.status_code == 201
    project = response.json()
    assert client.get("/api/action-items/projects").json() == {
        "items": [project],
        "total": 1,
    }
    assert (
        client.post("/api/action-items/projects", json={"name": "Empty project"}).json()
        == project
    )
    assert client.delete(f"/api/action-items/projects/{project['id']}").json() == {
        "deleted": True,
        "id": project["id"],
    }
    assert client.get("/api/action-items/projects").json() == {"items": [], "total": 0}
    assert (
        client.delete(f"/api/action-items/projects/{project['id']}").status_code == 404
    )
    assert client.delete("/api/action-items/projects/0").status_code == 422


def test_task_assignment_uses_catalog_ids_but_keeps_string_api_tags_and_ordering():
    first = db.create(
        {"title": "First", "project": " Work ", "tags": [" Personal ", "personal"]}
    )
    hidden = db.create({"title": "Hidden", "project": "Other", "tags": ["work"]})
    last = db.create({"title": "Last", "project": "Work"})
    assert first["project"] == "Work" and first["tags"] == ["personal"]
    assert "project_id" not in first
    before = [db.get(item["id"]) for item in (first, hidden, last)]
    changed = db.update(first["id"], {"expected_revision": 1, "project": "Other"})
    assert changed["project"] == "Other" and changed["tags"] == first["tags"]
    assert changed["priority"] == first["priority"]
    assert db.get(hidden["id"]) == before[1] and db.get(last["id"]) == before[2]
    assert names() == {"Work", "Other"}
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT p.name FROM action_items a JOIN action_item_projects p ON p.id=a.project_id WHERE a.id=%s",
            (first["id"],),
        )
        assert cursor.fetchone()[0] == "Other"
    cleared = db.update(
        first["id"], {"expected_revision": changed["revision"], "project": None}
    )
    assert cleared["project"] is None and cleared["tags"] == ["personal"]
    assert names() == {"Work", "Other"}


def test_unassigned_is_separate_from_literal_project_names_and_tags(client):
    projects = [
        db.create({"title": name, "project": name, "tags": ["shared"]})
        for name in ("All projects", "Unassigned")
    ]
    unassigned = db.create({"title": "No project", "tags": ["shared"]})
    db.create({"title": "Other tag", "project": "Unassigned", "tags": ["other"]})
    for item in projects:
        listed = db.list_items({"project": item["project"], "tags": ["shared"]})
        assert [row["id"] for row in listed["items"]] == [item["id"]]
    assert [row["id"] for row in db.list_items({"unassigned": True})["items"]] == [
        unassigned["id"]
    ]
    assert db.list_items({"unassigned": False})["total"] == 4
    assert (
        client.get(
            "/api/action-items", params={"unassigned": "true", "tags": "shared"}
        ).json()["items"][0]["id"]
        == unassigned["id"]
    )
    assert (
        client.get(
            "/api/action-items", params={"unassigned": "true", "project": "Unassigned"}
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"unassigned": "true"},
        {"unassigned": 1},
        {"unassigned": None},
        {"unassigned": True, "project": "Work"},
    ],
)
def test_global_unassigned_contract_is_strict_and_mutually_exclusive(payload):
    with pytest.raises(ValidationError):
        Query.model_validate(payload)
    assert db.list_items()["total"] == 0


def test_profile_topic_query_contract_stays_project_free(client):
    for payload in ({"unassigned": True}, {"project": "Work"}):
        with pytest.raises(ValidationError):
            ItemQuery.model_validate(payload)
        assert (
            client.get(
                f"/api/profiles/{uuid4()}/discussion-topics", params=payload
            ).status_code
            == 422
        )


@pytest.mark.parametrize("raw", ["  Legacy project  ", "Legacy\nproject", " "])
def test_existing_legacy_names_remain_exactly_selectable_and_assignable(raw):
    project_id = legacy_project(raw)
    created = db.create({"title": "Legacy selection", "project": raw})
    assert created["project"] == raw
    assert [item["id"] for item in db.list_items({"project": raw})["items"]] == [
        created["id"]
    ]
    assert db.list_items({"unassigned": True})["total"] == 0
    assert (
        next(item for item in db.list_projects()["items"] if item["id"] == project_id)[
            "name"
        ]
        == raw
    )
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT project_id FROM action_items WHERE id=%s", (created["id"],)
        )
        assert cursor.fetchone()[0] == project_id


def test_original_normalized_uuid_replay_precedes_legacy_exact_name_resolution():
    request_id = str(uuid4())
    payload = {
        "title": "Original",
        "project": "Work",
        "tags": ["preparation"],
        "request_id": request_id,
    }
    original = db.create(payload)
    legacy_project("  Work  ")
    changed = db.update(
        original["id"],
        {
            "expected_revision": 1,
            "title": "Edited",
            "project": "Other",
            "status": "completed",
        },
    )
    assert (
        db.create({**payload, "project": "  Work  ", "tags": [" Preparation "]})
        == changed
    )
    assert names() == {"Work", "  Work  ", "Other"}
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT create_payload FROM action_items WHERE id=%s", (original["id"],)
        )
        assert cursor.fetchone()[0]["project"] == "Work"


def test_conflicting_creation_replay_cannot_create_a_phantom_project():
    payload = {"title": "Frozen", "request_id": str(uuid4())}
    first = db.create(payload)
    with pytest.raises(db.Conflict):
        db.create({**payload, "project": "Must not exist"})
    assert names() == set() and db.get(first["id"]) == first


def test_exact_legacy_project_creation_receipt_replays_without_normalizing_it():
    raw = "  Existing legacy  "
    legacy_project(raw)
    payload = {
        "title": "Original legacy choice",
        "project": raw,
        "request_id": str(uuid4()),
    }
    first = db.create(payload)
    edited = db.update(first["id"], {"expected_revision": 1, "title": "Saved later"})

    assert db.create(payload) == edited
    assert names() == {raw}
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT create_payload FROM action_items WHERE id=%s", (first["id"],)
        )
        assert cursor.fetchone()[0]["project"] == raw


def test_deleted_creation_receipt_rejects_before_ensuring_any_new_project():
    payload = {"title": "Deleted request", "request_id": str(uuid4())}
    first = db.create(payload)
    db.delete(first["id"], {"expected_revision": 1})

    with pytest.raises(db.Conflict, match="deleted"):
        db.create({**payload, "project": "Must not exist"})

    assert names() == set()


def test_stale_and_missing_task_writes_do_not_ensure_project_rows():
    first = db.create({"title": "Original"})
    changed = db.update(first["id"], {"expected_revision": 1, "title": "Current"})
    with pytest.raises(db.Conflict):
        db.update(first["id"], {"expected_revision": 1, "project": "Stale project"})
    with pytest.raises(db.NotFound):
        db.update(
            first["id"] + 10000,
            {"expected_revision": 1, "project": "Missing task project"},
        )
    assert names() == set() and db.get(first["id"]) == changed


@pytest.mark.parametrize("operation", ["create", "update"])
def test_failed_task_transaction_rolls_back_ensured_catalog_project(
    monkeypatch, operation
):
    first = db.create({"title": "Original"})
    read = db._read

    def fail_after_write(cursor, item_id, scope):
        read(cursor, item_id, scope)
        raise RuntimeError("Injected task write failure")

    monkeypatch.setattr(db, "_read", fail_after_write)
    with pytest.raises(RuntimeError, match="Injected"):
        if operation == "create":
            db.create({"title": "Rolled back", "project": "Phantom"})
        else:
            db.update(first["id"], {"expected_revision": 1, "project": "Phantom"})
    monkeypatch.setattr(db, "_read", read)
    assert names() == set() and db.get(first["id"]) == first
    assert db.list_items()["total"] == 1


@pytest.mark.parametrize("deleted", [False, True])
def test_any_task_reference_including_tombstones_blocks_project_deletion(
    client, deleted
):
    task = db.create({"title": "Referenced", "project": "Keep"})
    project = db.list_projects()["items"][0]
    if deleted:
        db.delete(task["id"], {"expected_revision": 1})
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT to_jsonb(action_items) FROM action_items WHERE id=%s", (task["id"],)
        )
        before = cursor.fetchone()[0]
    with pytest.raises(db.Conflict):
        db.delete_project(project["id"])
    assert (
        client.delete(f"/api/action-items/projects/{project['id']}").status_code == 409
    )
    assert names() == {"Keep"}
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT to_jsonb(action_items) FROM action_items WHERE id=%s", (task["id"],)
        )
        assert cursor.fetchone()[0] == before


def test_clearing_final_assignment_allows_project_delete_without_changing_task():
    task = db.create({"title": "Detached from project", "project": "Temporary"})
    project = db.list_projects()["items"][0]
    cleared = db.update(task["id"], {"expected_revision": 1, "project": None})
    assert db.delete_project(project["id"]) == {"deleted": True, "id": project["id"]}
    assert db.get(task["id"]) == cleared and names() == set()


@pytest.mark.asyncio
async def test_project_mcp_crud_and_original_project_string_calls_share_catalog(client):
    server = create_server()
    tools = {tool.name: tool for tool in await server.list_tools()}
    assert {
        "action_item_project_list",
        "action_item_project_create",
        "action_item_project_delete",
    } <= tools.keys()
    assert tools["action_item_project_list"].annotations.readOnlyHint is True
    assert tools["action_item_project_delete"].annotations.destructiveHint is True
    assert all(
        tools[name].inputSchema["additionalProperties"] is False
        for name in tools
        if "project_" in name
    )
    project = await call(server, "action_item_project_create", name="MCP project")
    assert (await call(server, "action_item_project_list"))["items"] == [project]
    task = await call(
        server,
        "action_item_create",
        title="Old caller",
        project="MCP project",
        tags=["other"],
    )
    assert task["project"] == "MCP project"
    assert client.get(f"/api/action-items/{task['id']}").json() == task
    assert [
        row["id"]
        for row in (await call(server, "action_item_list", project="MCP project"))[
            "items"
        ]
    ] == [task["id"]]
    empty = await call(server, "action_item_project_create", name="Empty MCP project")
    assert await call(server, "action_item_project_delete", project_id=empty["id"]) == {
        "deleted": True,
        "id": empty["id"],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool,arguments",
    [
        ("action_item_project_list", {"unexpected": True}),
        ("action_item_project_create", {"name": 123}),
        ("action_item_project_delete", {"project_id": True}),
        ("action_item_project_delete", {"project_id": "1"}),
        ("action_item_list", {"unassigned": "true"}),
    ],
)
async def test_project_mcp_contracts_reject_coercion_and_unknown_fields(
    tool, arguments
):
    with pytest.raises(ToolError):
        await call(create_server(), tool, **arguments)
