import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from psycopg2.extras import Json

from services.db import get_connection
from services.meetings import (
    db,
    digestion_db,
    management_db,
    manual_analysis,
    manual_stage,
    memory_db,
    profile_db,
    stage_db,
    work_requests,
)
from tests.test_manual_analysis import (
    finish_stage,
    jobs as jobs,
    payload as payload,
    saved as saved,
)
from tests.test_meeting_profiles_db import ready_meeting
from tests.test_meeting_sync import source as source


def request(meeting_id, stages, reason="process_meeting"):
    with db._cursor() as cur:
        return work_requests.request(cur, meeting_id, stages, reason)


def pending_meeting(source, external_id="one"):
    meeting_id = ready_meeting(source, external_id)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE meeting_digestions SET memory_status='pending',memory_artifact='{}'::jsonb WHERE meeting_id=%s",
            (meeting_id,),
        )
    return meeting_id


def test_pure_mark_and_consume_preserve_other_scopes_and_do_not_mutate_inputs():
    original = {
        "profile": {"request_id": "immutable", "active": True},
        "other": {"kept": True},
    }
    frozen = copy.deepcopy(original)
    now = datetime(2026, 11, 2, tzinfo=timezone.utc)
    memory = work_requests.mark(original, "memory", "memory_retry", requested_at=now)
    both = work_requests.mark(memory, "profile", "profile_retry", requested_at=now)
    remaining = work_requests.consume(both, ("memory",))
    assert original == frozen and memory["work_requests"] == {
        "memory": both["work_requests"]["memory"]
    }
    assert remaining["profile"] == original["profile"]
    assert remaining["work_requests"] == {"profile": both["work_requests"]["profile"]}
    assert work_requests.consume(remaining, ("profile",)) == original
    with pytest.raises(ValueError):
        work_requests.mark(
            original, "memory", "unbounded invented reason", requested_at=now
        )
    with pytest.raises(ValueError):
        work_requests.mark(
            original, "memory", "memory_retry", requested_at=now.replace(tzinfo=None)
        )


def test_legacy_shared_flag_cannot_wake_or_prioritize_another_workflow(source):
    first, second = pending_meeting(source, "first"), pending_meeting(source, "second")
    identities = [(source.provider, source.account_key)]
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE meeting_digestions SET requested_at=clock_timestamp()-interval '1 day' WHERE meeting_id=%s",
            (first,),
        )
    assert not digestion_db.has_requested_work(identities)
    assert not digestion_db.has_requested_profile_work(source.name)
    request(first, ("memory",), "memory_retry")
    assert digestion_db.has_requested_work(identities)
    assert not digestion_db.has_requested_profile_work(source.name)
    request(second, ("profile",), "profile_retry")
    assert (
        digestion_db.claim_profile(source.name, "profile-owner")["meeting_id"] == second
    )
    digestion_db.release_profile_owner("profile-owner")
    assert (
        digestion_db.claim_digestion(identities, "memory-owner")["meeting_id"] == first
    )
    digestion_db.release(first, "memory-owner")


@pytest.mark.parametrize(
    "marker",
    [
        None,
        [],
        7,
        "invalid",
        {"requested_at": 1.5, "reason": "memory_retry"},
        {"requested_at": "2026-11-02T00:00:00Z", "reason": "memory_retry"},
        {"requested_at": True, "reason": "memory_retry"},
        {"requested_at": -1, "reason": "memory_retry"},
        {"requested_at": 253_402_300_800_000_000, "reason": "memory_retry"},
        {"requested_at": 1, "reason": "invented"},
        {"requested_at": 1, "reason": "memory_retry", "extra": "invalid"},
    ],
)
def test_invalid_work_marker_cannot_wake_paid_work(source, marker):
    meeting_id = pending_meeting(source)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE meeting_digestions SET manual_analysis=%s,requested_at=clock_timestamp() WHERE meeting_id=%s",
            (Json({"work_requests": {"memory": marker}}), meeting_id),
        )
    assert not digestion_db.has_requested_work([(source.provider, source.account_key)])
    assert not digestion_db.has_requested_profile_work(source.name)


def test_active_receipt_backed_legacy_manual_scope_remains_explicit_intent(
    source, saved, payload, jobs
):
    meeting_id = saved()
    jobs("meeting_ingest")
    manual_analysis.request_analysis(payload(meeting_id, scope="memories"))
    with db._cursor() as cur:
        work_requests.finish(cur, meeting_id, work_requests.STAGES)
    assert "work_requests" not in digestion_db.get_record(meeting_id)["manual_analysis"]
    assert digestion_db.has_requested_work([(source.provider, source.account_key)])
    assert not digestion_db.has_requested_profile_work(source.name)


def test_terminal_cleanup_retains_sibling_request_and_pending_backoff(source):
    meeting_id = pending_meeting(source)
    request(meeting_id, work_requests.STAGES)
    identities = [(source.provider, source.account_key)]
    row = digestion_db.claim_digestion(identities, "memory-owner")
    stage_db.save_progress(
        "memory", meeting_id, "memory-owner", row["transcript_hash"], {}, complete=True
    )
    digestion_db.release(meeting_id, "memory-owner")
    controls = digestion_db.get_record(meeting_id)["manual_analysis"]
    assert set(controls["work_requests"]) == {"profile"}
    assert not digestion_db.has_requested_work(identities)
    row = digestion_db.claim_profile(source.name, "profile-owner")
    for attempt in range(3):
        stage_db.record_failure(
            "profile", meeting_id, "profile-owner", "SyntheticFailure"
        )
        current = digestion_db.get_record(meeting_id)
        assert ("profile" in current["manual_analysis"].get("work_requests", {})) == (
            attempt < 2
        )
    digestion_db.release_profile_owner("profile-owner")


def test_concurrent_scoped_requests_do_not_lose_sibling_marker(source):
    meeting_id = pending_meeting(source)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(
            pool.map(lambda stage: request(meeting_id, (stage,)), work_requests.STAGES)
        )
    assert set(
        digestion_db.get_record(meeting_id)["manual_analysis"]["work_requests"]
    ) == set(work_requests.STAGES)


def test_capture_terminal_failure_and_deletion_clear_only_applicable_intent(source):
    meeting_id = pending_meeting(source)
    request(meeting_id, work_requests.STAGES)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE meeting_digestions SET transcript_status='pending' WHERE meeting_id=%s",
            (meeting_id,),
        )
    assert digestion_db.claim_transcript(
        [(source.provider, source.account_key)], "capture-owner"
    )
    digestion_db.record_failure(
        meeting_id, "capture-owner", "TranscriptUnavailable", status="unavailable"
    )
    digestion_db.release(meeting_id, "capture-owner")
    assert set(
        digestion_db.get_record(meeting_id)["manual_analysis"]["work_requests"]
    ) == {"profile"}
    digestion_db.delete_transcript(meeting_id)
    assert "work_requests" not in digestion_db.get_record(meeting_id)["manual_analysis"]


@pytest.mark.parametrize(
    "operation,expected",
    [
        ("memory_retry", {"memory"}),
        ("profile_retry", {"profile"}),
        ("transcript_retry", {"memory"}),
        ("participant_assignment", {"profile"}),
        ("process_memory", {"memory"}),
        ("process_profile", {"profile"}),
        ("process_both", {"memory", "profile"}),
    ],
)
def test_public_producers_mark_only_their_unfinished_workflows(
    source, saved, operation, expected
):
    meeting_id = saved()
    memory = (
        "failed"
        if operation == "memory_retry"
        else "done"
        if operation == "process_profile"
        else "pending"
    )
    profile = (
        "failed"
        if operation == "profile_retry"
        else "done"
        if operation == "process_memory"
        else "pending"
    )
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE meeting_digestions SET memory_status=%s,profile_status=%s WHERE meeting_id=%s",
            (memory, profile, meeting_id),
        )
        if operation == "transcript_retry":
            cur.execute(
                "UPDATE meeting_digestions SET transcript_status='failed' WHERE meeting_id=%s",
                (meeting_id,),
            )
    if operation == "memory_retry":
        memory_db.retry_memories(meeting_id)
    elif operation == "profile_retry":
        profile_db.retry_profiles(meeting_id)
    elif operation == "transcript_retry":
        digestion_db.retry_transcript(meeting_id)
    elif operation == "participant_assignment":
        management_db.update_participants(
            meeting_id, 0, [{"name": "An explicitly assigned participant"}]
        )
    else:
        assert management_db.request_processing(meeting_id) == {"status": "queued"}
    markers = digestion_db.get_record(meeting_id)["manual_analysis"]["work_requests"]
    assert set(markers) == expected
    assert all(
        marker["reason"]
        == ("process_meeting" if operation.startswith("process_") else operation)
        for marker in markers.values()
    )


@pytest.mark.parametrize(
    "scope,expected",
    [
        ("memories", {"memory"}),
        ("profiles", {"profile"}),
        ("both", {"memory", "profile"}),
    ],
)
def test_manual_new_and_resume_mark_exact_scope_and_keep_receipt_controls(
    source, saved, payload, jobs, scope, expected
):
    meeting_id = saved()
    jobs()
    jobs("meeting_ingest")
    receipt = manual_analysis.request_analysis(payload(meeting_id, scope=scope))
    queued = digestion_db.get_record(meeting_id)
    assert set(queued["manual_analysis"]["work_requests"]) == expected
    for stage in expected:
        assert queued["manual_analysis"][stage]["request_id"] == receipt["request_id"]
        finish_stage(meeting_id, stage, status="failed")
    terminal = digestion_db.get_record(meeting_id)
    assert "work_requests" not in terminal["manual_analysis"]
    manual_stage.resume_request(receipt["request_id"])
    resumed = digestion_db.get_record(meeting_id)
    assert set(resumed["manual_analysis"]["work_requests"]) == expected
    assert all(
        marker["reason"] == "manual_resume"
        for marker in resumed["manual_analysis"]["work_requests"].values()
    )
    assert all(
        resumed["manual_analysis"][stage]["request_id"] == receipt["request_id"]
        for stage in expected
    )


def test_source_withdrawal_blocks_wake_without_mutating_queued_intent(source):
    meeting_id = pending_meeting(source)
    request(meeting_id, work_requests.STAGES)
    before = digestion_db.get_record(meeting_id)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE meeting_summaries SET available=false WHERE id=%s", (meeting_id,)
        )
    assert not digestion_db.has_requested_work([(source.provider, source.account_key)])
    assert not digestion_db.has_requested_profile_work(source.name)
    assert digestion_db.get_record(meeting_id) == before
