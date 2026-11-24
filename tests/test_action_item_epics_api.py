from time import monotonic
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from services.action_items import db, queue_db
from services.api.app import app
from services.db import get_connection
from tests.test_action_items import action_items_empty as action_items_empty
from tests.test_action_item_epics import epic, membership, current, ref, root_ref


@pytest.fixture
def client():
    return TestClient(app)


def test_complete_groups_precede_pagination_and_keep_full_hidden_cohort(client):
    root = db.create({"title": "Root"})
    group = epic()
    children = []
    for index in range(3):
        children.append(membership(db.create({"title": f"Child {index}", "tags": ["match"] if index == 0 else []}), destination=current(group["id"])))
    first = client.get("/api/action-items/queue", params={"limit": 1, "offset": 1}).json()
    assert first["total"] == 2
    assert first["matching_count"] == 4
    assert [row["item"]["id"] for row in first["items"][0]["children"]] == [row["id"] for row in children]
    filtered = client.get("/api/action-items/queue?tags=match&limit=1").json()
    assert filtered["total"] == 1 and filtered["matching_count"] == 1
    assert filtered["items"][0]["total_count"] == 3
    assert filtered["items"][0]["epic"]["cohort"] == first["items"][0]["epic"]["cohort"]
    assert client.get("/api/action-items").json()["items"][0]["id"] == root["id"]


def test_epic_http_lifecycle_and_strict_boundaries(client):
    child = db.create({"title": "Child"})
    response = client.post("/api/action-items/epics", json={"title": "New", "request_id": str(uuid4()), "item_id": child["id"], "membership": {"expected_revision": 1}})
    assert response.status_code == 201
    group = response.json()
    assert client.patch(f"/api/action-items/epics/{group['id']}", json={"expected_revision": group["revision"], "title": "Renamed"}).status_code == 200
    group = current(group["id"])
    assert client.post(f"/api/action-items/{child['id']}/epic", json={"expected_revision": db.get(child["id"])["revision"], "expected_parent": ref(group)}).status_code == 200
    group = current(group["id"])
    assert client.request("DELETE", f"/api/action-items/epics/{group['id']}", json={"expected_revision": group["revision"], "cohort": group["cohort"]}).status_code == 200
    assert db.get(child["id"])["title"] == "Child"
    assert client.get("/api/action-items/queue?parent=1").status_code == 422
    assert client.post("/api/action-items/epics", json={"title": " ", "request_id": str(uuid4())}).status_code == 422
    assert client.patch(f"/api/action-items/{child['id']}", json={"expected_revision": db.get(child["id"])["revision"], "epic_id": 1}).status_code == 422


@pytest.mark.parametrize("column", ["title", "updated", "newest", "due", "project", "tags"])
def test_sorts_stable_for_complete_roots_and_children(column):
    groups = [epic("Beta"), epic("Alpha"), epic("Gamma")]
    for index in range(30):
        item = db.create({"title": f"Task {index:03}", "project": ["Work", "School", None][index % 3], "tags": [["a", "b"], ["c"], []][index % 3], "due_at": f"2026-12-{index % 9+1:02}T15:00:00Z" if index % 2 else None})
        membership(item, destination=current(groups[index % 3]["id"]))
    asc, desc = {"updated": ("updated_asc", "updated"), "newest": ("newest", "newest")}.get(column, (column + "_asc", column + "_desc"))
    if column == "title":
        asc = "title"
    one = queue_db.list_queue({"sort": asc})
    two = queue_db.list_queue({"sort": desc})
    assert len(one["items"]) == len(two["items"]) == 3
    def identities(result, sort):
        return [row["epic"]["id"] for row in result["items"] if queue_db._root_value(row, sort) is not None]
    if column != "newest":
        assert identities(one, asc) == list(reversed(identities(two, desc)))
    assert sum(len(row["children"]) for row in one["items"]) == 30


def test_filters_keep_parent_titles_and_hide_empty_constrained_groups():
    group = epic("Launch")
    done = db.create({"title": "Finished", "status": "completed", "project": "Work"})
    membership(done, destination=group)
    assert queue_db.list_queue()["items"][0]["matching_count"] == 0
    assert queue_db.list_queue({"q": "Launch"})["total"] == 1
    assert queue_db.list_queue({"project": "Work"})["total"] == 0
    assert queue_db.list_queue({"status": "completed"})["items"][0]["matching_count"] == 1
    assert queue_db.list_queue({"q": "unrelated"})["total"] == 0


def test_stale_root_api_move_does_not_change_current_order(client):
    root = db.create({"title": "Root"})
    group = epic()
    membership(db.create({"title": "Hidden"}), destination=group)
    result = client.post("/api/action-items/queue/move", json={"source": root_ref(group, "epic"), "before": root_ref(root)})
    assert result.status_code == 409
    assert queue_db.list_queue()["items"][0]["kind"] == "item"


def test_grouped_query_real_scale_stays_inside_existing_statement_bound(record_property):
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute("""WITH epics AS (INSERT INTO action_item_epics(title,request_id,create_payload)
          SELECT 'Epic '||n,md5('epic-test-'||n)::uuid,'{}'::jsonb FROM generate_series(1,1000)n RETURNING id)
          INSERT INTO action_item_queue_entries(epic_id,sort_key) SELECT id,row_number() OVER(ORDER BY id) FROM epics""")
        cursor.execute("SELECT id FROM action_item_epics ORDER BY id")
        ids = [row[0] for row in cursor.fetchall()]
        cursor.execute("""WITH tasks AS (INSERT INTO action_items(title,tags)
          SELECT 'Task '||n,ARRAY['match'] FROM generate_series(1,10000)n RETURNING id),
          ranked AS (SELECT id,row_number() OVER(ORDER BY id) AS n FROM tasks)
          INSERT INTO action_item_queue_entries(action_item_id,parent_epic_id,sort_key)
          SELECT id,(%s::integer[])[CASE WHEN n<=1000 THEN 1 ELSE 2+((n-1001)/10)::integer END],
            CASE WHEN n<=1000 THEN n ELSE 1+((n-1001)%%10) END FROM ranked""", (ids,))
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(f"""EXPLAIN (ANALYZE,FORMAT JSON) SELECT {db._Scope(None).columns(detail=False)},q.id AS entry_id,q.parent_epic_id,q.sort_key AS position
          FROM {db._PROJECT_ROWS} JOIN action_item_queue_entries q ON q.action_item_id=a.id
          LEFT JOIN action_item_epics e ON e.id=q.parent_epic_id
          WHERE a.profile_id IS NULL AND a.deleted_at IS NULL AND a.status='open' AND a.tags @> ARRAY['match']::text[]""")
        execution_ms = cursor.fetchone()[0][0]["Execution Time"]
        record_property("grouped_projection_ms", execution_ms)
        assert execution_ms < 5000
    started = monotonic()
    result = queue_db.list_queue({"tags": ["match"], "sort": "due_asc", "limit": 100})
    elapsed = monotonic()-started
    record_property("grouped_read_seconds", elapsed)
    assert elapsed < 5, f"Grouped read took {elapsed:.3f}s, exceeding the existing bound"
    assert result["matching_count"] == 10000
    assert any(len(row["children"]) == 1000 for row in queue_db.list_queue({"limit": 100})["items"])
