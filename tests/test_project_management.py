from concurrent.futures import ThreadPoolExecutor
import logging
from datetime import datetime, timedelta
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from services.action_items import db
from services.api.app import app
from services.db import get_connection


@pytest.fixture(autouse=True)
def catalog():
    def clear():
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("TRUNCATE action_items, action_item_projects")

    clear()
    yield
    clear()


@pytest.fixture
def client():
    return TestClient(app)


def create(client, name="WGU", description="Coursework and assessments"):
    response = client.post(
        "/api/projects", json={"name": name, "description": description}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_metadata_roundtrip_keeps_lightweight_catalog_compatible(client):
    project = create(client, "  WGU  ", "Line one\n\nLine two 🌱")
    assert (
        project["name"] == "WGU" and project["description"] == "Line one\n\nLine two 🌱"
    )
    assert project["revision"] == 1
    for field in ("created_at", "updated_at"):
        assert datetime.fromisoformat(project[field]).utcoffset() == timedelta(0)
    assert client.get(f"/api/projects/{project['id']}").json() == project
    assert client.get("/api/projects").json() == {"items": [project], "total": 1}
    legacy = {key: project[key] for key in ("id", "name", "created_at")}
    assert db.create_project({"name": "WGU"}) == legacy
    assert db.list_projects() == {"items": [legacy], "total": 1}
    assert create(client, "WGU", project["description"]) == project
    assert (
        client.post(
            "/api/projects", json={"name": "WGU", "description": "Overwrite"}
        ).status_code
        == 409
    )
    assert client.post("/api/projects", json={"name": "WGU"}).json() == project


def test_rename_retains_assignment_and_history_but_rejects_stale_item_editor(client):
    project = create(client)
    first = db.create(
        {
            "title": "First",
            "project": "WGU",
            "tags": ["school"],
            "due_at": "2026-12-01T12:00:00Z",
        }
    )
    completed = db.create({"title": "Done", "project": "WGU", "status": "completed"})
    unrelated = db.create({"title": "Other", "project": "Personal"})
    deleted = db.create({"title": "History", "project": "WGU"})
    db.delete(deleted["id"], {"expected_revision": deleted["revision"]})
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, project_id, create_payload, request_id, deleted_at, revision FROM action_items ORDER BY id"
        )
        before = cursor.fetchall()
    response = client.patch(
        f"/api/projects/{project['id']}",
        json={
            "expected_revision": 1,
            "name": "School",
            "description": "All school work",
        },
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["id"] == project["id"] and saved["revision"] == 2
    assert saved["created_at"] == project["created_at"]
    for item in (first, completed):
        assert db.get(item["id"]) == {
            **item,
            "project": "School",
            "revision": item["revision"] + 1,
        }
    assert db.get(unrelated["id"]) == unrelated
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, project_id, create_payload, request_id, deleted_at, revision FROM action_items ORDER BY id"
        )
        after = cursor.fetchall()
    assert [row[:-1] for row in after] == [row[:-1] for row in before]
    assert after[-1] == before[-1]
    stale = client.patch(
        f"/api/action-items/{first['id']}",
        json={
            "expected_revision": first["revision"],
            "title": "Old editor",
            "project": "WGU",
        },
    )
    assert stale.status_code == 409
    assert "WGU" not in {row["name"] for row in db.list_projects()["items"]}
    assert (
        client.get(
            "/api/action-items", params={"project": "School", "status": "all"}
        ).json()["total"]
        == 2
    )


def test_description_and_noop_changes_leave_items_and_timestamps_alone(client):
    project = create(client)
    item = db.create({"title": "Assigned", "project": "WGU"})
    endpoint = f"/api/projects/{project['id']}"
    assert (
        client.patch(
            endpoint,
            json={
                "expected_revision": 1,
                "name": " WGU ",
                "description": project["description"],
            },
        ).json()
        == project
    )
    saved = client.patch(
        endpoint, json={"expected_revision": 1, "description": ""}
    ).json()
    assert saved["revision"] == 2 and saved["description"] == ""
    assert db.get(item["id"]) == item
    assert (
        client.patch(
            endpoint, json={"expected_revision": 1, "description": "Stale"}
        ).status_code
        == 409
    )
    other = create(client, "Other")
    assert (
        client.patch(
            endpoint, json={"expected_revision": 2, "name": other["name"]}
        ).status_code
        == 409
    )
    assert client.get(endpoint).json() == saved


def test_legacy_names_remain_description_editable_and_case_distinct(client):
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO action_item_projects(name) VALUES('  Legacy\nname  ') RETURNING id"
        )
        project_id = cursor.fetchone()[0]
    response = client.patch(
        f"/api/projects/{project_id}",
        json={"expected_revision": 1, "description": "Legacy context"},
    )
    assert response.status_code == 200 and response.json()["name"] == "  Legacy\nname  "
    assert create(client, "wgu")["id"] != create(client, "WGU")["id"]


@pytest.mark.parametrize(
    "fields",
    [
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 201},
        {"name": "bad\nname"},
        {"name": "bad\x85name"},
        {"name": None},
        {"name": 5},
        {"description": None},
        {"description": 4},
        {"description": "bad\0text"},
        {"description": "x" * 100_001},
        {"unknown": "field"},
    ],
)
def test_metadata_validation_rejects_invalid_create_and_patch_without_writes(
    client, fields
):
    project = create(client)
    assert (
        client.post("/api/projects", json={"name": "New", **fields}).status_code == 422
    )
    assert (
        client.patch(
            f"/api/projects/{project['id']}", json={"expected_revision": 1, **fields}
        ).status_code
        == 422
    )
    assert client.get(f"/api/projects/{project['id']}").json() == project
    assert db.list_projects()["total"] == 1


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"description": "x"},
        {"expected_revision": True, "description": "x"},
        {"expected_revision": 0, "name": "New"},
        {"expected_revision": 1},
    ],
)
def test_patch_requires_revision_and_changes(client, payload):
    project = create(client)
    assert (
        client.patch(f"/api/projects/{project['id']}", json=payload).status_code == 422
    )


@pytest.mark.parametrize(
    "query",
    [
        {"sort": "DROP TABLE"},
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"q": "x" * 1001},
        {"unknown": "x"},
    ],
)
def test_management_query_validation(client, query):
    assert client.get("/api/projects", params=query).status_code == 422


def test_management_search_escapes_literals_and_sorts_before_paging(client):
    rows = [
        create(client, f"Project {index:02}", f"Description {30 - index:02}")
        for index in range(30)
    ]
    columns = {
        "name": lambda row: row["name"].lower(),
        "description": lambda row: row["description"].lower(),
        "updated": lambda row: row["updated_at"],
    }
    for column, key in columns.items():
        for direction in ("asc", "desc"):
            sort = f"{column}_{direction}"
            response = client.get(
                "/api/projects", params={"sort": sort, "limit": 10, "offset": 10}
            )
            assert response.status_code == 200, response.text
            assert response.json() == {
                "items": sorted(rows, key=key, reverse=direction == "desc")[10:20],
                "total": 30,
            }
    literal = create(client, "100%_literal", "Needle")
    assert client.get("/api/projects", params={"q": "%_"}).json() == {
        "items": [literal],
        "total": 1,
    }
    assert client.get("/api/projects", params={"q": "needle"}).json()["items"] == [
        literal
    ]


def test_concurrent_rename_has_one_winner_and_keeps_single_identity(client):
    project = create(client)
    ready = Barrier(2)

    def rename(name):
        ready.wait(timeout=5)
        return TestClient(app).patch(
            f"/api/projects/{project['id']}",
            json={"expected_revision": 1, "name": name},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(rename, ("School", "Learning")))
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert db.list_projects()["total"] == 1


def test_rename_protects_large_assigned_queue_without_changing_item_dates(client):
    project = create(client)
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO action_items(title,project_id,sort_key) SELECT 'Task ' || value,%s,value FROM generate_series(1,1000) value",
            (project["id"],),
        )
        cursor.execute(
            "SELECT id,revision,updated_at,sort_key FROM action_items ORDER BY id"
        )
        before = cursor.fetchall()
    response = client.patch(
        f"/api/projects/{project['id']}",
        json={"expected_revision": 1, "name": "Renamed"},
    )
    assert response.status_code == 200, response.text
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT id,revision,updated_at,sort_key FROM action_items ORDER BY id"
        )
        assert cursor.fetchall() == [
            (row[0], row[1] + 1, row[2], row[3]) for row in before
        ]


def test_missing_and_invalid_ids(client):
    assert client.get("/api/projects/999999999").status_code == 404
    assert (
        client.patch(
            "/api/projects/999999999", json={"expected_revision": 1, "name": "Missing"}
        ).status_code
        == 404
    )
    assert client.get("/api/projects/0").status_code == 422


def test_project_http_actions_are_classified_as_nonbillable(client, caplog):
    caplog.set_level(logging.INFO, logger="agent_smith.action")
    project = create(client)
    client.get("/api/projects")
    client.get(f"/api/projects/{project['id']}")
    client.patch(
        f"/api/projects/{project['id']}",
        json={"expected_revision": 1, "description": "New context"},
    )
    lines = [
        record.getMessage()
        for record in caplog.records
        if record.name == "agent_smith.action"
    ]
    for action in ("CREATE", "LIST", "READ", "UPDATE"):
        assert (
            sum(line.startswith(f"PROJECT {action} [NONBILLABLE] ") for line in lines)
            == 1
        )
