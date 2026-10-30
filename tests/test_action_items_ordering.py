from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Barrier, Event
from uuid import uuid4

import psycopg2
import pytest

from services.action_items import db
from services.db import get_connection
from tests.test_action_items import action_items_empty as action_items_empty


def state():
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT id,sort_key,revision,updated_at FROM action_items WHERE deleted_at IS NULL AND status='open' ORDER BY sort_key,id")
        rows = cursor.fetchall()
    assert [row[1] for row in rows] == list(range(1, len(rows) + 1))
    return rows


def tasks(count=6):
    return [db.create({"title": f"Task {index:02}"}) for index in range(count)]


def test_action_items_page_bottom_move_preserves_all_hidden_items_and_unrelated_revisions():
    created = tasks(25)
    before = state()
    first_page = db.list_items({"limit": 10})["items"]
    moved = db.move(created[0]["id"], {"expected_revision": 1, "after_id": first_page[-1]["id"]})
    after = state()
    assert [row[0] for row in after] == [item["id"] for item in created[1:10] + created[:1] + created[10:]]
    assert [(row[0], row[2:]) for row in before[1:]] == [(row[0], row[2:]) for row in after if row[0] != moved["id"]]
    assert moved["revision"] == 2


@pytest.mark.parametrize("source,anchor,side,expected", [
    (0, 4, "before_id", [1, 2, 3, 0, 4, 5]),
    (0, 4, "after_id", [1, 2, 3, 4, 0, 5]),
    (5, 1, "before_id", [0, 5, 1, 2, 3, 4]),
    (5, 1, "after_id", [0, 1, 5, 2, 3, 4]),
])
def test_action_items_relative_move_both_directions(source, anchor, side, expected):
    created = tasks()
    db.move(created[source]["id"], {"expected_revision": 1, side: created[anchor]["id"]})
    assert [row[0] for row in state()] == [created[index]["id"] for index in expected]


def test_action_items_live_anchor_noop_and_source_revision():
    created = tasks()
    db.move(created[1]["id"], {"expected_revision": 1, "after_id": created[4]["id"]})
    moved = db.move(created[0]["id"], {"expected_revision": 1, "after_id": created[1]["id"]})
    assert [row[0] for row in state()] == [created[index]["id"] for index in [2, 3, 4, 1, 0, 5]]
    assert db.move(moved["id"], {"expected_revision": moved["revision"], "after_id": created[1]["id"]}) == moved
    with pytest.raises(db.Conflict, match="changed"):
        db.move(moved["id"], {"expected_revision": 1, "before_id": created[2]["id"]})


def test_action_items_membership_transitions_compact_and_reopen_at_end():
    created = tasks()
    completed = db.update(created[2]["id"], {"expected_revision": 1, "status": "completed"})
    db.delete(created[1]["id"], {"expected_revision": 1})
    for anchor in (created[1], completed):
        with pytest.raises(db.Conflict, match="still be open"):
            db.move(created[0]["id"], {"expected_revision": 1, "before_id": anchor["id"]})
    with pytest.raises(db.Conflict):
        db.move(completed["id"], {"expected_revision": completed["revision"], "before_id": created[0]["id"]})
    reopened = db.update(completed["id"], {"expected_revision": completed["revision"], "status": "open"})
    assert reopened["completed_at"] is None
    assert [row[0] for row in state()] == [created[index]["id"] for index in [0, 3, 4, 5, 2]]


def test_action_items_ordering_failure_rolls_back_entire_queue(monkeypatch):
    created = tasks()
    before = state()
    original = db._read

    def fail_after_order_shift(cursor, item_id):
        original(cursor, item_id)
        raise RuntimeError("Injected move failure")

    monkeypatch.setattr(db, "_read", fail_after_order_shift)
    with pytest.raises(RuntimeError, match="Injected"):
        db.move(created[0]["id"], {"expected_revision": 1, "after_id": created[4]["id"]})
    assert state() == before


def test_action_items_simultaneous_creates_and_replays_are_dense():
    barrier = Barrier(5)
    request_id = str(uuid4())

    def create(index):
        barrier.wait(timeout=5)
        return db.create({"title": "Shared" if index < 2 else f"Task {index}", "request_id": request_id if index < 2 else str(uuid4())})

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(create, index) for index in range(5)]
        results = [future.result(timeout=10) for future in futures]
    assert results[0]["id"] == results[1]["id"]
    assert len(state()) == 4


def test_action_items_simultaneous_stale_writers_do_not_lose_content():
    task = db.create({"title": "Original"})
    barrier = Barrier(2)

    def update(title):
        barrier.wait(timeout=5)
        try:
            return db.update(task["id"], {"expected_revision": 1, "title": title})
        except db.Conflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(update, title) for title in ("First", "Second")]
        results = [future.result(timeout=10) for future in futures]
    assert sum(result is not None for result in results) == 1
    assert db.get(task["id"])["revision"] == 2


def test_action_items_independent_moves_serialize_and_share_content_write_lock():
    created = tasks()
    started = [Event(), Event(), Event()]

    def run(index, operation):
        started[index].set()
        return operation()

    with ThreadPoolExecutor(max_workers=3) as executor:
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (db._WRITE_LOCK,))
            operations = [lambda: db.move(created[0]["id"], {"expected_revision": 1, "after_id": created[2]["id"]}),
                          lambda: db.move(created[5]["id"], {"expected_revision": 1, "before_id": created[3]["id"]}),
                          lambda: db.update(created[4]["id"], {"expected_revision": 1, "description": "Edited"})]
            futures = [executor.submit(run, index, operation) for index, operation in enumerate(operations)]
            assert all(event.wait(timeout=2) for event in started)
            for future in futures:
                with pytest.raises(TimeoutError):
                    future.result(timeout=0.1)
        for future in futures:
            future.result(timeout=10)
    assert [row[0] for row in state()] == [created[index]["id"] for index in [1, 2, 0, 5, 3, 4]]


def test_action_items_lock_wait_is_bounded_and_does_not_mutate():
    task = db.create({"title": "Original"})
    with ThreadPoolExecutor(max_workers=1) as executor:
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (db._WRITE_LOCK,))
            future = executor.submit(db.update, task["id"], {"expected_revision": 1, "title": "Blocked"})
            with pytest.raises(db.Conflict, match="busy"):
                future.result(timeout=8)
    assert db.get(task["id"]) == task


@pytest.mark.parametrize("assignment,value", [("status", "bad"), ("revision", 0), ("title", "\n\t"), ("sort_key", None), ("completed_at", "2026-01-01T00:00:00Z")])
def test_action_items_database_constraints(assignment, value):
    task = db.create({"title": "Valid"})
    with pytest.raises(psycopg2.IntegrityError):
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute(f"UPDATE action_items SET {assignment}=%s WHERE id=%s", (value, task["id"]))
    assert db.get(task["id"]) == task


def test_action_items_rank_uniqueness_is_checked_at_commit():
    first, second = tasks(2)
    executed = False
    with pytest.raises(psycopg2.IntegrityError):
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE action_items SET sort_key=1 WHERE id=%s", (second["id"],))
            executed = True
    assert executed
    assert [row[0] for row in state()] == [first["id"], second["id"]]
