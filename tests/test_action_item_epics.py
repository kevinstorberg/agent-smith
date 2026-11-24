from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg2
import pytest

from services.action_items import db, queue_db
from services.db import get_connection
from tests.action_item_queue_helpers import assert_action_item_queue
from tests.test_action_items import action_items_empty as action_items_empty


def epic(title="Release", item=None, parent=None):
    payload = {"title": title, "request_id": str(uuid4())}
    if item:
        payload.update(item_id=item["id"], membership={"expected_revision": item["revision"], "expected_parent": ref(parent) if parent else None})
    return queue_db.create_epic(payload)


def ref(value):
    return {"id": value["id"], "expected_revision": value["revision"], "cohort": value["cohort"]}


def current(epic_id):
    return next(row for row in queue_db.list_epics()["items"] if row["id"] == epic_id)


def membership(item, parent=None, destination=None):
    return queue_db.set_membership(item["id"], {"expected_revision": item["revision"], "expected_parent": ref(parent) if parent else None, "destination": ref(destination) if destination else None})


def root_ref(value, kind="item"):
    return {"kind": kind, "id": value["id"], "expected_revision": value["revision"], **({"cohort": value["cohort"]} if kind == "epic" else {})}


def flat_ids():
    return [row["id"] for row in db.list_items({"limit": 100})["items"]]


@pytest.fixture(autouse=True)
def valid_queue_after(action_items_empty):
    yield
    assert_action_item_queue()


def test_singleton_epic_order_and_removal_preserve_all_task_fields():
    first = db.create({"title": "A"})
    child = db.create({"title": "C", "description": "Details", "project": "Work", "tags": ["one"], "due_at": "2026-12-01T15:00:00Z"})
    group = epic(item=child)
    child = db.get(child["id"])
    queue_db.move({"source": root_ref(group, "epic"), "before": root_ref(first)})
    assert flat_ids() == [child["id"], first["id"]]
    saved = db.get(child["id"])
    group = current(group["id"])
    queue_db.remove_epic(group["id"], {"expected_revision": group["revision"], "cohort": group["cohort"]})
    assert flat_ids() == [child["id"], first["id"]]
    after = db.get(child["id"])
    assert {k:v for k,v in after.items() if k not in {"revision", "updated_at"}} == {k:v for k,v in saved.items() if k not in {"revision", "updated_at"}}
    assert after["revision"] == saved["revision"]+1
    assert queue_db.list_epics()["items"] == []


def test_empty_epic_and_completion_reopen_keep_membership():
    group = epic()
    child = membership(db.create({"title": "Child"}), destination=group)
    done = db.update(child["id"], {"expected_revision": child["revision"], "status": "completed"})
    opened = db.update(child["id"], {"expected_revision": done["revision"], "status": "open"})
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT parent_epic_id,sort_key FROM action_item_queue_entries WHERE action_item_id=%s", (opened["id"],))
        assert cursor.fetchone() == (group["id"], 1)
    assert current(group["id"])["total_count"] == 1
    moved = membership(opened, parent=current(group["id"]))
    assert moved["priority"] == 1
    assert current(group["id"])["total_count"] == 0


def test_create_and_move_replay_does_not_reapply_membership():
    child = db.create({"title": "Child"})
    payload = {"title": "Group", "request_id": str(uuid4()), "item_id": child["id"], "membership": {"expected_revision": child["revision"]}}
    group = queue_db.create_epic(payload)
    membership(db.get(child["id"]), parent=group)
    assert queue_db.create_epic(payload)["id"] == group["id"]
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT parent_epic_id FROM action_item_queue_entries WHERE action_item_id=%s", (child["id"],))
        assert cursor.fetchone() == (None,)
    with pytest.raises(db.Conflict):
        queue_db.create_epic({**payload, "title": "Different"})


def test_group_snapshot_blocks_hidden_membership_but_preserves_unrelated_text():
    child = db.create({"title": "Child"})
    group = epic(item=child)
    saved = db.get(child["id"])
    db.update(saved["id"], {"expected_revision": saved["revision"], "title": "Edited concurrently"})
    anchor = db.create({"title": "Anchor"})
    queue_db.move({"source": root_ref(group, "epic"), "after": root_ref(anchor)})
    assert db.get(child["id"])["title"] == "Edited concurrently"
    group = current(group["id"])
    membership(db.create({"title": "Hidden"}), destination=group)
    with pytest.raises(db.Conflict, match="changed"):
        queue_db.remove_epic(group["id"], {"expected_revision": group["revision"], "cohort": group["cohort"]})


def test_child_moves_and_legacy_cross_scope_guard():
    first = db.create({"title": "Root"})
    group = epic()
    children = []
    for title in ("One", "Two", "Three"):
        children.append(membership(db.create({"title": title}), destination=current(group["id"])))
    group = current(group["id"])
    queue_db.move({"source": root_ref(children[2]), "parent": ref(group), "before": root_ref(children[0])})
    assert flat_ids() == [first["id"], children[2]["id"], children[0]["id"], children[1]["id"]]
    with pytest.raises(db.Conflict, match="different Epic scopes"):
        db.move(first["id"], {"expected_revision": first["revision"], "after_id": children[0]["id"]})


def test_atomic_remove_rollback(monkeypatch):
    child = db.create({"title": "Child"})
    group = epic(item=child)
    original = queue_db._bump_items
    def broken(*args):
        original(*args)
        raise RuntimeError("Injected failure")
    monkeypatch.setattr(queue_db, "_bump_items", broken)
    with pytest.raises(RuntimeError, match="Injected"):
        queue_db.remove_epic(group["id"], {"expected_revision": group["revision"], "cohort": group["cohort"]})
    assert current(group["id"])["cohort"] == group["cohort"]
    assert current(group["id"])["total_count"] == 1


def test_concurrent_membership_writers_one_wins():
    child = db.create({"title": "Child"})
    groups = [epic("One"), epic("Two")]
    def write(group):
        try:
            membership(child, destination=group)
            return "saved"
        except db.Conflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(write, groups)) == ["conflict", "saved"]


def test_database_rejects_missing_entries_and_nested_epics():
    with pytest.raises(psycopg2.IntegrityError):
        with get_connection() as conn, conn.cursor() as cursor:
            cursor.execute("INSERT INTO action_items(title) VALUES('Missing entry')")
    first, second = epic("One"), epic("Two")
    with pytest.raises(psycopg2.IntegrityError):
        with get_connection() as conn, conn.cursor() as cursor:
            cursor.execute("UPDATE action_item_queue_entries SET parent_epic_id=%s WHERE epic_id=%s", (first["id"], second["id"]))


@pytest.mark.parametrize("other_operation", ["remove", "complete", "delete"])
def test_group_move_and_structural_member_write_have_one_winner(other_operation):
    from threading import Barrier

    anchor = db.create({"title": "Root"})
    child = db.create({"title": "Child", "description": "Preserve this"})
    group = epic(item=child)
    child = db.get(child["id"])
    ready = Barrier(2)

    def write(operation):
        ready.wait(timeout=5)
        try:
            operation()
            return "saved"
        except (db.Conflict, db.NotFound):
            return "conflict"

    def other():
        if other_operation == "remove":
            queue_db.remove_epic(group["id"], {"expected_revision": group["revision"], "cohort": group["cohort"]})
        elif other_operation == "complete":
            db.update(child["id"], {"expected_revision": child["revision"], "status": "completed"})
        else:
            db.delete(child["id"], {"expected_revision": child["revision"]})

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(write, lambda: queue_db.move({"source": root_ref(group, "epic"), "before": root_ref(anchor)})), executor.submit(write, other)]
        assert sorted(future.result(timeout=10) for future in futures) == ["conflict", "saved"]
    assert_action_item_queue()


def test_completed_members_unwrap_and_reopen_as_standalone_without_lost_content():
    group = epic()
    task = membership(db.create({"title": "Keep", "status": "completed", "description": "Original"}), destination=group)
    group = current(group["id"])
    queue_db.remove_epic(group["id"], {"expected_revision": group["revision"], "cohort": group["cohort"]})
    task = db.get(task["id"])
    assert task["status"] == "completed" and task["description"] == "Original"
    reopened = db.update(task["id"], {"expected_revision": task["revision"], "status": "open"})
    assert reopened["priority"] == 1
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT parent_epic_id FROM action_item_queue_entries WHERE action_item_id=%s", (task["id"],))
        assert cursor.fetchone() == (None,)
