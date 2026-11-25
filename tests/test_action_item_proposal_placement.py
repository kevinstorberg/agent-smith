from concurrent.futures import ThreadPoolExecutor
from functools import partial

import pytest

from services.action_items import db as tasks, proposals, queue_db
from services.api.models.action_item_proposal import get_proposal
from services.db import get_connection
from tests.action_item_queue_helpers import assert_action_item_queue
from tests.test_action_item_epics import current, epic, membership, ref, root_ref
from tests.test_action_item_proposals import (
    candidate,
    client as client,
    empty_task_proposals as empty_task_proposals,
    source as source,
    source_factory as source_factory,
)
from tests.test_proposal_decision_concurrency import (
    decide,
    wait_for_block,
    watch_decision_connections,
)


@pytest.fixture(autouse=True)
def valid_queue(empty_task_proposals):
    yield
    assert_action_item_queue()


def placement(destination, parent=None):
    return {
        "placement": {
            "expected_parent": ref(parent) if parent else None,
            "destination": ref(destination),
        }
    }


def parent_and_position(item_id):
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT parent_epic_id,sort_key FROM action_item_queue_entries WHERE action_item_id=%s",
            (item_id,),
        )
        return cursor.fetchone()


def stored_state():
    with get_connection() as conn, conn.cursor() as cursor:
        result = {}
        for table in (
            "action_items",
            "action_item_queue_entries",
            "action_item_epics",
            "action_item_proposals",
            "action_item_proposal_payloads",
            "action_item_proposal_receipts",
        ):
            cursor.execute(
                f"SELECT to_jsonb(row) FROM {table} row ORDER BY to_jsonb(row)::text"
            )
            result[table] = cursor.fetchall()
        return result


@pytest.mark.parametrize("status", ["open", "completed"])
def test_approval_atomically_creates_in_reviewed_epic(source, client, status):
    destination = epic()
    pending = proposals.stage_and_persist(
        source,
        candidate(
            changes={
                "title": "Review design",
                "description": "Details",
                "status": status,
            }
        ),
    )
    body = placement(destination)
    response = client.post(f"/action-item-proposals/{pending['id']}/approve", json=body)
    assert response.status_code == 200, response.text
    approved = response.json()
    item = tasks.get(approved["applied_ref"]["action_item_id"])
    assert approved["status"] == "approved"
    assert approved["applied_ref"]["placement"] == body["placement"]
    assert item["title"] == "Review design" and item["description"] == "Details"
    assert item["status"] == status and item["revision"] == 2
    assert parent_and_position(item["id"]) == (
        destination["id"],
        1 if status == "open" else None,
    )
    assert current(destination["id"])["total_count"] == 1


@pytest.mark.parametrize("same_parent", [False, True])
@pytest.mark.parametrize("before,after", [("open", "completed"), ("completed", "open")])
def test_status_update_and_placement_do_not_invalidate_their_own_review(
    source, before, after, same_parent
):
    parent = epic("Original")
    item = membership(
        tasks.create({"title": "Review design", "status": before}), destination=parent
    )
    parent = current(parent["id"])
    destination = parent if same_parent else epic("Next")
    pending = proposals.stage_and_persist(
        source, candidate(target=item, changes={"status": after})
    )
    approved = proposals.promote_proposal(pending["id"], placement(destination, parent))
    assert approved["applied_ref"]["action_item_id"] == item["id"]
    saved = tasks.get(item["id"])
    assert saved["title"] == item["title"] and saved["status"] == after
    assert parent_and_position(item["id"]) == (
        destination["id"],
        1 if after == "open" else None,
    )
    assert saved["revision"] == item["revision"] + (1 if same_parent else 2)


@pytest.mark.parametrize("body", [None, {}, {"placement": None}])
def test_ordinary_approval_preserves_update_membership(source, body):
    parent = epic()
    item = membership(tasks.create({"title": "Review design"}), destination=parent)
    pending = proposals.stage_and_persist(
        source, candidate(target=item, changes={"description": "Approved"})
    )
    position = parent_and_position(item["id"])
    approved = proposals.promote_proposal(pending["id"], body)
    assert approved["applied_ref"] == {"action_item_id": item["id"]}
    assert parent_and_position(item["id"]) == position
    assert tasks.get(item["id"])["revision"] == item["revision"] + 1


def test_same_destination_keeps_existing_child_position(source):
    parent = epic()
    items = [
        membership(
            tasks.create({"title": str(index)}), destination=current(parent["id"])
        )
        for index in range(3)
    ]
    item = items[1]
    parent = current(parent["id"])
    pending = proposals.stage_and_persist(
        source, candidate(target=item, changes={"description": "Approved"})
    )
    position = parent_and_position(item["id"])
    proposals.promote_proposal(pending["id"], placement(parent, parent))
    assert parent_and_position(item["id"]) == position
    assert current(parent["id"]) == parent


@pytest.mark.parametrize("changed", ["parent", "destination", "removed_destination"])
def test_stale_membership_review_rolls_back_entire_approval(source, client, changed):
    parent = epic("Original")
    item = membership(tasks.create({"title": "Review design"}), destination=parent)
    parent = current(parent["id"])
    destination = epic("Next")
    pending = proposals.stage_and_persist(
        source, candidate(target=item, changes={"status": "completed"})
    )
    body = placement(destination, parent)
    if changed == "removed_destination":
        queue_db.remove_epic(
            destination["id"],
            {
                "expected_revision": destination["revision"],
                "cohort": destination["cohort"],
            },
        )
    else:
        altered = parent if changed == "parent" else destination
        membership(tasks.create({"title": "Hidden sibling"}), destination=altered)
    before = stored_state()
    response = client.post(f"/action-item-proposals/{pending['id']}/approve", json=body)
    assert response.status_code == 409, response.text
    assert stored_state() == before


@pytest.mark.parametrize("status", ["open", "completed"])
def test_duplicate_create_does_not_move_an_existing_grouped_item(
    source, client, status
):
    pending = proposals.stage_and_persist(source, candidate())
    parent = epic("Existing")
    duplicate = membership(
        tasks.create({"title": "Send the design document", "status": status}),
        destination=parent,
    )
    destination = epic("Next")
    before = stored_state()
    response = client.post(
        f"/action-item-proposals/{pending['id']}/approve", json=placement(destination)
    )
    assert response.status_code == 409 and "equivalent" in response.text
    assert stored_state() == before
    assert parent_and_position(duplicate["id"])[0] == parent["id"]


def test_new_item_cannot_claim_an_existing_parent(source, client):
    pending = proposals.stage_and_persist(source, candidate())
    parent, destination = epic("Original"), epic("Next")
    before = stored_state()
    response = client.post(
        f"/action-item-proposals/{pending['id']}/approve",
        json=placement(destination, parent),
    )
    assert response.status_code == 409
    assert stored_state() == before


def test_review_reports_live_parent_without_taking_write_locks(
    source, client, monkeypatch
):
    parent = epic()
    item = membership(tasks.create({"title": "Review design"}), destination=parent)
    pending = proposals.stage_and_persist(
        source, candidate(target=item, changes={"description": "Approved"})
    )
    membership(
        tasks.create({"title": "Hidden completed sibling", "status": "completed"}),
        destination=current(parent["id"]),
    )
    parent = current(parent["id"])
    original = queue_db.parent_snapshots

    def snapshots(cursor, item_ids):
        cursor.execute("SHOW transaction_isolation")
        assert cursor.fetchone()["transaction_isolation"] == "repeatable read"
        return original(cursor, item_ids)

    def forbidden(*args, **kwargs):
        pytest.fail("Proposal inspection must not use a FOR UPDATE membership helper")

    monkeypatch.setattr(queue_db, "parent_snapshots", snapshots)
    monkeypatch.setattr(queue_db, "task_entry", forbidden)
    monkeypatch.setattr(queue_db, "_epic", forbidden)
    with get_connection() as blocker, blocker.cursor() as cursor:
        tasks.acquire_write_lock(cursor)
        cursor.execute(
            "SELECT id FROM action_item_epics WHERE id=%s FOR UPDATE", (parent["id"],)
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                client.get, f"/action-item-proposals/{pending['id']}"
            )
            response = future.result(timeout=2)
    assert response.status_code == 200
    assert response.json()["current_parent"] == ref(parent)
    assert response.json()["current_parent_title"] == parent["title"]
    assert response.json()["target_stale"] is False
    assert client.get("/action-item-proposals").json()["items"][0][
        "current_parent"
    ] == ref(parent)
    assert (
        client.get("/action-item-proposals").json()["items"][0]["current_parent_title"]
        == parent["title"]
    )


def test_review_parent_name_and_reference_share_the_read_snapshot(
    source, client, monkeypatch
):
    parent = epic("Reviewed Epic")
    item = membership(tasks.create({"title": "Review design"}), destination=parent)
    parent = current(parent["id"])
    pending = proposals.stage_and_persist(
        source, candidate(target=item, changes={"description": "Approved"})
    )
    original = queue_db._catalog
    renamed = False

    def rename_before_catalog(cursor):
        nonlocal renamed
        if not renamed:
            renamed = True
            queue_db.rename_epic(
                parent["id"],
                {
                    "expected_revision": parent["revision"],
                    "title": "Renamed after review began",
                },
            )
        return original(cursor)

    monkeypatch.setattr(queue_db, "_catalog", rename_before_catalog)
    response = client.get(f"/action-item-proposals/{pending['id']}")
    assert response.status_code == 200, response.text
    assert renamed
    assert response.json()["current_parent"] == ref(parent)
    assert response.json()["current_parent_title"] == "Reviewed Epic"
    assert set(response.json()["current_parent"]) == {
        "id",
        "expected_revision",
        "cohort",
    }
    assert current(parent["id"])["title"] == "Renamed after review began"
    refreshed = client.get(f"/action-item-proposals/{pending['id']}").json()
    assert refreshed["current_parent_title"] == "Renamed after review began"
    assert refreshed["current_parent"]["expected_revision"] > parent["revision"]


@pytest.mark.parametrize("action", ["create", "update"])
def test_review_without_an_epic_has_no_parent_name(source, client, action):
    item = tasks.create({"title": "Review design"}) if action == "update" else None
    pending = proposals.stage_and_persist(
        source,
        candidate(target=item, changes={"description": "Approved"})
        if item
        else candidate(),
    )
    response = client.get(f"/action-item-proposals/{pending['id']}")
    assert response.status_code == 200, response.text
    assert response.json()["current_parent"] is None
    assert response.json()["current_parent_title"] is None


def test_placement_replay_is_frozen_after_later_edit_movement_and_deletion(source):
    destination = epic()
    pending = proposals.stage_and_persist(source, candidate())
    body = placement(destination)
    approved = proposals.promote_proposal(pending["id"], body)
    item = tasks.get(approved["applied_ref"]["action_item_id"])
    item = tasks.update(
        item["id"], {"expected_revision": item["revision"], "title": "Later edit"}
    )
    item = membership(item, parent=current(destination["id"]))
    now = current(destination["id"])
    queue_db.remove_epic(
        now["id"], {"expected_revision": now["revision"], "cohort": now["cohort"]}
    )
    tasks.delete(item["id"], {"expected_revision": item["revision"]})
    before = stored_state()
    assert proposals.promote_proposal(pending["id"], body) == approved
    assert stored_state() == before


def test_missing_parent_normalizes_to_null_for_create_and_frozen_replay(source, client):
    destination = epic()
    pending = proposals.stage_and_persist(source, candidate())
    body = {"placement": {"destination": ref(destination)}}
    response = client.post(f"/action-item-proposals/{pending['id']}/approve", json=body)
    assert response.status_code == 200
    approved = response.json()
    assert approved["applied_ref"]["placement"] == placement(destination)["placement"]
    before = stored_state()
    assert proposals.promote_proposal(pending["id"], placement(destination)) == approved
    assert stored_state() == before


def test_missing_parent_does_not_authorize_moving_a_grouped_update(source, client):
    parent = epic("Original")
    item = membership(tasks.create({"title": "Review design"}), destination=parent)
    destination = epic("Next")
    pending = proposals.stage_and_persist(
        source, candidate(target=item, changes={"description": "Approved"})
    )
    before = stored_state()
    response = client.post(
        f"/action-item-proposals/{pending['id']}/approve",
        json={"placement": {"destination": ref(destination)}},
    )
    assert response.status_code == 409 and "changed Epic" in response.text
    assert stored_state() == before


@pytest.mark.parametrize("changed", ["destination", "receipt", "omitted"])
def test_approved_placement_rejects_a_different_replay(source, changed):
    destination = epic()
    pending = proposals.stage_and_persist(source, candidate())
    body = placement(destination)
    proposals.promote_proposal(pending["id"], body)
    if changed == "destination":
        body = placement(epic("Other"))
    elif changed == "receipt":
        body = placement(current(destination["id"]))
    else:
        body = {}
    before = stored_state()
    with pytest.raises(
        proposals.ProposalConflictError, match="different Epic placement"
    ):
        proposals.promote_proposal(pending["id"], body)
    assert stored_state() == before


def test_legacy_approval_replays_without_placement_and_rejects_later_grouping(source):
    pending = proposals.stage_and_persist(source, candidate())
    approved = proposals.promote_proposal(pending["id"])
    assert "placement" not in approved["applied_ref"]
    assert proposals.promote_proposal(pending["id"], {"placement": None}) == approved
    with pytest.raises(
        proposals.ProposalConflictError, match="different Epic placement"
    ):
        proposals.promote_proposal(pending["id"], placement(epic()))


@pytest.mark.parametrize("update", [False, True])
def test_record_failure_rolls_back_task_placement_and_all_receipts(
    source, monkeypatch, update
):
    parent = epic("Original")
    item = (
        membership(tasks.create({"title": "Review design"}), destination=parent)
        if update
        else None
    )
    parent = current(parent["id"])
    destination = epic("Next")
    pending = proposals.stage_and_persist(
        source,
        candidate(target=item, changes={"status": "completed"} if update else None),
    )
    body = placement(destination, parent if update else None)
    before = stored_state()
    record = proposals._record_decision

    def fail(*args, **kwargs):
        record(*args, **kwargs)
        raise RuntimeError("Synthetic post-placement decision failure")

    with monkeypatch.context() as patch:
        patch.setattr(proposals, "_record_decision", fail)
        with pytest.raises(RuntimeError, match="post-placement"):
            proposals.promote_proposal(pending["id"], body)
    assert stored_state() == before
    assert proposals.promote_proposal(pending["id"], body)["status"] == "approved"


@pytest.mark.parametrize(
    "body",
    [
        {"unknown": True},
        {"placement": {}},
        {"placement": {"destination": None, "expected_parent": None}},
        {
            "placement": {
                "expected_parent": None,
                "destination": {
                    "id": True,
                    "expected_revision": 1,
                    "cohort": "v1:" + "a" * 64,
                },
            }
        },
        {
            "placement": {
                "expected_parent": None,
                "destination": {
                    "id": 1,
                    "expected_revision": "1",
                    "cohort": "v1:" + "a" * 64,
                },
            }
        },
    ],
)
def test_http_approval_rejects_unknown_or_unreviewed_placement(source, client, body):
    pending = proposals.stage_and_persist(source, candidate())
    before = stored_state()
    assert (
        client.post(
            f"/action-item-proposals/{pending['id']}/approve", json=body
        ).status_code
        == 422
    )
    assert stored_state() == before


@pytest.mark.parametrize("body", [None, {}, {"placement": None}])
def test_http_approval_keeps_bodyless_empty_and_null_placement_compatibility(
    source, client, body
):
    pending = proposals.stage_and_persist(source, candidate())
    response = client.post(
        f"/action-item-proposals/{pending['id']}/approve",
        **({"json": body} if body is not None else {}),
    )
    assert response.status_code == 200
    assert (
        parent_and_position(response.json()["applied_ref"]["action_item_id"])[0] is None
    )


@pytest.mark.parametrize("other", ["sibling_move", "rename", "approval"])
@pytest.mark.parametrize("approval_first", [False, True])
def test_native_placement_races_have_one_fresh_winner(
    source, monkeypatch, other, approval_first
):
    destination = epic()
    siblings = [
        membership(
            tasks.create({"title": f"Sibling {index}"}),
            destination=current(destination["id"]),
        )
        for index in range(2)
    ]
    destination = current(destination["id"])
    pending = proposals.stage_and_persist(
        source, candidate(title="First proposed task")
    )
    approve = partial(proposals.promote_proposal, pending["id"], placement(destination))
    other_pending = None
    if other == "sibling_move":
        operation = partial(
            queue_db.move,
            {
                "source": root_ref(siblings[1]),
                "parent": ref(destination),
                "before": root_ref(siblings[0]),
            },
        )
    elif other == "rename":
        operation = partial(
            queue_db.rename_epic,
            destination["id"],
            {"expected_revision": destination["revision"], "title": "Renamed"},
        )
    else:
        other_pending = proposals.stage_and_persist(
            source, candidate(title="Second proposed task")
        )
        operation = partial(
            proposals.promote_proposal, other_pending["id"], placement(destination)
        )
    first, second = (approve, operation) if approval_first else (operation, approve)
    connections = watch_decision_connections(monkeypatch, service=proposals)
    monkeypatch.setattr(tasks, "get_connection", proposals.get_connection)
    with ThreadPoolExecutor(max_workers=2) as executor:
        with get_connection() as blocker, blocker.cursor() as cursor:
            tasks.acquire_write_lock(cursor)
            winner = executor.submit(decide, lambda _: first(), 0)
            wait_for_block(
                cursor, connections.get(timeout=2), winner, blocker.get_backend_pid()
            )
            loser = executor.submit(decide, lambda _: second(), 0)
            wait_for_block(cursor, connections.get(timeout=2), loser)
        result, stale = winner.result(timeout=8), loser.result(timeout=8)
    assert isinstance(result, dict), result
    assert isinstance(stale, (proposals.ProposalConflictError, tasks.Conflict)), stale
    assert get_proposal(pending["id"])["status"] == (
        "approved" if approval_first else "pending"
    )
    assert current(destination["id"])["total_count"] == 2 + int(
        approval_first or other == "approval"
    )
    if other_pending:
        assert get_proposal(other_pending["id"])["status"] == (
            "pending" if approval_first else "approved"
        )
