from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event
from uuid import uuid4

import pytest
from psycopg2.extras import RealDictCursor

from services.action_items import db
from services.db import get_connection
from services.meetings import profile_db
from tests.test_action_items import action_items_empty as action_items_empty
from tests.test_profile_discussion_queue import assert_dense, owners as owners, snapshot


def stored_rows():
    with get_connection() as connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SELECT * FROM action_items ORDER BY id")
        return {row["id"]: dict(row) for row in cursor.fetchall()}


def test_profile_discussion_merge_transfers_order_history_receipts_and_alias_replay_atomically(owners):
    source, target = owners
    source_queue, target_queue = db.profile_queue(source["id"]), db.profile_queue(target["id"])
    payload = {"title": "Source first", "request_id": str(uuid4())}
    first = source_queue.create(payload)
    second = source_queue.create({"title": "Source second"})
    completed = source_queue.create({"title": "Already discussed", "status": "completed"})
    deleted_payload = {"title": "Deleted source topic", "request_id": str(uuid4())}
    deleted = source_queue.create(deleted_payload)
    source_queue.delete(deleted["id"], {"expected_revision": 1})
    target_items = [target_queue.create({"title": f"Target {index}"}) for index in range(2)]
    target_queue.create({"title": "Target completed", "status": "completed"})
    global_item = db.create({"title": "Global remains separate"})
    before, global_before = stored_rows(), snapshot(db.Queue(None))

    winner = profile_db.merge_profiles(source["id"], target["id"], source["revision"], target["revision"])

    assert winner["id"] == target["id"]
    assert_dense(target_queue, [item["id"] for item in target_items] + [first["id"], second["id"]])
    assert source_queue.list_items() == target_queue.list_items()
    assert source_queue.list_items()["profile_id"] == target["id"]
    after = stored_rows()
    moved_ids = {first["id"], second["id"], completed["id"], deleted["id"]}
    for item_id, original in before.items():
        current = after[item_id]
        if item_id not in moved_ids:
            assert current == original
            continue
        assert str(current["profile_id"]) == current["scope_key"] == target["id"]
        assert current["revision"] == original["revision"] + 1 and current["updated_at"] > original["updated_at"]
        for key in ("id", "title", "description", "project", "tags", "status", "completed_at", "created_at", "request_id", "create_payload", "deleted_at"):
            assert current[key] == original[key]
    assert after[completed["id"]]["sort_key"] is None and after[deleted["id"]]["sort_key"] is None
    assert snapshot(db.Queue(None)) == global_before and db.get(global_item["id"]) == global_item
    assert source_queue.create(payload) == target_queue.create(payload) == target_queue.get(first["id"])
    with pytest.raises(db.Conflict, match="changed"):
        source_queue.update(first["id"], {"expected_revision": first["revision"], "title": "Stale source draft"})
    with pytest.raises(db.Conflict, match="deleted action item"):
        source_queue.create(deleted_payload)
    with pytest.raises(db.Conflict, match="different queue"):
        db.create(payload)

    profile_db.delete_profile(target["id"], winner["revision"])
    for queue in (source_queue, target_queue):
        with pytest.raises(db.NotFound, match="profile"):
            queue.list_items({"status": "all"})
        with pytest.raises(db.NotFound, match="profile"):
            queue.create(payload)
    for item_id in moved_ids:
        with pytest.raises(db.NotFound):
            db.get(item_id)
    assert stored_rows() == after and snapshot(db.Queue(None)) == global_before


def test_profile_discussion_merge_failure_rolls_back_profile_aliases_and_all_topic_rows(owners, monkeypatch):
    source, target = owners
    source_queue, target_queue = db.profile_queue(source["id"]), db.profile_queue(target["id"])
    topic = source_queue.create({"title": "Source"})
    target_queue.create({"title": "Target"})
    before = stored_rows()
    profiles = [profile_db.get_profile(profile["id"]) for profile in owners]
    original = profile_db._detail

    def fail_after_transfer(cursor, row, **kwargs):
        cursor.execute("SELECT profile_id::text FROM action_items WHERE id=%s", (topic["id"],))
        assert cursor.fetchone()["profile_id"] == target["id"]
        raise RuntimeError("Injected failure after topic transfer")

    monkeypatch.setattr(profile_db, "_detail", fail_after_transfer)
    with pytest.raises(RuntimeError, match="after topic transfer"):
        profile_db.merge_profiles(source["id"], target["id"], source["revision"], target["revision"])
    monkeypatch.setattr(profile_db, "_detail", original)
    assert stored_rows() == before
    assert [profile_db.get_profile(profile["id"]) for profile in owners] == profiles
    assert_dense(source_queue, [topic["id"]])


def test_profile_discussion_merge_lock_timeout_is_profile_conflict_and_keeps_both_queues(owners):
    source, target = owners
    db.profile_queue(source["id"]).create({"title": "Source"})
    db.profile_queue(target["id"]).create({"title": "Target"})
    before = stored_rows()
    with ThreadPoolExecutor(max_workers=1) as executor:
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (db._WRITE_LOCK,))
            blocked = executor.submit(profile_db.merge_profiles, source["id"], target["id"], source["revision"], target["revision"])
            with pytest.raises(profile_db.ProfileRevisionConflict, match="Discussion topics are busy"):
                blocked.result(timeout=8)
    assert stored_rows() == before
    assert profile_db.get_profile(source["id"])["id"] == source["id"]


@pytest.mark.parametrize("operation", ["create", "update"])
def test_profile_discussion_writer_waiting_on_merge_resolves_canonical_owner_or_conflicts(owners, monkeypatch, operation):
    source, target = owners
    source_queue, target_queue = db.profile_queue(source["id"]), db.profile_queue(target["id"])
    topic = source_queue.create({"title": "Source"})
    target_topic = target_queue.create({"title": "Target"})
    transferred, release, started = Event(), Event(), Event()
    original = db.merge_profile_queue

    def hold_after_transfer(cursor, source_id, target_id):
        original(cursor, source_id, target_id)
        transferred.set()
        assert release.wait(timeout=5)

    monkeypatch.setattr(db, "merge_profile_queue", hold_after_transfer)

    def write():
        started.set()
        if operation == "create":
            return source_queue.create({"title": "Created after merge", "request_id": str(uuid4())})
        return source_queue.update(topic["id"], {"expected_revision": topic["revision"], "title": "Stale source edit"})

    with ThreadPoolExecutor(max_workers=2) as executor:
        merging = executor.submit(profile_db.merge_profiles, source["id"], target["id"], source["revision"], target["revision"])
        try:
            assert transferred.wait(timeout=3)
            writing = executor.submit(write)
            assert started.wait(timeout=2)
            with pytest.raises(TimeoutError):
                writing.result(timeout=0.1)
        finally:
            release.set()
        assert merging.result(timeout=5)["id"] == target["id"]
        expected = [target_topic["id"], topic["id"]]
        if operation == "create":
            added = writing.result(timeout=5)
            assert added["profile_id"] == target["id"]
            expected.append(added["id"])
        else:
            with pytest.raises(db.Conflict, match="changed"):
                writing.result(timeout=5)
            assert target_queue.get(topic["id"])["title"] == "Source"
    assert_dense(source_queue, expected)
    assert db.list_items() == {"items": [], "total": 0}


def test_profile_discussion_writer_waiting_on_delete_cannot_create_under_tombstoned_owner(owners, monkeypatch):
    source = owners[0]
    queue = db.profile_queue(source["id"])
    topic = queue.create({"title": "Existing"})
    locked, release, started = Event(), Event(), Event()
    original = profile_db._editable

    def hold_owner(cursor, profile_id, expected_revision):
        row = original(cursor, profile_id, expected_revision)
        locked.set()
        assert release.wait(timeout=5)
        return row

    monkeypatch.setattr(profile_db, "_editable", hold_owner)

    def create():
        started.set()
        return queue.create({"title": "Must not resurrect owner"})

    with ThreadPoolExecutor(max_workers=2) as executor:
        deleting = executor.submit(profile_db.delete_profile, source["id"], source["revision"])
        try:
            assert locked.wait(timeout=3)
            writing = executor.submit(create)
            assert started.wait(timeout=2)
            with pytest.raises(TimeoutError):
                writing.result(timeout=0.1)
        finally:
            release.set()
        deleting.result(timeout=5)
        with pytest.raises(db.NotFound, match="profile"):
            writing.result(timeout=5)
    assert set(stored_rows()) == {topic["id"]}
    assert db.list_items() == {"items": [], "total": 0}


def test_profile_discussion_read_keeps_one_owner_and_queue_snapshot_across_merge(owners, monkeypatch):
    source, target = owners
    source_queue, target_queue = db.profile_queue(source["id"]), db.profile_queue(target["id"])
    source_topic = source_queue.create({"title": "Source"})
    target_topic = target_queue.create({"title": "Target"})
    resolved, release = Event(), Event()
    original = db._resolve_scope
    paused = False

    def pause_after_owner(cursor, profile_id):
        nonlocal paused
        scope = original(cursor, profile_id)
        if profile_id == source["id"] and not paused:
            paused = True
            resolved.set()
            assert release.wait(timeout=5)
        return scope

    monkeypatch.setattr(db, "_resolve_scope", pause_after_owner)
    with ThreadPoolExecutor(max_workers=1) as executor:
        reading = executor.submit(source_queue.list_items)
        try:
            assert resolved.wait(timeout=3)
            profile_db.merge_profiles(source["id"], target["id"], source["revision"], target["revision"])
        finally:
            release.set()
        frozen = reading.result(timeout=5)
    assert frozen["profile_id"] == source["id"] and frozen["total"] == 1
    assert [item["id"] for item in frozen["items"]] == [source_topic["id"]]
    live = source_queue.list_items()
    assert live["profile_id"] == target["id"] and live["total"] == 2
    assert [item["id"] for item in live["items"]] == [target_topic["id"], source_topic["id"]]
