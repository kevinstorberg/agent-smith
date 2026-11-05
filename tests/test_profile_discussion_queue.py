from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest

from services.action_items import db
from services.db import get_connection
from services.meetings import profile_db
from tests.test_action_items import action_items_empty as action_items_empty


@pytest.fixture
def owners():
    profiles = [
        profile_db.create_profile(name) for name in ("Discussion A", "Discussion B")
    ]
    yield profiles
    with get_connection() as connection, connection.cursor() as cursor:
        ids = tuple(profile["id"] for profile in profiles)
        cursor.execute("DELETE FROM action_items WHERE profile_id IN %s", (ids,))
        cursor.execute(
            "DELETE FROM participant_profiles WHERE merged_into IN %s", (ids,)
        )
        cursor.execute("DELETE FROM participant_profiles WHERE id IN %s", (ids,))


def queues(owners):
    return {
        "global": db.Queue(None),
        "a": db.profile_queue(owners[0]["id"]),
        "b": db.profile_queue(owners[1]["id"]),
    }


def snapshot(queue):
    listed = queue.list_items({"status": "all", "sort": "title"})
    return listed, [queue.get(item["id"]) for item in listed["items"]]


def assert_dense(queue, expected):
    listed = queue.list_items({"limit": 100})
    assert listed["total"] == len(expected)
    assert [item["id"] for item in listed["items"]] == expected
    assert [item["priority"] for item in listed["items"]] == list(
        range(1, len(expected) + 1)
    )
    return listed


@pytest.mark.parametrize("selected", ["global", "a", "b"])
def test_profile_discussion_queue_lifecycle_preserves_other_queues(owners, selected):
    scoped = queues(owners)
    tasks = {
        name: [
            queue.create(
                {
                    "title": f"{name} task {index}",
                    "description": "Shared needle",
                    "tags": ["Prep"],
                }
            )
            for index in range(4)
        ]
        for name, queue in scoped.items()
    }
    protected = {
        name: snapshot(queue) for name, queue in scoped.items() if name != selected
    }
    queue, records = scoped[selected], tasks[selected]
    profile_before = [
        profile_db.get_profile(profile["id"], include_evidence=False)
        for profile in owners
    ]

    def unchanged():
        for name, before in protected.items():
            assert snapshot(scoped[name]) == before

    listed = queue.list_items(
        {"q": "needle", "tags": ["prep"], "limit": 2, "offset": 1}
    )
    assert listed["total"] == 4 and len(listed["items"]) == 2
    assert all(item["title"].startswith(selected + " ") for item in listed["items"])
    assert "description" not in listed["items"][0]
    for record in records:
        assert queue.get(record["id"]) == record
        if selected == "global":
            assert "profile_id" not in record and "profile_id" not in listed
        else:
            assert record["profile_id"] == listed["profile_id"] == queue.profile_id
    unchanged()

    edited = queue.update(
        records[1]["id"],
        {"expected_revision": 1, "description": "Edited detail", "tags": []},
    )
    assert (
        edited["revision"] == 2
        and edited["description"] == "Edited detail"
        and edited["tags"] == []
    )
    unchanged()
    moved = queue.move(
        records[3]["id"], {"expected_revision": 1, "before_id": records[0]["id"]}
    )
    assert_dense(queue, [records[index]["id"] for index in (3, 0, 1, 2)])
    assert moved["revision"] == 2 and queue.get(records[0]["id"])["revision"] == 1
    unchanged()
    completed = queue.update(
        records[1]["id"], {"expected_revision": 2, "status": "completed"}
    )
    assert completed["completed_at"] and completed["priority"] is None
    assert_dense(queue, [records[index]["id"] for index in (3, 0, 2)])
    unchanged()
    reopened = queue.update(completed["id"], {"expected_revision": 3, "status": "open"})
    assert reopened["completed_at"] is None and reopened["priority"] == 4
    unchanged()
    queue.delete(records[0]["id"], {"expected_revision": 1})
    with pytest.raises(db.NotFound):
        queue.get(records[0]["id"])
    assert_dense(queue, [records[index]["id"] for index in (3, 2, 1)])
    unchanged()
    assert [
        profile_db.get_profile(profile["id"], include_evidence=False)
        for profile in owners
    ] == profile_before


@pytest.mark.parametrize("selected", ["global", "a", "b"])
def test_profile_discussion_queue_rejects_every_cross_queue_read_write_and_anchor(
    owners, selected
):
    scoped = queues(owners)
    tasks = {name: queue.create({"title": name}) for name, queue in scoped.items()}
    before = {name: snapshot(queue) for name, queue in scoped.items()}
    queue = scoped[selected]
    for other, foreign in tasks.items():
        if other == selected:
            continue
        operations = [
            lambda: queue.get(foreign["id"]),
            lambda: queue.update(
                foreign["id"], {"expected_revision": 1, "title": "Wrong owner"}
            ),
            lambda: queue.delete(foreign["id"], {"expected_revision": 1}),
            lambda: queue.move(
                foreign["id"],
                {"expected_revision": 1, "before_id": tasks[selected]["id"]},
            ),
        ]
        for operation in operations:
            with pytest.raises(db.NotFound):
                operation()
        with pytest.raises(db.Conflict, match="still be open"):
            queue.move(
                tasks[selected]["id"],
                {"expected_revision": 1, "after_id": foreign["id"]},
            )
    assert {name: snapshot(queue) for name, queue in scoped.items()} == before


@pytest.mark.parametrize("selected", ["global", "a", "b"])
def test_profile_discussion_queue_creation_replay_is_scoped_and_keeps_deleted_receipts(
    owners, selected
):
    scoped = queues(owners)
    queue = scoped[selected]
    payload = {"title": "Frozen input", "request_id": str(uuid4())}
    created = queue.create(payload)
    edited = queue.update(
        created["id"],
        {"expected_revision": 1, "title": "Saved later", "status": "completed"},
    )
    assert queue.create(payload) == edited
    for name, other in scoped.items():
        if name == selected:
            continue
        with pytest.raises(db.Conflict, match="different queue"):
            other.create(payload)
        assert other.list_items()["total"] == 0
    with pytest.raises(db.Conflict, match="different input"):
        queue.create({**payload, "title": "Changed replay"})
    queue.delete(created["id"], {"expected_revision": edited["revision"]})
    with pytest.raises(db.Conflict, match="deleted action item"):
        queue.create(payload)
    for name, other in scoped.items():
        if name != selected:
            with pytest.raises(db.Conflict, match="different queue"):
                other.create(payload)


def test_profile_discussion_queue_is_explicit_and_empty_alias_reads_return_canonical_owner(
    owners,
):
    with pytest.raises(TypeError):
        db.Queue()
    for invalid in (None, 1, "not-a-profile"):
        with pytest.raises((TypeError, ValueError)):
            db.profile_queue(invalid)
    owner = owners[0]
    linked = profile_db.link_alias(
        owner["id"], f"prep-{uuid4().hex}@example.test", owner["revision"]
    )
    alias = linked["aliases"][0]["id"]
    queue = db.profile_queue(alias)
    assert queue.list_items() == {"items": [], "total": 0, "profile_id": owner["id"]}
    topic = queue.create({"title": "Ask about staffing"})
    assert topic["profile_id"] == owner["id"]
    assert db.profile_queue(owner["id"]).get(topic["id"]) == topic
    assert db.list_items() == {"items": [], "total": 0}
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("DELETE FROM participant_profiles WHERE id=%s", (alias,))


def test_profile_discussion_queue_keeps_pre_scope_creation_payload_replays_compatible():
    from psycopg2.extras import Json

    payload = {
        "title": "Legacy task",
        "description": "Original details",
        "project": None,
        "tags": [],
        "status": "open",
    }
    request_id = str(uuid4())
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO action_items(title,description,project_id,tags,status,sort_key,request_id,create_payload)
            VALUES(%s,%s,%s,%s,%s,1,%s,%s) RETURNING id""",
            (
                payload["title"],
                payload["description"],
                payload["project"],
                payload["tags"],
                payload["status"],
                request_id,
                Json(payload),
            ),
        )
        item_id = cursor.fetchone()[0]
    current = db.get(item_id)
    assert db.create({**payload, "request_id": request_id}) == current
    assert "profile_id" not in current


@pytest.mark.parametrize("deleted", [False, True])
def test_profile_discussion_queue_rejects_missing_or_deleted_owners_for_all_operations(
    owners, deleted
):
    owner_id = str(uuid4())
    if deleted:
        owner_id = owners[0]["id"]
        profile_db.delete_profile(owner_id, owners[0]["revision"])
    queue = db.profile_queue(owner_id)
    operations = [
        lambda: queue.list_items(),
        lambda: queue.create({"title": "Must not appear"}),
        lambda: queue.get(1),
        lambda: queue.update(1, {"expected_revision": 1, "title": "Must not save"}),
        lambda: queue.delete(1, {"expected_revision": 1}),
        lambda: queue.move(1, {"expected_revision": 1, "before_id": 2}),
    ]
    for operation in operations:
        with pytest.raises(db.NotFound, match="profile"):
            operation()
    assert db.list_items() == {"items": [], "total": 0}


def test_profile_discussion_queue_page_bottom_move_preserves_hidden_rows_and_other_queues(
    owners,
):
    queue = db.profile_queue(owners[0]["id"])
    records = [queue.create({"title": f"Topic {index:02}"}) for index in range(25)]
    global_item = db.create({"title": "Global task"})
    second = db.profile_queue(owners[1]["id"]).create({"title": "Other profile topic"})
    before = {item["id"]: queue.get(item["id"]) for item in records}
    first_page = queue.list_items({"limit": 10})["items"]
    moved = queue.move(
        records[0]["id"], {"expected_revision": 1, "after_id": first_page[-1]["id"]}
    )
    assert moved["priority"] == 10
    assert_dense(
        queue, [item["id"] for item in records[1:10] + records[:1] + records[10:]]
    )
    for item in records[1:]:
        after = queue.get(item["id"])
        assert (after["revision"], after["updated_at"]) == (
            before[item["id"]]["revision"],
            before[item["id"]]["updated_at"],
        )
    assert db.get(global_item["id"]) == global_item
    assert db.profile_queue(owners[1]["id"]).get(second["id"]) == second


def test_profile_discussion_queue_simultaneous_writers_use_item_revision_and_dense_positions(
    owners,
):
    queue = db.profile_queue(owners[0]["id"])
    payload = {"title": "One request", "request_id": str(uuid4())}
    barrier = Barrier(2)

    def create():
        barrier.wait(timeout=5)
        return queue.create(payload)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            future.result(timeout=10)
            for future in [executor.submit(create), executor.submit(create)]
        ]
    assert results[0] == results[1]
    barrier = Barrier(2)

    def update(title):
        barrier.wait(timeout=5)
        try:
            return queue.update(
                results[0]["id"], {"expected_revision": 1, "title": title}
            )
        except db.Conflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            future.result(timeout=10)
            for future in [
                executor.submit(update, "First"),
                executor.submit(update, "Second"),
            ]
        ]
    assert sum(result is not None for result in results) == 1
    assert queue.list_items()["items"][0]["revision"] == 2
    assert_dense(queue, [next(result["id"] for result in results if result)])
