from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from mcp.server.fastmcp.exceptions import ToolError
from psycopg2.extras import RealDictCursor
from pydantic import ValidationError

from services.action_items import db
from services.action_items.server import create_server
from services.api.app import app
from services.db import get_connection
from services.profiles.contracts import TopicCreate, TopicList, TopicUpdate
from tests.test_action_item_projects import (
    call,
    empty_project_catalog as empty_project_catalog,
    names,
)
from tests.test_profile_discussion_queue import owners as owners

OFFSET = "2026-07-01T09:15:30.123456-04:00"
UTC_STAMP = "2026-07-01T13:15:30.123456+00:00"


@pytest.fixture
def client():
    return TestClient(app)


def stored(item_id):
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("SET LOCAL TIME ZONE 'UTC'")
        cursor.execute(
            "SELECT to_jsonb(action_items) FROM action_items WHERE id=%s", (item_id,)
        )
        return cursor.fetchone()[0]


def test_due_lifecycle_normalizes_to_utc_and_preserves_deadline_on_status_changes(
    client,
):
    response = client.post(
        "/api/action-items", json={"title": "With deadline", "due_at": OFFSET}
    )
    assert response.status_code == 201, response.text
    first = response.json()
    assert first["due_at"] == UTC_STAMP
    assert stored(first["id"])["due_at"] == UTC_STAMP
    assert client.get(f"/api/action-items/{first['id']}").json() == first
    assert db.list_items()["items"][0]["due_at"] == UTC_STAMP
    completed = db.update(first["id"], {"expected_revision": 1, "status": "completed"})
    assert completed["due_at"] == UTC_STAMP and completed["priority"] is None
    reopened = db.update(first["id"], {"expected_revision": 2, "status": "open"})
    assert reopened["due_at"] == UTC_STAMP and reopened["priority"] == 1
    renamed = db.update(
        first["id"], {"expected_revision": 3, "title": "Only title changes"}
    )
    assert renamed["due_at"] == UTC_STAMP
    cleared = client.patch(
        f"/api/action-items/{first['id']}",
        json={"expected_revision": 4, "due_at": None},
    )
    assert cleared.status_code == 200 and cleared.json()["due_at"] is None
    assert (
        db.update(first["id"], {"expected_revision": 5, "due_at": None})
        == cleared.json()
    )


def test_undated_old_callers_remain_accessible_and_equivalent_instants_are_noops():
    undated = db.create({"title": "Old caller"})
    assert undated["due_at"] is None
    first = db.create({"title": "Same instant", "due_at": OFFSET})
    before = stored(first["id"])
    assert (
        db.update(first["id"], {"expected_revision": 1, "due_at": UTC_STAMP}) == first
    )
    assert stored(first["id"]) == before


@pytest.mark.parametrize(
    "value",
    [
        "",
        "2026-07-01",
        "2026-07-01T13:15:30",
        "not a date",
        "2026-02-30T00:00:00Z",
        "1234567890",
        True,
        1234567890,
        1.5,
        [],
        {},
        "0001-01-01T00:00:00+14:00",
        "9999-12-31T23:59:59-14:00",
        "2026-07-01T13:15:30.1234567Z",
        "2026-07-01T13:15:30.123456789Z",
        "2026-07-01T13:15:30.1234560+00:00",
    ],
)
def test_due_inputs_reject_naive_coerced_or_invalid_values_without_phantom_projects(
    client, value
):
    response = client.post(
        "/api/action-items",
        json={"title": "Rejected", "project": "Never created", "due_at": value},
    )
    assert response.status_code == 422
    with pytest.raises((ValueError, ValidationError)):
        db.create({"title": "Rejected", "project": "Never created", "due_at": value})
    assert db.list_items()["total"] == 0 and names() == set()


def test_original_uuid_receipt_remains_replayable_and_does_not_gain_a_null_deadline():
    payload = {
        "title": "Historical request",
        "project": " Work ",
        "request_id": str(uuid4()),
    }
    first = db.create(payload)
    receipt = stored(first["id"])["create_payload"]
    assert "due_at" not in receipt
    changed = db.update(
        first["id"], {"expected_revision": 1, "title": "Later title", "due_at": OFFSET}
    )
    assert db.create(payload) == changed
    assert db.create({**payload, "due_at": None}) == changed
    assert stored(first["id"])["create_payload"] == receipt
    with pytest.raises(db.Conflict):
        db.create({**payload, "due_at": OFFSET})


def test_python_deadline_values_require_awareness_and_preserve_exact_instants():
    aware = datetime(
        2026, 7, 1, 9, 15, 30, 123456, tzinfo=timezone(timedelta(hours=-4))
    )
    assert (
        db.create({"title": "Internal aware value", "due_at": aware})["due_at"]
        == UTC_STAMP
    )
    for invalid in [aware.replace(tzinfo=None), date(2026, 7, 1)]:
        with pytest.raises(ValidationError):
            db.create({"title": "Rejected naive value", "due_at": invalid})


def test_deadline_uuid_replay_freezes_original_instant_and_rejects_new_input_before_writes():
    payload = {"title": "Frozen deadline", "due_at": OFFSET, "request_id": str(uuid4())}
    first = db.create(payload)
    receipt = stored(first["id"])["create_payload"]
    assert receipt["due_at"] == UTC_STAMP
    changed = db.update(first["id"], {"expected_revision": 1, "due_at": None})
    assert db.create({**payload, "due_at": UTC_STAMP}) == changed
    assert stored(first["id"])["create_payload"] == receipt
    for changed_fields in (
        {"due_at": None},
        {"due_at": "2026-07-02T13:15:30Z", "project": "Phantom"},
    ):
        with pytest.raises(db.Conflict):
            db.create({**payload, **changed_fields})
    assert names() == set()


def test_stale_deadline_patch_cannot_change_task_or_create_project():
    first = db.create({"title": "Protected", "due_at": OFFSET})
    changed = db.update(first["id"], {"expected_revision": 1, "title": "Current"})
    with pytest.raises(db.Conflict):
        db.update(
            first["id"], {"expected_revision": 1, "due_at": None, "project": "Phantom"}
        )
    assert db.get(first["id"]) == changed and names() == set()


def relative_task(title, hours, **fields):
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT CURRENT_TIMESTAMP")
        now = cursor.fetchone()[0]
    return db.create(
        {"title": title, "due_at": (now + timedelta(hours=hours)).isoformat(), **fields}
    )


@pytest.mark.parametrize("hours", [5, 24, 48])
def test_due_window_includes_past_and_within_but_excludes_undated_and_later(hours):
    overdue = relative_task("Past deadline", -24)
    inside = relative_task("Inside window", hours - 0.1)
    relative_task("Outside window", hours + 0.1)
    db.create({"title": "No deadline"})
    completed = relative_task("Completed history", -48, status="completed")
    assert [
        row["id"] for row in db.list_items({"due_within_hours": hours})["items"]
    ] == [overdue["id"], inside["id"]]
    assert [
        row["id"]
        for row in db.list_items({"due_within_hours": hours, "status": "completed"})[
            "items"
        ]
    ] == [completed["id"]]
    assert db.list_items({"due_within_hours": hours, "status": "all"})["total"] == 3
    assert db.list_items({"status": "all"})["total"] == 5


def test_due_window_combines_with_project_tags_unassigned_and_preserves_global_priorities(
    client,
):
    first = relative_task("Selected first", 2, project="Work", tags=["security"])
    hidden = relative_task(
        "Hidden other project", 2, project="Other", tags=["security"]
    )
    db.create({"title": "Undated selected", "project": "Work", "tags": ["security"]})
    last = relative_task("Selected last", 3, project="Work", tags=["security"])
    unassigned = relative_task("Unassigned due", 1, tags=["security"])
    response = client.get(
        "/api/action-items",
        params={
            "project": "Work",
            "tags": "security",
            "due_within_hours": 5,
            "limit": 1,
            "offset": 1,
        },
    )
    assert response.status_code == 200, response.text
    assert (
        response.json()["total"] == 2
        and response.json()["items"][0]["id"] == last["id"]
    )
    assert response.json()["items"][0]["priority"] == 4
    assert (
        db.list_items({"unassigned": True, "due_within_hours": 5})["items"][0]["id"]
        == unassigned["id"]
    )
    moved = db.move(first["id"], {"expected_revision": 1, "after_id": last["id"]})
    assert moved["priority"] == 4
    assert [row["id"] for row in db.list_items()["items"]][:1] == [hidden["id"]]
    assert db.get(hidden["id"])["revision"] == 1
    assert [
        row["priority"]
        for row in db.list_items(
            {"project": "Work", "tags": ["security"], "due_within_hours": 5}
        )["items"]
    ] == [3, 4]


def test_due_count_and_page_consume_one_transaction_clock_and_same_bound_hours(
    monkeypatch,
):
    relative_task("Expected", 2)
    observations = []
    original = db.get_connection

    class Cursor:
        def __init__(self, connection, cursor):
            self.connection, self.cursor = connection, cursor

        def __enter__(self):
            self.cursor.__enter__()
            return self

        def __exit__(self, *args):
            return self.cursor.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self.cursor, name)

        def execute(self, sql, parameters=None):
            result = self.cursor.execute(sql, parameters)
            if " WHERE " in sql and "due_at" in sql.split(" WHERE ", 1)[1]:
                with self.connection.cursor(cursor_factory=RealDictCursor) as probe:
                    probe.execute(
                        "SELECT CURRENT_TIMESTAMP AS as_of, CURRENT_TIMESTAMP+make_interval(hours => %s) AS cutoff, current_setting('TimeZone') AS timezone",
                        (5,),
                    )
                    observations.append((sql, parameters, dict(probe.fetchone())))
            return result

    class Connection:
        def __init__(self, connection):
            self.connection = connection

        def cursor(self, *args, **kwargs):
            return Cursor(self.connection, self.connection.cursor(*args, **kwargs))

    @contextmanager
    def traced_connection():
        with original() as connection:
            yield Connection(connection)

    monkeypatch.setattr(db, "get_connection", traced_connection)
    result = db.list_items({"due_within_hours": 5})
    assert result["total"] == 1 and len(result["items"]) == 1
    assert len(observations) == 2
    assert observations[0][2] == observations[1][2]
    for sql, parameters, clock in observations:
        assert "CURRENT_TIMESTAMP" in sql and "make_interval" in sql
        assert 5 in parameters
        assert clock["timezone"] == "UTC" and clock["as_of"].utcoffset() == timedelta(0)
        assert clock["cutoff"] - clock["as_of"] == timedelta(hours=5)


@pytest.mark.parametrize("value", [0, 169, -1, True, 1.5, "5", None])
def test_due_window_core_has_a_strict_optional_integer_contract(value):
    if value is None:
        assert db.list_items({"due_within_hours": None}) == {"items": [], "total": 0}
    else:
        with pytest.raises((ValueError, ValidationError)):
            db.list_items({"due_within_hours": value})


@pytest.mark.parametrize("hours", [1, 168])
def test_due_window_accepts_both_documented_boundaries(client, hours):
    assert db.list_items({"due_within_hours": hours}) == {"items": [], "total": 0}
    assert (
        client.get("/api/action-items", params={"due_within_hours": hours}).status_code
        == 200
    )


@pytest.mark.parametrize("value", ["0", "169", "true", "1.5", "1.0", "", "no"])
def test_rest_rejects_invalid_due_window_without_relaxing_filters(client, value):
    assert (
        client.get("/api/action-items", params={"due_within_hours": value}).status_code
        == 422
    )


@pytest.mark.asyncio
async def test_due_mcp_validates_before_coercion_and_matches_rest(client):
    server = create_server()
    tools = {tool.name: tool for tool in await server.list_tools()}
    assert "due_at" in tools["action_item_create"].inputSchema["properties"]
    assert "due_within_hours" in tools["action_item_list"].inputSchema["properties"]
    first = await call(
        server, "action_item_create", title="MCP deadline", due_at=OFFSET
    )
    assert first["due_at"] == UTC_STAMP
    assert client.get(f"/api/action-items/{first['id']}").json() == first
    listed = await call(server, "action_item_list", due_within_hours=24)
    assert listed["items"][0]["id"] == first["id"]
    cleared = await call(
        server,
        "action_item_update",
        item_id=first["id"],
        changes={"expected_revision": 1, "due_at": None},
    )
    assert cleared["due_at"] is None
    for tool, arguments in [
        ("action_item_create", {"title": "Rejected", "due_at": "2026-07-01T01:00:00"}),
        (
            "action_item_create",
            {"title": "Rejected precision", "due_at": "2026-07-01T13:15:30.123456789Z"},
        ),
        ("action_item_list", {"due_within_hours": True}),
        ("action_item_list", {"due_within_hours": "5"}),
    ]:
        with pytest.raises(ToolError):
            await call(server, tool, **arguments)


def test_profile_contracts_remain_deadline_free():
    profile_id = str(uuid4())
    for contract, payload in [
        (TopicCreate, {"profile_id": profile_id, "title": "Topic", "due_at": OFFSET}),
        (
            TopicUpdate,
            {
                "profile_id": profile_id,
                "item_id": 1,
                "changes": {"expected_revision": 1, "due_at": None},
            },
        ),
        (TopicList, {"profile_id": profile_id, "due_within_hours": 24}),
    ]:
        with pytest.raises(ValidationError):
            contract.model_validate(payload)
    for contract in (TopicCreate, TopicList):
        assert (
            "due_at" not in contract.model_fields
            and "due_within_hours" not in contract.model_fields
        )


def test_profile_runtime_reads_and_http_contract_do_not_gain_deadline_fields(
    owners, client
):
    queue = db.profile_queue(owners[0]["id"])
    topic = queue.create({"title": "No task deadline on this discussion topic"})
    assert "due_at" not in topic
    assert "due_at" not in queue.list_items()["items"][0]
    path = f"/api/profiles/{owners[0]['id']}/discussion-topics"
    assert "due_at" not in client.get(f"{path}/{topic['id']}").json()
    assert client.get(path, params={"due_within_hours": 24}).status_code == 422
    assert (
        client.post(
            path, json={"title": "Rejected topic", "due_at": OFFSET}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"{path}/{topic['id']}", json={"expected_revision": 1, "due_at": None}
        ).status_code
        == 422
    )


def test_profile_queue_rejects_deadline_fields_before_database_access(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError(
            "Profile deadline inputs must fail before opening a connection"
        )

    monkeypatch.setattr(db, "get_connection", forbidden)
    queue = db.Queue(str(uuid4()))
    for operation in [
        lambda: queue.create({"title": "Topic", "due_at": OFFSET}),
        lambda: queue.update(1, {"expected_revision": 1, "due_at": None}),
        lambda: queue.list_items({"due_within_hours": 5}),
    ]:
        with pytest.raises(ValueError):
            operation()
