from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from services.action_items import db
from services.api.app import app
from services.db import get_connection


@pytest.fixture(autouse=True)
def action_items_empty():
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("TRUNCATE action_items")
    yield
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("TRUNCATE action_items")


@pytest.fixture
def client():
    return TestClient(app)


def test_action_items_lifecycle_and_explicit_clears(client):
    response = client.post("/api/action-items", json={"title": "  Follow up  ", "description": "Details", "project": " Work ", "tags": [" Security ", "security", "Product"]})
    assert response.status_code == 201
    first = response.json()
    assert (first["title"], first["project"], first["tags"]) == ("Follow up", "Work", ["product", "security"])
    assert first["status"] == "open" and first["completed_at"] is None and first["revision"] == 1
    assert set(first) == {"id", "title", "description", "project", "tags", "status", "completed_at", "revision", "created_at", "updated_at", "priority"}
    changed = client.patch(f"/api/action-items/{first['id']}", json={"expected_revision": 1, "project": None, "description": None, "tags": []}).json()
    assert changed["title"] == "Follow up" and changed["project"] is None and changed["description"] == "" and changed["tags"] == []
    assert changed["revision"] == 2
    complete = db.update(first["id"], {"expected_revision": 2, "status": "completed"})
    assert complete["completed_at"] and complete["revision"] == 3
    assert db.update(first["id"], {"expected_revision": 3, "status": "completed"}) == complete
    assert db.list_items()["total"] == 0
    assert db.list_items({"status": "completed"})["total"] == 1
    assert "description" not in db.list_items({"status": "all"})["items"][0]
    reopened = db.update(first["id"], {"expected_revision": 3, "status": "open"})
    assert reopened["completed_at"] is None and reopened["revision"] == 4
    assert client.request("DELETE", f"/api/action-items/{first['id']}", json={"expected_revision": 1}).status_code == 409
    assert client.request("DELETE", f"/api/action-items/{first['id']}", json={"expected_revision": 4}).json() == {"deleted": True, "id": first["id"]}
    assert client.get(f"/api/action-items/{first['id']}").status_code == 404
    assert db.list_items({"status": "all"})["total"] == 0


def test_action_items_creation_replay_preserves_later_edits_and_tombstones():
    payload = {"title": "Original", "tags": [" Work "], "request_id": str(uuid4())}
    first = db.create(payload)
    changed = db.update(first["id"], {"expected_revision": 1, "title": "Edited", "status": "completed"})
    assert db.create({**payload, "tags": ["work"]}) == changed
    with pytest.raises(db.Conflict, match="different input"):
        db.create({**payload, "title": "Different"})
    second = db.create({**payload, "request_id": str(uuid4())})
    assert second["id"] != first["id"]
    db.delete(first["id"], {"expected_revision": changed["revision"]})
    with pytest.raises(db.Conflict, match="deleted"):
        db.create(payload)


@pytest.mark.parametrize("payload", [
    {}, {"title": " \n "}, {"title": "x" * 201}, {"title": 7}, {"title": "ok", "status": "pending"},
    {"title": "ok", "request_id": "bad"}, {"title": "ok", "revision": 99}, {"title": "ok", "priority": 3}, {"title": "ok", "tags": [""]},
    {"title": "ok", "tags": ["x" * 101]}, {"title": "ok", "tags": ["tag"] * 21},
    {"title": "ok", "project": "x" * 201}, {"title": "ok", "description": "x" * 100001},
])
def test_action_items_create_validation_is_shared_and_atomic(client, payload):
    assert client.post("/api/action-items", json=payload).status_code == 422
    with pytest.raises((ValueError, ValidationError)):
        db.create(payload)
    assert db.list_items()["total"] == 0


@pytest.mark.parametrize("payload", [
    {"title": None}, {"status": None}, {"status": "pending"}, {"sort_key": 3}, {"priority": 3}, {"id": 3},
    {"expected_revision": True}, {"expected_revision": "1"}, {"expected_revision": 0},
])
def test_action_items_patch_rejects_invalid_inputs_without_mutation(client, payload):
    first = db.create({"title": "Task"})
    assert client.patch(f"/api/action-items/{first['id']}", json={"expected_revision": 1, **payload}).status_code == 422
    assert db.get(first["id"]) == first


def test_action_items_search_filters_before_count_and_pagination():
    for index in range(12):
        db.create({"title": f"Task {index:02}", "description": "Needle" if index % 2 else "Other", "project": "work" if index < 10 else "personal", "tags": ["product", "security"] if index % 2 else ["product"]})
    result = db.list_items({"q": "NEEDLE", "project": "work", "tags": ["Product", "Security"], "sort": "title", "limit": 2, "offset": 2})
    assert result["total"] == 5
    assert [item["title"] for item in result["items"]] == ["Task 05", "Task 07"]
    assert db.list_items({"q": "' OR true --"})["total"] == 0
    literal = db.create({"title": "100%_done"})
    assert [row["id"] for row in db.list_items({"q": "%_"})["items"]] == [literal["id"]]
    with pytest.raises(ValueError, match="manual"):
        db.list_items({"status": "all", "sort": "manual"})


def test_action_items_public_priority_tracks_the_global_open_queue(client):
    created = [db.create({"title": f"Task {25 - index:02}", "project": "selected" if index in (2, 12, 23) else "other"})
               for index in range(25)]
    assert [item["priority"] for item in created] == list(range(1, 26))
    page = client.get("/api/action-items", params={"limit": 10, "offset": 10}).json()
    assert [item["priority"] for item in page["items"]] == list(range(11, 21))
    filtered = client.get("/api/action-items", params={"project": "selected", "sort": "title"}).json()
    assert [item["priority"] for item in filtered["items"]] == [24, 13, 3]
    assert client.get("/api/action-items", params={"project": "selected", "sort": "title", "limit": 1, "offset": 1}).json()["items"][0]["priority"] == 13
    moved = db.move(created[0]["id"], {"expected_revision": 1, "after_id": created[9]["id"]})
    assert moved["priority"] == 10
    assert db.get(created[1]["id"])["priority"] == 1
    assert db.get(created[1]["id"])["revision"] == 1
    completed = client.patch(f"/api/action-items/{created[1]['id']}", json={"expected_revision": 1, "status": "completed"}).json()
    assert completed["priority"] is None
    assert db.get(moved["id"])["priority"] == 9
    assert client.get("/api/action-items", params={"status": "completed"}).json()["items"][0]["priority"] is None
    reopened = db.update(completed["id"], {"expected_revision": completed["revision"], "status": "open"})
    assert reopened["priority"] == 25
    assert db.create({"title": "Already complete", "status": "completed"})["priority"] is None


@pytest.mark.parametrize("query", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"q": " "}, {"q": "x" * 1001}, {"status": "bad"}, {"sort": "DROP TABLE action_items"}, {"status": "completed", "sort": "manual"}, {"sort_key": 2}])
def test_action_items_invalid_queries(client, query):
    assert client.get("/api/action-items", params=query).status_code == 422


def test_action_items_stale_writes_and_rollback(monkeypatch):
    first = db.create({"title": "Task"})
    changed = db.update(first["id"], {"expected_revision": 1, "description": "New"})
    for operation, payload in ((db.update, {"title": "Lost"}), (db.delete, {})):
        with pytest.raises(db.Conflict):
            operation(first["id"], {"expected_revision": 1, **payload})
    original = db._read

    def failed_read(cursor, item_id):
        original(cursor, item_id)
        raise RuntimeError("Injected failure after write")

    monkeypatch.setattr(db, "_read", failed_read)
    with pytest.raises(RuntimeError, match="Injected"):
        db.update(first["id"], {"expected_revision": changed["revision"], "title": "Rolled back"})
    monkeypatch.setattr(db, "_read", original)
    assert db.get(first["id"]) == changed
