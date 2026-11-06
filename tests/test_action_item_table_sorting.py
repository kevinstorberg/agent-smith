from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from services.action_items import db
from services.api.app import app
from services.db import get_connection
from services.meetings import profile_db
from tests.test_action_items import action_items_empty as action_items_empty


COMMON_ORDERS = [
    ("manual", [0, 1, 2, 3, 4, 5]),
    ("manual_desc", [5, 4, 3, 2, 1, 0]),
    ("title", [1, 2, 4, 3, 5, 0]),
    ("title_desc", [0, 5, 3, 4, 2, 1]),
    ("tags_asc", [1, 3, 0, 4, 2, 5]),
    ("tags_desc", [4, 0, 3, 1, 5, 2]),
    ("updated_asc", [0, 4, 2, 3, 1, 5]),
    ("updated", [5, 1, 3, 2, 4, 0]),
]
GLOBAL_ORDERS = [
    ("project_asc", [1, 4, 0, 5, 2, 3]),
    ("project_desc", [5, 0, 4, 1, 3, 2]),
    ("due_asc", [1, 4, 0, 3, 2, 5]),
    ("due_desc", [3, 0, 4, 1, 5, 2]),
]


@pytest.fixture
def make_queue():
    owners = []

    def make(scope):
        marker = "table-order-" + uuid4().hex
        owner = profile_db.create_profile(marker)
        owners.append(owner["id"])
        profile_queue = db.profile_queue(owner["id"])
        queue = db.Queue(None) if scope == "global" else profile_queue
        other = profile_queue if scope == "global" else db.Queue(None)
        specs = [
            ("zulu", ["yellow"], "Beta", 1, 2),
            ("alpha", ["alpha"], "Alpha", 3, 1),
            ("ALPHA", [], None, 2, None),
            ("charlie", ["alpha"], None, 2, 3),
            ("bravo", ["zebra"], "ALPHA", 1, 1),
            ("delta", [], "Beta", 4, None),
        ]
        stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
        records = []
        for title, tags, project, day, due in specs:
            payload = {"title": f"{marker} {title}", "tags": tags}
            if scope == "global":
                payload.update(
                    project=project,
                    due_at=(stamp + timedelta(days=due)).isoformat() if due else None,
                )
            item = queue.create(payload)
            records.append(item)
            with get_connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE action_items SET updated_at=%s WHERE id=%s",
                    (stamp + timedelta(days=day), item["id"]),
                )
        other.create({"title": f"{marker} 000 outside scope"})
        queue.create({"title": f"{marker} 000 completed", "status": "completed"})
        endpoint = (
            "/api/action-items"
            if scope == "global"
            else f"/api/profiles/{owner['id']}/discussion-topics"
        )
        return queue, marker, [item["id"] for item in records], endpoint

    yield make
    with get_connection() as connection, connection.cursor() as cursor:
        for owner in owners:
            cursor.execute("DELETE FROM action_items WHERE profile_id=%s", (owner,))
            cursor.execute("DELETE FROM participant_profiles WHERE id=%s", (owner,))


@pytest.mark.parametrize(
    "scope,sort,positions",
    [
        *(
            (scope, sort, positions)
            for scope in ("global", "profile")
            for sort, positions in COMMON_ORDERS
        ),
        *(("global", sort, positions) for sort, positions in GLOBAL_ORDERS),
    ],
)
def test_action_item_table_sort_is_global_before_paging_and_preserves_scope(
    make_queue, scope, sort, positions
):
    queue, marker, ids, endpoint = make_queue(scope)
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT * FROM action_items ORDER BY id")
        before = cursor.fetchall()
    pages = [
        queue.list_items({"q": marker, "sort": sort, "limit": 2, "offset": offset})
        for offset in (0, 2, 4)
    ]
    assert [row["id"] for page in pages for row in page["items"]] == [
        ids[index] for index in positions
    ]
    assert [page["total"] for page in pages] == [6, 6, 6]
    assert all("description" not in row for page in pages for row in page["items"])
    response = TestClient(app).get(
        endpoint, params={"q": marker, "sort": sort, "limit": 2, "offset": 2}
    )
    assert response.status_code == 200
    assert response.json()["total"] == 6
    assert [row["id"] for row in response.json()["items"]] == [
        ids[index] for index in positions[2:4]
    ]
    filtered = queue.list_items(
        {"q": marker, "sort": sort, "tags": ["alpha"], "limit": 1, "offset": 1}
    )
    assert filtered["total"] == 2
    assert (
        filtered["items"][0]["id"]
        == [ids[index] for index in positions if index in (1, 3)][1]
    )
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT * FROM action_items ORDER BY id")
        assert cursor.fetchall() == before


@pytest.mark.parametrize("sort", [sort for sort, _ in GLOBAL_ORDERS])
def test_profile_topic_sort_refuses_global_only_columns_before_storage(
    monkeypatch, sort
):
    profile_id = str(uuid4())
    response = TestClient(app).get(
        f"/api/profiles/{profile_id}/discussion-topics", params={"sort": sort}
    )
    assert response.status_code == 422

    def unexpected_cursor(*args, **kwargs):
        pytest.fail("Unsupported topic sort reached storage")

    monkeypatch.setattr(db, "_cursor", unexpected_cursor)
    with pytest.raises(ValueError):
        db.profile_queue(profile_id).list_items({"sort": sort})


@pytest.mark.parametrize("status", ["completed", "all"])
def test_reverse_priority_remains_open_only(monkeypatch, status):
    def unexpected_cursor(*args, **kwargs):
        pytest.fail("Unavailable manual order reached storage")

    monkeypatch.setattr(db, "_cursor", unexpected_cursor)
    with pytest.raises(ValueError):
        db.Queue(None).list_items({"status": status, "sort": "manual_desc"})
    assert (
        TestClient(app)
        .get("/api/action-items", params={"status": status, "sort": "manual_desc"})
        .status_code
        == 422
    )


@pytest.mark.parametrize("scope", ["global", "profile"])
def test_new_nonpriority_sort_works_for_completed_and_all_scopes(make_queue, scope):
    queue, marker, ids, endpoint = make_queue(scope)
    completed = queue.list_items(
        {"q": marker, "status": "completed", "sort": "title_desc"}
    )
    assert completed["total"] == 1 and completed["items"][0]["status"] == "completed"
    all_items = queue.list_items({"q": marker, "status": "all", "sort": "title_desc"})
    assert all_items["total"] == 7
    assert [item["id"] for item in all_items["items"][:6]] == [
        ids[index] for index in (0, 5, 3, 4, 2, 1)
    ]


@pytest.mark.parametrize(
    "sort", ["title;DROP TABLE action_items", "due_at DESC", "", "manual_reverse"]
)
def test_action_item_sort_rejects_unknown_values_before_storage(monkeypatch, sort):
    def unexpected_cursor(*args, **kwargs):
        pytest.fail("Untrusted sort reached storage")

    monkeypatch.setattr(db, "_cursor", unexpected_cursor)
    with pytest.raises(ValueError):
        db.Queue(None).list_items({"sort": sort})
    assert (
        TestClient(app).get("/api/action-items", params={"sort": sort}).status_code
        == 422
    )
