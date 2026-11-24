from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from services.action_items import db as tasks
from services.api.models.action_item_proposal import get_proposal
from services.api.routers.action_item_proposals import router
from services.db import get_connection
from tests.action_item_queue_helpers import clear_action_items
from services.meetings import db as meetings
from services.meetings.config import SourceConfig
from services.meetings.types import MeetingSummary
from services.action_items import proposals as action_items
from tests.conftest import action_item_owner, clean_meeting_rows
from tests.test_proposal_decision_concurrency import (
    decide,
    race_with_held_master,
    wait_for_block,
    watch_decision_connections,
)

_QUOTE = "Send the design document and complete the integration review."


@pytest.fixture(autouse=True)
def empty_task_proposals():
    def clean():
        with get_connection() as conn, conn.cursor() as cursor:
            cursor.execute("DELETE FROM action_item_proposals")
            cursor.execute("DELETE FROM action_item_proposal_receipts")
            clear_action_items(cursor)

    clean()
    yield
    clean()


@pytest.fixture
def source_factory():
    config = SourceConfig(
        "task-proposals", "test", "task-proposals-" + uuid4().hex, "synthetic-only"
    )
    meetings.claim_source(config, "fixture")
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def make(text=_QUOTE):
        summary = MeetingSummary(
            uuid4().hex,
            "Synthetic planning",
            text,
            None,
            "https://example.test/meeting",
            stamp,
            stamp,
        )
        result = meetings.save_progress(config, "fixture", {}, summary=summary)
        return meetings.get_summary(result["id"])

    yield make
    clean_meeting_rows(config.account_key)


@pytest.fixture
def source(source_factory):
    return source_factory()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/action-item-proposals")
    return TestClient(app)


def candidate(*, title="Send the design document", changes=None, target=None):
    return {
        "action": "update" if target else "create",
        **(
            {"target_id": target["id"], "expected_revision": target["revision"]}
            if target
            else {}
        ),
        "changes": changes if changes is not None else {"title": title},
        "rationale": "An explicit synthetic meeting commitment supports this change.",
        "evidence": [{"segment_id": "summary-0", "quote": _QUOTE}],
    }


def test_generation_persists_detached_review_without_creating_a_task(source, client):
    proposal = action_items.stage_and_persist(source, candidate())
    assert "target_kind" not in proposal and proposal["status"] == "pending"
    assert "proposed_item_id" not in proposal and proposal["target_id"] is None
    assert tasks.list_items({"status": "all"})["total"] == 0
    detail = client.get(f"/action-item-proposals/{proposal['id']}").json()
    assert detail["proposed_item"] == {
        "title": "Send the design document",
        "description": "",
        "project": None,
        "tags": [],
        "status": "open",
        "due_at": None,
    }
    assert detail["current_target"] is None and detail["before_snapshot"] is None
    assert detail["source_stale"] is False and detail["source_available"] is True
    assert detail["evidence"] == [
        {
            "source": "meeting",
            "id": source["id"],
            "note": source["title"],
            "quote": _QUOTE,
            "segment_id": "summary-0",
            "revision": 1,
        }
    ]


def test_approval_creates_once_and_replays_the_receipt_after_later_edit_or_deletion(
    source,
):
    first = tasks.create({"title": "An earlier task"})
    proposal = action_items.stage_and_persist(source, candidate())
    approved = action_items.promote_proposal(proposal["id"])
    item_id = approved["applied_ref"]["action_item_id"]
    task = tasks.get(item_id)
    assert task["priority"] == first["priority"] + 1 and task["revision"] == 1
    edited = tasks.update(
        item_id, {"expected_revision": 1, "title": "User edited this task"}
    )
    assert action_items.promote_proposal(proposal["id"]) == approved
    assert tasks.get(item_id) == edited
    tasks.delete(item_id, {"expected_revision": edited["revision"]})
    assert action_items.promote_proposal(proposal["id"]) == approved
    assert tasks.list_items({"status": "all"})["total"] == 1


def test_list_includes_frozen_changes_and_live_conflict_flags(source, client):
    new = action_items.stage_and_persist(source, candidate())
    task = tasks.create({"title": "Complete the integration review"})
    update = action_items.stage_and_persist(
        source, candidate(target=task, changes={"status": "completed"})
    )
    response = client.get("/action-item-proposals?status=pending")
    assert response.status_code == 200
    rows = {row["id"]: row for row in response.json()["items"]}
    assert rows[new["id"]]["proposed_item"]["title"] == "Send the design document"
    preview = rows[update["id"]]
    assert preview["before_snapshot"] == task
    assert preview["proposed_item"]["status"] == "completed"
    assert preview["source_available"] is True
    assert preview["source_stale"] is False and preview["target_stale"] is False
    tasks.update(task["id"], {"expected_revision": 1, "description": "Manual edit"})
    change_source(source)
    rows = {
        row["id"]: row for row in client.get("/action-item-proposals").json()["items"]
    }
    assert rows[update["id"]]["target_stale"] is True
    assert rows[new["id"]]["target_stale"] is False
    assert all(row["source_stale"] for row in rows.values())
    assert rows[update["id"]]["before_snapshot"] == task
    assert rows[update["id"]]["proposed_item"]["description"] == task["description"]


def test_review_never_returns_a_proposal_without_its_payload(source):
    proposal = action_items.stage_and_persist(source, candidate())
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "DELETE FROM action_item_proposal_payloads WHERE proposal_id=%s",
            (proposal["id"],),
        )
    with pytest.raises(action_items.ProposalConflictError, match="payload is missing"):
        action_items.review_details([proposal])


def test_rejection_is_durable_across_meetings_and_explicit_creation_defaults(
    source, source_factory
):
    proposal = action_items.stage_and_persist(source, candidate())
    rejected = action_items.reject_proposal(proposal["id"])
    assert action_items.reject_proposal(proposal["id"]) == rejected
    other = source_factory()
    explicit = candidate(
        changes={
            "title": " SEND  THE DESIGN DOCUMENT ",
            "description": "",
            "tags": [],
            "status": "open",
            "project": None,
            "due_at": None,
        }
    )
    with pytest.raises(action_items.DuplicateProposalError):
        action_items.stage_and_persist(other, explicit)
    assert tasks.list_items({"status": "all"})["total"] == 0


def equivalent_pending_updates(source):
    task = tasks.create({"title": "Complete the integration review"})
    first = action_items.stage_and_persist(
        source, candidate(target=task, changes={"status": "completed"})
    )
    current = tasks.update(
        task["id"],
        {"expected_revision": task["revision"], "description": "Manual notes"},
    )
    second = action_items.stage_and_persist(
        source, candidate(target=current, changes={"status": "completed"})
    )
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT decision_key FROM action_item_proposal_payloads WHERE proposal_id IN (%s,%s)",
            (first["id"], second["id"]),
        )
        keys = [row[0] for row in cursor.fetchall()]
    assert len(keys) == 2 and keys[0] == keys[1]
    return first, second, current, keys[0]


@pytest.mark.parametrize("delete_original", [False, True])
def test_equivalent_pending_updates_can_each_be_rejected(
    source, client, delete_original
):
    first, second, task, key = equivalent_pending_updates(source)
    rejected = client.post(f"/action-item-proposals/{first['id']}/reject")
    assert rejected.status_code == 200
    if delete_original:
        assert client.delete(f"/action-item-proposals/{first['id']}").status_code == 200
    blocked = client.post(f"/action-item-proposals/{second['id']}/approve")
    assert blocked.status_code == 409 and "dismissed" in blocked.json()["detail"]
    response = client.post(f"/action-item-proposals/{second['id']}/reject")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "rejected"
    assert (
        client.post(f"/action-item-proposals/{second['id']}/reject").json()
        == response.json()
    )
    if not delete_original:
        assert (
            client.post(f"/action-item-proposals/{first['id']}/reject").json()
            == rejected.json()
        )
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT decision_key,proposal_id FROM action_item_proposal_receipts"
        )
        assert cursor.fetchall() == [(key, None if delete_original else first["id"])]
    assert tasks.get(task["id"]) == task


def test_concurrent_equivalent_rejections_keep_one_receipt_and_both_decisions(
    source, monkeypatch
):
    first, second, task, key = equivalent_pending_updates(source)
    connections = watch_decision_connections(monkeypatch, service=action_items)
    with ThreadPoolExecutor(max_workers=2) as executor:
        with get_connection() as blocker, blocker.cursor() as cursor:
            tasks.acquire_write_lock(cursor)
            left = executor.submit(action_items.reject_proposal, first["id"])
            wait_for_block(cursor, connections.get(timeout=2), left)
            right = executor.submit(action_items.reject_proposal, second["id"])
            wait_for_block(cursor, connections.get(timeout=2), right)
        results = [left.result(timeout=8), right.result(timeout=8)]
    assert all(result["status"] == "rejected" for result in results)
    assert all(
        get_proposal(item["id"])["status"] == "rejected" for item in (first, second)
    )
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT decision_key,proposal_id FROM action_item_proposal_receipts"
        )
        receipts = cursor.fetchall()
    assert len(receipts) == 1 and receipts[0][0] == key
    assert receipts[0][1] in {first["id"], second["id"]}
    assert tasks.get(task["id"]) == task


def test_failed_sibling_rejection_preserves_preexisting_receipt_and_pending_row(
    source, monkeypatch
):
    first, second, task, key = equivalent_pending_updates(source)
    action_items.reject_proposal(first["id"])

    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic decision failure")

    monkeypatch.setattr(action_items, "_record_decision", fail)
    with pytest.raises(RuntimeError, match="Synthetic decision failure"):
        action_items.reject_proposal(second["id"])
    assert get_proposal(second["id"])["status"] == "pending"
    assert get_proposal(first["id"])["status"] == "rejected"
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT decision_key,proposal_id FROM action_item_proposal_receipts"
        )
        assert cursor.fetchall() == [(key, first["id"])]
    assert tasks.get(task["id"]) == task


@pytest.mark.parametrize("decision", ["pending", "rejected"])
def test_deleting_proposal_preserves_a_text_free_dismissal_receipt_and_live_task(
    source, decision
):
    proposal = action_items.stage_and_persist(source, candidate())
    if decision == "rejected":
        action_items.reject_proposal(proposal["id"])
    action_items.delete_proposal(proposal["id"])
    assert get_proposal(proposal["id"]) is None
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT * FROM action_item_proposal_receipts")
        receipt = cursor.fetchone()
        assert len(receipt) == 2 and len(receipt[0]) == 64 and receipt[1] is None
        cursor.execute("SELECT count(*) FROM action_item_proposal_payloads")
        assert cursor.fetchone()[0] == 0
    with pytest.raises(action_items.DuplicateProposalError):
        action_items.stage_and_persist(source, candidate())
    assert tasks.list_items({"status": "all"})["total"] == 0


@pytest.mark.parametrize("delete_audit", [False, True])
def test_approved_update_can_be_proposed_again_after_a_later_manual_change(
    source, source_factory, delete_audit
):
    task = tasks.create(
        {"title": "Integration review", "description": "Original notes"}
    )
    proposal = action_items.stage_and_persist(
        source, candidate(target=task, changes={"description": "Reviewed notes"})
    )
    action_items.promote_proposal(proposal["id"])
    if delete_audit:
        action_items.delete_proposal(proposal["id"])
    edited = tasks.update(
        task["id"], {"expected_revision": 2, "description": "Later manual notes"}
    )
    fresh = action_items.stage_and_persist(
        source_factory(),
        candidate(target=edited, changes={"description": "Reviewed notes"}),
    )
    action_items.promote_proposal(fresh["id"])
    assert tasks.get(task["id"])["description"] == "Reviewed notes"


def test_update_preserves_unreviewed_fields_and_queue_completion_semantics(
    source, client
):
    original = tasks.create(
        {
            "title": "Integration review",
            "description": "Keep these manual notes",
            "project": "Work",
            "tags": ["security"],
            "due_at": "2026-01-02T12:00:00Z",
        }
    )
    later = tasks.create({"title": "Later task"})
    proposal = action_items.stage_and_persist(
        source, candidate(target=original, changes={"status": "completed"})
    )
    frozen = client.get(f"/action-item-proposals/{proposal['id']}").json()
    assert frozen["before_snapshot"] == original
    approved = action_items.promote_proposal(proposal["id"])
    assert approved["applied_ref"] == {"action_item_id": original["id"]}
    completed = tasks.get(original["id"])
    assert (
        completed["status"] == "completed"
        and completed["completed_at"]
        and completed["priority"] is None
    )
    assert completed["revision"] == 2 and tasks.get(later["id"])["priority"] == 1
    for field in ("title", "description", "project", "tags", "due_at"):
        assert completed[field] == original[field]
    assert (
        client.get(f"/action-item-proposals/{proposal['id']}").json()["before_snapshot"]
        == original
    )


def test_task_edit_blocks_old_approval_and_allows_new_immutable_review(source):
    original = tasks.create(
        {"title": "Integration review", "description": "Original notes"}
    )
    old = action_items.stage_and_persist(
        source, candidate(target=original, changes={"status": "completed"})
    )
    edited = tasks.update(
        original["id"], {"expected_revision": 1, "description": "New user notes"}
    )
    with pytest.raises(action_items.ProposalConflictError, match="changed"):
        action_items.promote_proposal(old["id"])
    assert (
        tasks.get(original["id"]) == edited
        and get_proposal(old["id"])["status"] == "pending"
    )
    new = action_items.stage_and_persist(
        source, candidate(target=edited, changes={"status": "completed"})
    )
    assert new["id"] != old["id"]
    action_items.promote_proposal(new["id"])
    assert tasks.get(original["id"])["description"] == "New user notes"
    assert action_items.review_details([old])[0]["before_snapshot"] == original


def change_source(source):
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "UPDATE meeting_summaries SET revision=revision+1,content_hash=%s,summary_text=%s WHERE id=%s",
            ("b" * 64, _QUOTE + " Additional reviewed context.", source["id"]),
        )
    return meetings.get_summary(source["id"])


def test_source_edit_blocks_old_approval_but_does_not_strand_an_unchanged_pending_change(
    source, client
):
    old = action_items.stage_and_persist(source, candidate())
    changed = change_source(source)
    with pytest.raises(
        action_items.ProposalConflictError, match="source meeting changed"
    ):
        action_items.promote_proposal(old["id"])
    assert (
        client.get(f"/action-item-proposals/{old['id']}").json()["source_stale"] is True
    )
    new = action_items.stage_and_persist(changed, candidate())
    assert new["id"] != old["id"]
    action_items.promote_proposal(new["id"])
    with pytest.raises(
        action_items.ProposalConflictError, match="source meeting changed"
    ):
        action_items.promote_proposal(old["id"])
    assert tasks.list_items({"status": "all"})["total"] == 1


def test_rejected_change_stays_rejected_after_source_revision_changes(source):
    old = action_items.stage_and_persist(source, candidate())
    action_items.reject_proposal(old["id"])
    changed = change_source(source)
    with pytest.raises(action_items.DuplicateProposalError):
        action_items.stage_and_persist(changed, candidate())


def test_stale_pending_cannot_apply_if_another_generation_is_rejected(source):
    old = action_items.stage_and_persist(source, candidate())
    changed = change_source(source)
    new = action_items.stage_and_persist(changed, candidate())
    action_items.reject_proposal(new["id"])
    with pytest.raises(action_items.ProposalConflictError, match="dismissed"):
        action_items.promote_proposal(old["id"])
    assert tasks.list_items({"status": "all"})["total"] == 0


@pytest.mark.parametrize("unavailable", [False, True])
def test_missing_or_unavailable_source_blocks_approval_but_retains_audit(
    source, unavailable
):
    proposal = action_items.stage_and_persist(source, candidate())
    with get_connection() as conn, conn.cursor() as cursor:
        if unavailable:
            cursor.execute(
                "UPDATE meeting_summaries SET available=false WHERE id=%s",
                (source["id"],),
            )
        else:
            cursor.execute("DELETE FROM meeting_summaries WHERE id=%s", (source["id"],))
    with pytest.raises(action_items.ProposalConflictError):
        action_items.promote_proposal(proposal["id"])
    assert get_proposal(proposal["id"])["status"] == "pending"
    assert action_items.review_details([proposal])[0]["source_available"] is False
    action_items.reject_proposal(proposal["id"])


@pytest.mark.parametrize(
    "changes",
    [
        {"title": "Invented", "priority": 2},
        {"project": "Unknown"},
        {"due_at": "tomorrow"},
    ],
)
def test_invalid_task_fields_never_create_a_proposal(source, changes):
    with pytest.raises(ValueError):
        action_items.stage_and_persist(
            source, candidate(changes={"title": "Send the design document", **changes})
        )
    assert action_items.decision_context()["total"] == 0
    assert tasks.list_items({"status": "all"})["total"] == 0


@pytest.mark.parametrize(
    "evidence",
    [
        [{"segment_id": "summary-0", "quote": "Invented quote"}],
        [{"segment_id": "other", "quote": _QUOTE}],
        [{"segment_id": "summary-0", "quote": " "}],
    ],
)
def test_evidence_must_be_an_exact_saved_summary_quote(source, evidence):
    with pytest.raises(ValueError, match="exact saved summary"):
        action_items.stage_and_persist(source, {**candidate(), "evidence": evidence})
    assert action_items.decision_context()["total"] == 0


def test_forged_summary_text_cannot_borrow_a_real_revision_and_hash(source):
    with pytest.raises(action_items.ProposalConflictError):
        action_items.stage_and_persist(
            {**source, "summary_text": "Invented summary"},
            {
                **candidate(),
                "evidence": [{"segment_id": "summary-0", "quote": "Invented summary"}],
            },
        )


def test_normalized_noop_deadline_and_unchanged_patch_fields_do_not_evade_rejection(
    source,
):
    original = tasks.create(
        {
            "title": "Integration review",
            "description": "Original notes",
            "due_at": "2026-01-02T12:00:00Z",
        }
    )
    with pytest.raises(action_items.DuplicateProposalError, match="changes nothing"):
        action_items.stage_and_persist(
            source,
            candidate(target=original, changes={"due_at": "2026-01-02T12:00:00Z"}),
        )
    proposal = action_items.stage_and_persist(
        source, candidate(target=original, changes={"status": "completed"})
    )
    action_items.reject_proposal(proposal["id"])
    with pytest.raises(action_items.DuplicateProposalError):
        action_items.stage_and_persist(
            source,
            candidate(
                target=original,
                changes={
                    "status": "completed",
                    "title": original["title"],
                    "due_at": "2026-01-02T12:00:00+00:00",
                },
            ),
        )


def test_intervening_exact_duplicate_including_completed_task_blocks_create(source):
    proposal = action_items.stage_and_persist(source, candidate())
    duplicate = tasks.create(
        {"title": " SEND  THE DESIGN DOCUMENT ", "status": "completed"}
    )
    with pytest.raises(action_items.ProposalConflictError, match="created after"):
        action_items.promote_proposal(proposal["id"])
    assert tasks.list_items({"status": "all"})["total"] == 1
    assert tasks.get(duplicate["id"])["status"] == "completed"


def test_same_title_in_another_project_remains_a_distinct_commitment(source):
    tasks.create({"title": "Send the design document", "project": "Personal"})
    tasks.create_project({"name": "Work"})
    proposal = action_items.stage_and_persist(
        source,
        candidate(changes={"title": "Send the design document", "project": "Work"}),
    )
    action_items.promote_proposal(proposal["id"])
    assert tasks.list_items({"status": "all"})["total"] == 2


def test_deleted_or_reordered_target_requires_fresh_review(source):
    original = tasks.create({"title": "Integration review"})
    later = tasks.create({"title": "Later task"})
    proposal = action_items.stage_and_persist(
        source, candidate(target=original, changes={"status": "completed"})
    )
    moved = tasks.move(
        original["id"], {"expected_revision": 1, "after_id": later["id"]}
    )
    with pytest.raises(action_items.ProposalConflictError):
        action_items.promote_proposal(proposal["id"])
    tasks.delete(original["id"], {"expected_revision": moved["revision"]})
    with pytest.raises(action_items.ProposalConflictError):
        action_items.promote_proposal(proposal["id"])


def test_project_rename_invalidates_reviewed_task_revision(source):
    task = tasks.create({"title": "Integration review", "project": "Proposal project"})
    proposal = action_items.stage_and_persist(
        source, candidate(target=task, changes={"status": "completed"})
    )
    project = next(
        row
        for row in tasks.list_projects()["items"]
        if row["name"] == "Proposal project"
    )
    tasks.update_project_details(
        project["id"], {"expected_revision": 1, "name": "Renamed proposal project"}
    )
    with pytest.raises(action_items.ProposalConflictError):
        action_items.promote_proposal(proposal["id"])
    assert tasks.get(task["id"])["status"] == "open"


@pytest.mark.parametrize(
    "decision", [action_items.promote_proposal, action_items.reject_proposal]
)
def test_failure_after_decision_rolls_back_task_receipt_and_proposal(
    monkeypatch, source, decision
):
    proposal = action_items.stage_and_persist(source, candidate())
    record = action_items._record_decision

    def fail(*args, **kwargs):
        record(*args, **kwargs)
        raise RuntimeError("Synthetic post-decision failure")

    with monkeypatch.context() as patch:
        patch.setattr(action_items, "_record_decision", fail)
        with pytest.raises(RuntimeError):
            decision(proposal["id"])
    assert get_proposal(proposal["id"])["status"] == "pending"
    assert tasks.list_items({"status": "all"})["total"] == 0
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM action_item_proposal_receipts")
        assert cursor.fetchone()[0] == 0
        cursor.execute(
            "SELECT pg_try_advisory_xact_lock(hashtextextended('agent-smith:action-items-write',0))"
        )
        assert cursor.fetchone()[0] is True
    assert action_items.promote_proposal(proposal["id"])["status"] == "approved"


def test_external_connection_never_opens_commits_or_closes_another_transaction(
    monkeypatch,
):
    original = tasks.create({"title": "Original"})
    created_id = None

    def forbidden():
        pytest.fail("An injected task write must reuse its parent connection")

    with pytest.raises(RuntimeError):
        with get_connection() as conn:
            with monkeypatch.context() as patch:
                patch.setattr(tasks, "get_connection", forbidden)
                created_id = tasks.create({"title": "Uncommitted"}, conn=conn)["id"]
                tasks.update(
                    original["id"],
                    {"expected_revision": 1, "title": "Uncommitted edit"},
                    conn=conn,
                )
                assert conn.closed == 0
            raise RuntimeError("Roll back both nested writes")
    assert tasks.get(original["id"]) == original
    with pytest.raises(tasks.NotFound):
        tasks.get(created_id)
    with get_connection() as conn:
        with pytest.raises(ValueError, match="global"):
            tasks.profile_queue(str(uuid4())).create(
                {"title": "Invalid transaction"}, conn=conn
            )


@pytest.mark.parametrize(
    "first,second,status",
    [
        (action_items.promote_proposal, action_items.reject_proposal, "approved"),
        (action_items.reject_proposal, action_items.promote_proposal, "rejected"),
        (action_items.promote_proposal, action_items.promote_proposal, "approved"),
    ],
)
def test_native_decision_races_have_one_task_mutation_and_one_terminal_result(
    monkeypatch, source, first, second, status
):
    proposal = action_items.stage_and_persist(source, candidate())
    winner, loser = race_with_held_master(
        monkeypatch,
        proposal,
        first,
        second,
        service=action_items,
        table="action_item_proposals",
    )
    assert isinstance(winner, dict) and winner["status"] == status
    if first is second:
        assert loser == winner
    else:
        assert isinstance(loser, action_items.ProposalConflictError)
    assert get_proposal(proposal["id"])["status"] == status
    assert tasks.list_items({"status": "all"})["total"] == int(status == "approved")


def test_decision_takes_queue_advisory_lock_before_proposal_master(monkeypatch, source):
    proposal = action_items.stage_and_persist(source, candidate())
    connections = watch_decision_connections(monkeypatch, service=action_items)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with get_connection() as blocker, blocker.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended('agent-smith:action-items-write',0))"
            )
            future = executor.submit(
                decide, action_items.promote_proposal, proposal["id"]
            )
            wait_for_block(
                cursor, connections.get(timeout=2), future, blocker.get_backend_pid()
            )
            cursor.execute(
                "SELECT id FROM action_item_proposals WHERE id=%s FOR UPDATE NOWAIT",
                (proposal["id"],),
            )
            assert cursor.fetchone()[0] == proposal["id"]
        assert future.result(timeout=8)["status"] == "approved"


def test_concurrent_generation_files_one_pending_proposal_without_task_writes(
    monkeypatch, source
):
    connections = watch_decision_connections(monkeypatch, service=action_items)
    monkeypatch.setattr(action_items, "get_connection", action_items.get_connection)
    with ThreadPoolExecutor(max_workers=2) as executor:
        with get_connection() as blocker, blocker.cursor() as cursor:
            tasks.acquire_write_lock(cursor)
            first = executor.submit(
                decide, lambda _: action_items.stage_and_persist(source, candidate()), 0
            )
            wait_for_block(
                cursor, connections.get(timeout=2), first, blocker.get_backend_pid()
            )
            second = executor.submit(
                decide, lambda _: action_items.stage_and_persist(source, candidate()), 0
            )
            wait_for_block(cursor, connections.get(timeout=2), second)
        results = [first.result(timeout=8), second.result(timeout=8)]
    assert sum(isinstance(result, dict) for result in results) == 1
    assert (
        sum(
            isinstance(result, action_items.DuplicateProposalError)
            for result in results
        )
        == 1
    )
    assert action_items.decision_context()["total"] == 1
    assert tasks.list_items({"status": "all"})["total"] == 0


def test_native_manual_edit_wins_queue_lock_before_stale_approval(monkeypatch, source):
    task = tasks.create({"title": "Integration review"})
    proposal = action_items.stage_and_persist(
        source, candidate(target=task, changes={"status": "completed"})
    )
    connections = watch_decision_connections(monkeypatch, service=action_items)
    monkeypatch.setattr(tasks, "get_connection", action_items.get_connection)
    with ThreadPoolExecutor(max_workers=2) as executor:
        with get_connection() as blocker, blocker.cursor() as cursor:
            tasks.acquire_write_lock(cursor)
            edit = executor.submit(
                tasks.update,
                task["id"],
                {"expected_revision": 1, "description": "Manual edit"},
            )
            wait_for_block(
                cursor, connections.get(timeout=2), edit, blocker.get_backend_pid()
            )
            approve = executor.submit(
                decide, action_items.promote_proposal, proposal["id"]
            )
            wait_for_block(cursor, connections.get(timeout=2), approve)
        assert edit.result(timeout=8)["description"] == "Manual edit"
        assert isinstance(approve.result(timeout=8), action_items.ProposalConflictError)
    assert tasks.get(task["id"])["status"] == "open"


def test_context_includes_all_review_states_and_reports_full_total(source):
    first = action_items.stage_and_persist(source, candidate(title="One task"))
    second = action_items.stage_and_persist(source, candidate(title="Two task"))
    third = action_items.stage_and_persist(source, candidate(title="Three task"))
    action_items.promote_proposal(first["id"])
    action_items.reject_proposal(second["id"])
    context = action_items.decision_context()
    assert context["total"] == 3
    assert {row["status"] for row in context["items"]} == {
        "pending",
        "approved",
        "rejected",
    }
    assert all(
        row["meeting_id"] == source["id"] and row["changes"]["title"]
        for row in context["items"]
    )
    assert action_items.decision_context(limit=1)["items"][0]["id"] == third["id"]
    assert action_items.decision_context(limit=1)["total"] == 3


def test_stage_rejects_a_stale_snapshot_without_a_partial_proposal(source):
    change_source(source)
    with pytest.raises(action_items.ProposalConflictError):
        action_items.stage_and_persist(source, candidate())
    assert action_items.decision_context()["total"] == 0


def test_matching_context_marks_source_and_target_drift_without_losing_prior_decisions(
    source, source_factory
):
    source_proposal = action_items.stage_and_persist(source, candidate())
    task = tasks.create({"title": "Integration review"})
    target_proposal = action_items.stage_and_persist(
        source_factory(), candidate(target=task, changes={"status": "completed"})
    )
    change_source(source)
    tasks.update(
        task["id"], {"expected_revision": 1, "description": "New manual notes"}
    )
    context = {row["id"]: row for row in action_items.decision_context()["items"]}
    assert context[source_proposal["id"]]["source_stale"] is True
    assert context[source_proposal["id"]]["target_stale"] is False
    assert context[target_proposal["id"]]["source_stale"] is False
    assert context[target_proposal["id"]]["target_stale"] is True
    assert context[target_proposal["id"]]["base_version"] == 1


@pytest.mark.parametrize("takeover", [False, True])
def test_publication_rechecks_expired_or_replaced_lease_inside_its_transaction(
    source, takeover
):
    from services.meetings import action_item_db

    identities = [(source["provider"], source["account_key"])]
    assert action_item_db.claim(identities, action_item_owner("original-worker"))
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "UPDATE meeting_action_item_runs SET claim_until=clock_timestamp()-interval '1 second' WHERE meeting_id=%s",
            (source["id"],),
        )
    if takeover:
        assert action_item_db.claim(identities, action_item_owner("replacement-worker"))
    with pytest.raises(meetings.ClaimLostError):
        action_items.stage_and_persist(
            source, candidate(), lease_owner=action_item_owner("original-worker")
        )
    assert action_items.decision_context()["total"] == 0
    assert tasks.list_items({"status": "all"})["total"] == 0
    if takeover:
        assert action_item_db.get_record(source["id"])[
            "claim_owner"
        ] == action_item_owner("replacement-worker")
        proposal = action_items.stage_and_persist(
            source, candidate(), lease_owner=action_item_owner("replacement-worker")
        )
        assert proposal["status"] == "pending"
