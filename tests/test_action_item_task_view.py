from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from services.action_items import db, queue_db
from services.api.app import app
from services.db import get_connection
from tests.action_item_queue_helpers import assert_action_item_queue
from tests.test_action_items import action_items_empty as action_items_empty
from tests.test_action_item_epics import current, epic, membership, ref, root_ref


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def valid_queue(action_items_empty):
    yield
    assert_action_item_queue()


def ids(page):
    return [row["item"]["id"] for row in page["items"]]


def test_task_projection_paginates_every_member_with_explicit_parent_and_root_context(
    client,
):
    epic("Empty first")
    expected = []
    groups = {}
    for index in range(13):
        group = epic(f"Group {index:02}")
        for child in range(3):
            item = membership(
                db.create({"title": f"Task {index:02}-{child}"}),
                destination=current(group["id"]),
            )
            expected.append(item["id"])
        membership(
            db.create({"title": "Completed", "status": "completed"}),
            destination=current(group["id"]),
        )
        groups[group["id"]] = current(group["id"])
        if index % 3 == 0:
            expected.append(db.create({"title": f"Standalone {index}"})["id"])
    epic("Empty last")
    first = client.get("/api/action-items/queue?kind=task&limit=4").json()
    assert first["total"] == first["matching_count"] == len(expected) == 44
    assert first["root_total"] == 18
    pages = [
        client.get(
            "/api/action-items/queue",
            params={"kind": "task", "limit": 4, "offset": offset},
        ).json()
        for offset in range(0, len(expected), 4)
    ]
    rows = [row for page in pages for row in page["items"]]
    assert [row["item"]["id"] for row in rows] == expected
    assert len({row["item"]["id"] for row in rows}) == len(expected)
    assert [row["item"]["priority"] for row in rows] == list(range(1, 45))
    for row in rows:
        assert row["kind"] == "item"
        assert 0 <= row["root_index"] < 18
        if row["parent_epic_id"] is None:
            assert row["parent"] is None
        else:
            parent = row["parent"]
            assert parent == groups[row["parent_epic_id"]]
            assert parent["open_count"] == 3 and parent["total_count"] == 4
            assert row["position"] in {1, 2, 3}
    assert [row["root_index"] for row in rows] == sorted(
        row["root_index"] for row in rows
    )
    assert (
        len(client.get("/api/action-items/queue?kind=item&limit=100").json()["items"])
        == 5
    )
    assert (
        client.get("/api/action-items/queue?kind=epic&limit=100").json()["total"] == 15
    )
    assert client.get("/api/action-items?kind=task").status_code == 422


@pytest.mark.parametrize(
    "sort",
    [
        "manual",
        "manual_desc",
        "title",
        "title_desc",
        "updated",
        "updated_asc",
        "newest",
        "due_asc",
        "due_desc",
        "project_asc",
        "project_desc",
        "tags_asc",
        "tags_desc",
    ],
)
def test_task_sorts_use_individual_values_global_manual_rank_and_stable_missing_last(
    sort,
):
    groups = [epic("Z parent"), epic("A parent")]
    for index in range(6):
        item = db.create(
            {
                "title": "Equal" if index % 2 else "Alpha",
                "project": ["Work", "School", None][index % 3],
                "tags": ["match"] if index % 2 else [],
                "due_at": "2026-12-01T12:00:00Z" if index % 3 else None,
            }
        )
        if index % 3:
            membership(item, destination=current(groups[index % 2]["id"]))
    projected = queue_db.list_queue({"kind": "task", "sort": sort, "limit": 100})
    expected = db.list_items({"sort": sort, "limit": 100})
    assert ids(projected) == [item["id"] for item in expected["items"]]
    assert (
        len({row["root_index"] for row in projected["items"]})
        == projected["root_total"]
    )


def test_child_constraints_and_parent_title_search_keep_full_parent_snapshot():
    group = epic("Release context")
    deadline = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
    selected = membership(
        db.create(
            {
                "title": "Selected child",
                "project": "Work",
                "tags": ["match"],
                "due_at": deadline,
            }
        ),
        destination=group,
    )
    membership(
        db.create({"title": "Hidden child", "project": "Other"}),
        destination=current(group["id"]),
    )
    completed = membership(
        db.create(
            {
                "title": "Completed child",
                "status": "completed",
                "project": "Work",
                "tags": ["match"],
                "due_at": deadline,
            }
        ),
        destination=current(group["id"]),
    )
    expected = current(group["id"])
    page = queue_db.list_queue(
        {
            "kind": "task",
            "q": "Release context",
            "project": "Work",
            "tags": ["match"],
            "due_within_hours": 24,
        }
    )
    assert ids(page) == [selected["id"]]
    assert page["total"] == page["matching_count"] == page["root_total"] == 1
    assert page["items"][0]["parent"] == expected
    assert expected["open_count"] == 2 and expected["total_count"] == 3
    assert ids(queue_db.list_queue({"kind": "task", "status": "completed"})) == [
        completed["id"]
    ]
    assert queue_db.list_queue({"kind": "task", "unassigned": True})["total"] == 0


def test_flat_root_edges_ignore_empty_epics_but_keep_real_parent_anchors():
    epic("Empty before")
    standalone = db.create({"title": "Standalone"})
    epic("Empty between")
    parent = epic("Last matching root")
    child = membership(db.create({"title": "Child"}), destination=parent)
    epic("Empty after")
    page = queue_db.list_queue({"kind": "task"})
    assert page["root_total"] == 2
    assert [(row["item"]["id"], row["root_index"]) for row in page["items"]] == [
        (standalone["id"], 0),
        (child["id"], 1),
    ]
    boundary = queue_db.list_queue({"kind": "task", "sort": "manual_desc", "limit": 1})[
        "items"
    ][0]
    assert boundary["parent"]["id"] == parent["id"]
    queue_db.move(
        {"source": root_ref(standalone), "after": root_ref(boundary["parent"], "epic")}
    )
    assert ids(queue_db.list_queue({"kind": "task"})) == [child["id"], standalone["id"]]


def test_projection_parent_metadata_is_from_the_same_repeatable_read_snapshot(
    monkeypatch,
):
    parent, destination = epic("Original"), epic("Next")
    item = membership(db.create({"title": "Child"}), destination=parent)
    parent = current(parent["id"])
    catalog = queue_db._catalog
    changed = False

    def change_between_rows_and_catalog(cursor):
        nonlocal changed
        if not changed:
            changed = True
            queue_db.set_membership(
                item["id"],
                {
                    "expected_revision": item["revision"],
                    "expected_parent": ref(parent),
                    "destination": ref(destination),
                },
            )
        return catalog(cursor)

    monkeypatch.setattr(queue_db, "_catalog", change_between_rows_and_catalog)
    row = queue_db.list_queue({"kind": "task"})["items"][0]
    assert row["item"]["revision"] == item["revision"]
    assert row["parent"] == parent
    assert db.get(item["id"])["revision"] == item["revision"] + 1


def test_task_projection_keeps_a_constant_number_of_queries_at_representative_scale(
    monkeypatch,
):
    original = db._cursor
    statements = []

    class CountedCursor:
        def __init__(self, cursor):
            self.cursor = cursor

        def execute(self, sql, *args):
            statements.append(str(sql))
            return self.cursor.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self.cursor, name)

    @contextmanager
    def counted(*args, **kwargs):
        with original(*args, **kwargs) as (cursor, scope):
            yield (CountedCursor(cursor) if not kwargs["write"] else cursor), scope

    groups = [epic(f"Group {index}")["id"] for index in range(20)]
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """WITH tasks AS (
              INSERT INTO action_items(title) SELECT 'Task '||n FROM generate_series(1,1000)n RETURNING id
            ), ranked AS (SELECT id,row_number() OVER(ORDER BY id) AS n FROM tasks)
            INSERT INTO action_item_queue_entries(action_item_id,parent_epic_id,sort_key)
            SELECT id,(%s::integer[])[1+((n-1)/50)::integer],1+((n-1)%%50) FROM ranked""",
            (groups,),
        )
    monkeypatch.setattr(db, "_cursor", counted)
    result = queue_db.list_queue({"kind": "task", "limit": 5})
    assert result["total"] == 1000 and result["root_total"] == 20
    assert result["items"][0]["parent"]["open_count"] == 50
    assert len(statements) == 3


@pytest.mark.parametrize("edge", ["top", "bottom"])
def test_filtered_child_edge_moves_past_hidden_open_siblings_only(client, edge):
    outside = db.create({"title": "Outside"})
    parent = epic()
    children = [
        membership(
            db.create(
                {
                    "title": f"Child {index}",
                    "description": "Preserve",
                    "tags": ["visible"] if index == 2 else [],
                }
            ),
            destination=current(parent["id"]),
        )
        for index in range(5)
    ]
    membership(
        db.create({"title": "Completed", "status": "completed"}),
        destination=current(parent["id"]),
    )
    deleted = membership(
        db.create({"title": "Deleted"}), destination=current(parent["id"])
    )
    db.delete(deleted["id"], {"expected_revision": deleted["revision"]})
    row = client.get("/api/action-items/queue?kind=task&tags=visible").json()["items"][
        0
    ]
    assert row["parent"]["open_count"] == 5 and row["parent"]["total_count"] == 6
    response = client.post(
        "/api/action-items/queue/move",
        json={
            "source": root_ref(row["item"]),
            "parent": ref(row["parent"]),
            "edge": edge,
        },
    )
    assert response.status_code == 200, response.text
    expected = [item["id"] for item in children]
    expected.remove(children[2]["id"])
    expected.insert(0 if edge == "top" else len(expected), children[2]["id"])
    group = next(
        root for root in queue_db.list_queue()["items"] if root["kind"] == "epic"
    )
    assert [entry["item"]["id"] for entry in group["children"]] == expected
    saved = db.get(children[2]["id"])
    assert saved["description"] == "Preserve" and saved["tags"] == ["visible"]
    assert saved["revision"] == children[2]["revision"] + 1
    assert group["epic"]["revision"] == row["parent"]["revision"] + 1
    assert db.get(outside["id"]) == outside
    assert all(entry["parent_epic_id"] == parent["id"] for entry in group["children"])


@pytest.mark.parametrize("edge", ["top", "bottom"])
def test_actual_edge_is_a_noop_but_stale_parent_still_conflicts(client, edge):
    parent = epic()
    item = membership(db.create({"title": "Only open"}), destination=parent)
    parent = current(parent["id"])
    body = {"source": root_ref(item), "parent": ref(parent), "edge": edge}
    assert client.post("/api/action-items/queue/move", json=body).status_code == 200
    assert db.get(item["id"]) == item and current(parent["id"]) == parent
    membership(
        db.create({"title": "Hidden completed", "status": "completed"}),
        destination=parent,
    )
    changed = current(parent["id"])
    assert client.post("/api/action-items/queue/move", json=body).status_code == 409
    assert db.get(item["id"]) == item and current(parent["id"]) == changed


@pytest.mark.parametrize(
    "invalid",
    ["root", "epic_source", "both_edges", "both_anchors", "bad_edge", "missing"],
)
def test_edge_contract_rejects_ambiguous_or_unscoped_moves(client, invalid):
    parent = epic()
    item = membership(db.create({"title": "Child"}), destination=parent)
    parent = current(parent["id"])
    body = {"source": root_ref(item), "parent": ref(parent), "edge": "top"}
    if invalid == "root":
        body.pop("parent")
    elif invalid == "epic_source":
        body["source"] = root_ref(parent, "epic")
    elif invalid == "both_edges":
        body["before"] = root_ref(db.create({"title": "Other"}))
    elif invalid == "both_anchors":
        body.pop("edge")
        body.update(before=root_ref(item), after=root_ref(item))
    elif invalid == "bad_edge":
        body["edge"] = "middle"
    else:
        body.pop("edge")
    assert client.post("/api/action-items/queue/move", json=body).status_code == 422
    assert db.get(item["id"]) == item


def test_edge_rejects_another_parent_and_completed_sources(client):
    parent, other = epic("Original"), epic("Other")
    item = membership(db.create({"title": "Child"}), destination=parent)
    assert (
        client.post(
            "/api/action-items/queue/move",
            json={"source": root_ref(item), "parent": ref(other), "edge": "top"},
        ).status_code
        == 409
    )
    done = db.update(
        item["id"], {"expected_revision": item["revision"], "status": "completed"}
    )
    assert (
        client.post(
            "/api/action-items/queue/move",
            json={
                "source": root_ref(done),
                "parent": ref(current(parent["id"])),
                "edge": "bottom",
            },
        ).status_code
        == 409
    )
    assert db.get(item["id"]) == done
