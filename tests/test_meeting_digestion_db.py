import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.routers.meetings import router
from services.db import get_connection
from services.meetings import db, digestion_db
from services.meetings.types import TranscriptSegment
from tests.conftest import clean_meeting_rows
from tests.test_meeting_db import config as config, summary as summary


@pytest.fixture
def saved(config, summary):
    db.claim_source(config, "ingest")
    return db.save_progress(config, "ingest", {"offset": 1}, summary=summary)["id"]


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/api/meetings")
    return TestClient(app)


def identities(config):
    return [(config.provider, config.account_key)]


def transcript(summary):
    return {"segments": [
        TranscriptSegment(f"Evidence {index}", {"diarization_label": "Speaker A"}, summary.provider_created_at).to_dict(index)
        for index in range(1, 4)
    ], "cursor": None}


def test_digestion_enrolls_once_on_new_insert_and_survives_lost_return_value(config, summary, saved):
    first = digestion_db.get_record(saved)
    assert first["transcript_status"] == "pending" and first["attempts"] == 0
    assert first["transcript"] == first["snapshot"] == {}
    replay = db.save_progress(config, "ingest", {"offset": 2}, summary=summary)
    edited = db.save_progress(config, "ingest", {"offset": 3}, summary=replace(summary, title="Edited later"))
    assert replay["status"] == "unchanged" and edited["status"] == "updated"
    assert digestion_db.get_record(saved) == first
    claimed = digestion_db.claim_transcript(identities(config), "another-process")
    assert claimed["meeting_id"] == saved
    assert claimed["claim_owner"] == "another-process"


def test_legacy_summary_without_digestion_is_not_backfilled_by_replay(config, summary, saved):
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("DELETE FROM meeting_digestions WHERE meeting_id = %s", (saved,))
    db.save_progress(config, "ingest", {}, summary=summary)
    db.save_progress(config, "ingest", {}, summary=replace(summary, title="Legacy edit"))
    assert digestion_db.get_record(saved) is None
    assert digestion_db.claim_transcript(identities(config), "reader") is None
    assert digestion_db.get_transcript(saved)["status"] == "not_imported"


@pytest.mark.parametrize("failure_at", ["enrollment", "checkpoint"])
def test_summary_enrollment_and_checkpoint_roll_back_atomically(config, summary, monkeypatch, failure_at):
    db.claim_source(config, "ingest")
    inserted = []
    original_enroll = digestion_db.enroll

    def enroll_then_fail(cursor, meeting_id):
        inserted.append(meeting_id)
        original_enroll(cursor, meeting_id)
        if failure_at == "enrollment":
            raise RuntimeError("Enrollment interrupted")

    def checkpoint_failed(*args):
        raise RuntimeError("Checkpoint interrupted")

    with monkeypatch.context() as patch:
        patch.setattr(digestion_db, "enroll", enroll_then_fail)
        if failure_at == "checkpoint":
            patch.setattr(db, "_save_scan", checkpoint_failed)
        with pytest.raises(RuntimeError, match="interrupted"):
            db.save_progress(config, "ingest", {"offset": 1}, summary=summary)
    assert len(inserted) == 1
    assert digestion_db.get_record(inserted[0]) is None
    assert db.get_summary(inserted[0]) is None
    db.release_source(config, "ingest", "failed")
    assert db.claim_source(config, "retry")["scan"] == {}
    recovered = db.save_progress(config, "retry", {"offset": 1}, summary=summary)
    assert digestion_db.get_record(recovered["id"])["transcript_status"] == "pending"


def test_digestion_claim_serializes_different_accounts_and_fences_old_owner(config, summary, saved):
    other = replace(config, name="other-" + uuid4().hex, account_key="other-" + uuid4().hex)
    try:
        db.claim_source(other, "import-other")
        db.save_progress(other, "import-other", {}, summary=summary)
        claimed = digestion_db.claim_transcript(identities(config), "first")
        assert claimed["meeting_id"] == saved
        assert digestion_db.claim_transcript(identities(other), "other-device") is None
        digestion_db.release(saved, "wrong-owner")
        assert digestion_db.get_record(saved)["claim_owner"] == "first"
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE meeting_digestions SET claim_until = clock_timestamp() - interval '1 second' WHERE meeting_id = %s", (saved,))
        replacement = digestion_db.claim_transcript(identities(config), "second")
        assert replacement["meeting_id"] == saved
        with pytest.raises(db.ClaimLostError):
            digestion_db.save_capture(saved, "first", digestion_db.get_context(saved), transcript(summary), complete=True)
        with pytest.raises(db.ClaimLostError):
            digestion_db.record_failure(saved, "first", "Interrupted")
        digestion_db.release(saved, "first")
        assert digestion_db.get_record(saved)["claim_owner"] == "second"
        digestion_db.release(saved, "second")
        assert digestion_db.claim_transcript(identities(other), "other-device") is not None
    finally:
        clean_meeting_rows(other.account_key)


def test_concurrent_digestion_claims_have_one_global_owner(config, saved):
    barrier = threading.Barrier(2)

    def claim(owner):
        barrier.wait(timeout=5)
        return digestion_db.claim_transcript(identities(config), owner)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, ("device-a", "device-b")))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1 and winners[0]["meeting_id"] == saved


@pytest.mark.parametrize("change", ["provider_version", "revision", "snapshot_identity"])
def test_capture_rejects_changed_meeting_or_wrong_snapshot(config, summary, saved, change):
    digestion_db.claim_transcript(identities(config), "capture")
    snapshot = digestion_db.get_context(saved)
    if change == "snapshot_identity":
        snapshot = {**snapshot, "id": str(uuid4())}
    else:
        edited = replace(summary, title="Changed during capture")
        if change == "provider_version":
            edited = replace(edited, provider_updated_at=summary.provider_updated_at + timedelta(hours=1))
        db.save_progress(config, "ingest", {}, summary=edited)
    with pytest.raises(db.ClaimLostError):
        digestion_db.save_capture(saved, "capture", snapshot, transcript(summary), complete=True)
    record = digestion_db.get_record(saved)
    assert record["transcript_status"] == "pending"
    assert record["transcript_hash"] is None and record["transcript"] == {}


def test_partial_capture_is_hidden_and_checkpoint_resumes_under_new_owner(config, summary, saved):
    digestion_db.claim_transcript(identities(config), "capture-one")
    snapshot = digestion_db.get_context(saved)
    partial = {"segments": transcript(summary)["segments"][:1], "cursor": "next-page"}
    digestion_db.save_capture(saved, "capture-one", snapshot, partial)
    public = digestion_db.get_transcript(saved)
    assert public["status"] == "capturing" and public["items"] == [] and public["total"] == 0
    digestion_db.release(saved, "capture-one")
    resumed = digestion_db.claim_transcript(identities(config), "capture-two")
    assert resumed["transcript"] == partial and resumed["snapshot"] == snapshot
    digestion_db.save_capture(saved, "capture-two", snapshot, transcript(summary), complete=True)
    digestion_db.release(saved, "capture-two")
    assert digestion_db.get_transcript(saved)["status"] == "ready"


def test_complete_transcript_has_stable_hash_and_paginated_http_reader(config, summary, saved, client):
    full = transcript(summary)
    digestion_db.claim_transcript(identities(config), "capture")
    digestion_db.save_capture(saved, "capture", digestion_db.get_context(saved), full, complete=True)
    digestion_db.release(saved, "capture")
    expected_hash = hashlib.sha256(json.dumps(full["segments"], sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    record = digestion_db.get_record(saved)
    assert record["transcript_hash"] == expected_hash and record["captured_at"] is not None
    page = client.get(f"/api/meetings/{saved}/transcript", params={"offset": 1, "limit": 1})
    assert page.status_code == 200
    assert page.json()["status"] == "ready" and page.json()["total"] == 3
    assert [{key: item[key] for key in full["segments"][1]} for item in page.json()["items"]] == full["segments"][1:2]
    assert page.json()["items"][0]["effective_speaker"]["profile_id"] is None
    assert page.json()["offset"] == page.json()["limit"] == 1
    assert "snapshot" not in page.json() and "claim_owner" not in page.json()
    assert "transcript" not in client.get(f"/api/meetings/{saved}").json()
    second = db.save_progress(config, "ingest", {}, summary=replace(summary, external_id="hash-peer"))["id"]
    digestion_db.claim_transcript(identities(config), "capture-peer")
    reordered = {"segments": [dict(reversed(list(item.items()))) for item in full["segments"]]}
    digestion_db.save_capture(second, "capture-peer", digestion_db.get_context(second), reordered, complete=True)
    assert digestion_db.get_record(second)["transcript_hash"] == expected_hash


def test_transcript_deletion_tombstone_blocks_retry_replay_and_stale_capture(config, summary, saved, client):
    digestion_db.claim_transcript(identities(config), "capture")
    snapshot = digestion_db.get_context(saved)
    digestion_db.save_capture(saved, "capture", snapshot, transcript(summary), complete=True)
    response = client.delete(f"/api/meetings/{saved}/transcript")
    assert response.status_code == 200 and response.json()["deleted"]
    record = digestion_db.get_record(saved)
    assert record["transcript_status"] == "deleted"
    assert record["transcript"] == record["snapshot"] == {}
    assert record["transcript_hash"] is None and record["claim_owner"] is None
    with pytest.raises(db.ClaimLostError):
        digestion_db.save_capture(saved, "capture", snapshot, transcript(summary), complete=True)
    with pytest.raises(ValueError, match="cannot be retried"):
        digestion_db.retry_transcript(saved)
    db.save_progress(config, "ingest", {}, summary=replace(summary, title="Later edit"))
    assert digestion_db.claim_transcript(identities(config), "retry") is None
    result = client.get(f"/api/meetings/{saved}/transcript").json()
    assert result["status"] == "deleted" and result["items"] == [] and result["total"] == 0


def test_provider_deletion_prevents_capture_commit_claim_and_http_read(config, summary, saved, client):
    digestion_db.claim_transcript(identities(config), "capture")
    snapshot = digestion_db.get_context(saved)
    deleted = summary.provider_updated_at + timedelta(hours=1)
    db.save_progress(config, "ingest", {}, unavailable_id=summary.external_id, deleted_at=deleted, observed_updated_at=deleted)
    with pytest.raises(db.ClaimLostError):
        digestion_db.save_capture(saved, "capture", snapshot, transcript(summary), complete=True)
    digestion_db.release(saved, "capture")
    assert digestion_db.claim_transcript(identities(config), "next") is None
    assert digestion_db.get_transcript(saved) is None
    assert client.get(f"/api/meetings/{saved}/transcript").status_code == 404


def test_failure_retry_keeps_safe_diagnostics_and_bounded_attempts(config, saved):
    for attempt in range(1, 4):
        digestion_db.claim_transcript(identities(config), "capture")
        digestion_db.record_failure(saved, "capture", "MeetingProviderError")
        digestion_db.release(saved, "capture")
        record = digestion_db.get_record(saved)
        assert record["attempts"] == attempt and record["error_type"] == "MeetingProviderError"
        assert record["transcript_status"] == ("failed" if attempt == 3 else "pending")
        assert digestion_db.claim_transcript(identities(config), "too-soon") is None
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE meeting_digestions SET next_attempt_at = clock_timestamp() WHERE meeting_id = %s", (saved,))
    digestion_db.retry_transcript(saved)
    retried = digestion_db.get_record(saved)
    assert retried["attempts"] == 0 and retried["error_type"] is None
    assert digestion_db.claim_transcript(identities(config), "retry") is not None
    with pytest.raises(ValueError, match="safe error category"):
        digestion_db.record_failure(saved, "retry", "private body with credential")


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}, {"limit": True}])
def test_transcript_reader_rejects_invalid_paging(saved, params):
    with pytest.raises(ValueError, match="limit"):
        digestion_db.get_transcript(saved, **params)


@pytest.mark.parametrize("owner", ["", "   ", "x" * 101])
def test_digestion_claim_owner_must_be_nonblank_and_bounded(config, saved, owner):
    with pytest.raises(ValueError, match="owner"):
        digestion_db.claim_transcript(identities(config), owner)
