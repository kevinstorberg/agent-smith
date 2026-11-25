from concurrent.futures import ThreadPoolExecutor

import pytest

from services.action_items import db as tasks, proposals, queue_db
from services.db import get_connection
from services.proposals.errors import ProposalConflictError
from tests.action_item_queue_helpers import assert_action_item_queue
from tests.test_action_item_epics import current, epic, membership
from tests.test_action_item_proposal_placement import (
    parent_and_position,
    placement,
    stored_state,
)
from tests.test_action_item_proposals import (
    candidate,
    client as client,
    empty_task_proposals as empty_task_proposals,
    source as source,
    source_factory as source_factory,
)


@pytest.fixture(autouse=True)
def valid_queue(empty_task_proposals):
    yield
    assert_action_item_queue()


def frozen_changes(proposal_id):
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT changes FROM action_item_proposal_payloads WHERE proposal_id=%s",
            (proposal_id,),
        )
        return cursor.fetchone()[0]


@pytest.mark.parametrize("proposed_status", ["open", "completed"])
@pytest.mark.parametrize("in_epic", [False, True])
def test_done_creates_a_completed_item_atomically_with_normal_invariants(
    source, client, proposed_status, in_epic
):
    destination = epic() if in_epic else None
    pending = proposals.stage_and_persist(
        source,
        candidate(
            changes={
                "title": "Review design",
                "description": "Keep the detailed commitment",
                "tags": ["design"],
                "status": proposed_status,
            }
        ),
    )
    before = frozen_changes(pending["id"])
    body = {"complete": True, **(placement(destination) if destination else {})}
    response = client.post(f"/action-item-proposals/{pending['id']}/approve", json=body)
    assert response.status_code == 200, response.text
    approved = response.json()
    item = tasks.get(approved["applied_ref"]["action_item_id"])
    assert approved["status"] == "approved"
    assert approved["review_outcome"] == "completed"
    assert approved["applied_ref"]["review_outcome"] == "completed"
    assert item["status"] == "completed" and item["completed_at"] is not None
    assert item["priority"] is None
    assert item["title"] == "Review design"
    assert item["description"] == "Keep the detailed commitment"
    assert item["tags"] == ["design"]
    assert parent_and_position(item["id"]) == (
        destination["id"] if destination else None,
        None,
    )
    normal = tasks.create({"title": "Normal completion"})
    normal = tasks.update(
        normal["id"],
        {"expected_revision": normal["revision"], "status": "completed"},
    )
    assert normal["status"] == item["status"]
    assert normal["completed_at"] is not None and normal["priority"] is None
    if destination:
        counts = current(destination["id"])
        assert counts["open_count"] == 0 and counts["total_count"] == 1
    assert frozen_changes(pending["id"]) == before
    assert approved["evidence"] == pending["evidence"]


@pytest.mark.parametrize("status", ["open", "completed"])
@pytest.mark.parametrize("move", ["keep", "same", "other"])
def test_done_updates_use_live_completed_placement_and_preserve_task_data(
    source, status, move
):
    parent = epic("Original")
    item = membership(
        tasks.create(
            {
                "title": "Review design",
                "description": "Original",
                "tags": ["keep"],
                "status": status,
                "due_at": "2026-12-01T12:00:00+00:00",
            }
        ),
        destination=parent,
    )
    sibling = membership(
        tasks.create({"title": "Remaining work"}), destination=current(parent["id"])
    )
    parent = current(parent["id"])
    destination = epic("Next") if move == "other" else parent
    pending = proposals.stage_and_persist(
        source, candidate(target=item, changes={"description": "Reviewed"})
    )
    body = {
        "complete": True,
        **(placement(destination, parent) if move != "keep" else {}),
    }
    approved = proposals.promote_proposal(pending["id"], body)
    saved = tasks.get(item["id"])
    assert approved["review_outcome"] == "completed"
    assert saved["status"] == "completed" and saved["completed_at"]
    if status == "completed":
        assert saved["completed_at"] == item["completed_at"]
    assert saved["description"] == "Reviewed"
    for field in ("title", "tags", "project", "due_at", "created_at"):
        assert saved[field] == item[field]
    assert parent_and_position(item["id"]) == (destination["id"], None)
    assert parent_and_position(sibling["id"]) == (parent["id"], 1)
    assert current(parent["id"])["open_count"] == 1
    if move == "other":
        assert current(destination["id"])["open_count"] == 0
        assert current(destination["id"])["total_count"] == 1


def test_done_replay_preserves_decision_after_the_task_is_manually_reopened(source):
    destination = epic()
    pending = proposals.stage_and_persist(source, candidate())
    body = {"complete": True, **placement(destination)}
    approved = proposals.promote_proposal(pending["id"], body)
    item = tasks.get(approved["applied_ref"]["action_item_id"])
    reopened = tasks.update(
        item["id"], {"expected_revision": item["revision"], "status": "open"}
    )
    before = stored_state()
    replay = proposals.promote_proposal(pending["id"], body)
    assert replay == approved
    assert tasks.get(item["id"]) == reopened
    assert stored_state() == before
    history = {row["id"]: row for row in proposals.decision_context()["items"]}
    assert history[pending["id"]]["review_outcome"] == "completed"


@pytest.mark.parametrize("first_complete", [False, True])
def test_approval_replay_requires_the_original_completion_intent(
    source, client, first_complete
):
    pending = proposals.stage_and_persist(source, candidate())
    body = {"complete": True} if first_complete else {}
    approved = client.post(f"/action-item-proposals/{pending['id']}/approve", json=body)
    assert approved.status_code == 200, approved.text
    before = stored_state()
    changed = client.post(
        f"/action-item-proposals/{pending['id']}/approve",
        json={"complete": not first_complete},
    )
    assert changed.status_code == 409, changed.text
    assert "completion" in changed.json()["detail"]
    assert stored_state() == before


@pytest.mark.parametrize("invalid", [None, 0, 1, "true", [], {}])
def test_completion_intent_is_a_strict_boolean(source, client, invalid):
    pending = proposals.stage_and_persist(source, candidate())
    before = stored_state()
    response = client.post(
        f"/action-item-proposals/{pending['id']}/approve", json={"complete": invalid}
    )
    assert response.status_code == 422, response.text
    assert stored_state() == before


def test_stale_epic_rejects_done_without_completing_or_creating_a_task(source, client):
    destination = epic()
    pending = proposals.stage_and_persist(source, candidate())
    body = {"complete": True, **placement(destination)}
    queue_db.rename_epic(
        destination["id"],
        {"expected_revision": destination["revision"], "title": "Changed"},
    )
    before = stored_state()
    response = client.post(f"/action-item-proposals/{pending['id']}/approve", json=body)
    assert response.status_code == 409, response.text
    assert stored_state() == before


def test_recording_failure_rolls_back_task_completion_and_outcome(source, monkeypatch):
    pending = proposals.stage_and_persist(source, candidate())
    before = stored_state()

    def fail(*_args):
        raise RuntimeError("Synthetic decision persistence failure")

    monkeypatch.setattr(proposals, "_record_decision", fail)
    with pytest.raises(RuntimeError, match="Synthetic decision"):
        proposals.promote_proposal(pending["id"], {"complete": True})
    assert stored_state() == before


def test_concurrent_accept_and_done_have_one_winner_and_one_task(source):
    pending = proposals.stage_and_persist(source, candidate())

    def decide(complete):
        try:
            return proposals.promote_proposal(pending["id"], {"complete": complete})
        except ProposalConflictError:
            return None

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(decide, [False, True]))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    items = tasks.list_items({"status": "all"})
    assert items["total"] == 1
    expected = "completed" if winners[0]["review_outcome"] == "completed" else "open"
    assert items["items"][0]["status"] == expected


def test_feedback_distinguishes_legacy_accept_reject_and_explicit_done(source, client):
    accepted = proposals.stage_and_persist(source, candidate(title="Accepted task"))
    accepted_result = proposals.promote_proposal(accepted["id"])
    assert accepted_result["applied_ref"] == {
        "action_item_id": accepted_result["applied_ref"]["action_item_id"]
    }
    rejected = proposals.stage_and_persist(source, candidate(title="Rejected task"))
    proposals.reject_proposal(rejected["id"])
    completed = proposals.stage_and_persist(source, candidate(title="Completed task"))
    proposals.promote_proposal(completed["id"], {"complete": True})
    expected = {
        accepted["id"]: "accepted",
        rejected["id"]: "rejected",
        completed["id"]: "completed",
    }
    context = {
        row["id"]: row["review_outcome"]
        for row in proposals.decision_context()["items"]
    }
    assert context == expected
    listing = client.get("/action-item-proposals").json()
    assert {row["id"]: row["review_outcome"] for row in listing["items"]} == expected
    for proposal_id, outcome in expected.items():
        detail = client.get(f"/action-item-proposals/{proposal_id}").json()
        assert detail["review_outcome"] == outcome
    assert client.get("/action-item-proposals/counts").json() == {
        "pending": 0,
        "approved": 2,
        "rejected": 1,
        "superseded": 0,
    }


@pytest.mark.parametrize(
    "status,marker",
    [
        ("approved", "unknown"),
        ("approved", None),
        ("pending", "completed"),
        ("rejected", "completed"),
    ],
)
def test_feedback_does_not_silently_reinterpret_invalid_recorded_outcomes(
    status, marker
):
    with pytest.raises(ProposalConflictError, match="invalid recorded review outcome"):
        proposals.review_outcome(
            {"status": status, "applied_ref": {"review_outcome": marker}}
        )
