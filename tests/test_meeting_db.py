from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from services.db import get_connection
from services.meetings import db
from services.meetings.config import SourceConfig
from services.meetings.types import MeetingSummary
from tests.conftest import clean_meeting_rows


@pytest.fixture
def config():
    config = SourceConfig("db-test-" + uuid4().hex, "test", "account-" + uuid4().hex, "secret-never-persist")
    yield config
    clean_meeting_rows(config.account_key)


@pytest.fixture
def summary():
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return MeetingSummary(
        "external-1", "Planning meeting", "Build the meeting importer", None,
        "https://example.test/meeting/1", stamp, stamp,
        metadata={"attendees": [{"name": "Example", "email": "example@example.test"}]},
    )


def test_summary_replay_preserves_identity_and_revision(config, summary):
    db.claim_source(config, "run")
    checkpoint = {"id": "scan-1", "offset": 1}
    first = db.save_progress(config, "run", checkpoint, summary=summary)
    replay = db.save_progress(config, "run", checkpoint, summary=replace(summary, provider_updated_at=summary.provider_updated_at + timedelta(hours=1)))
    row = db.get_summary(first["id"])
    assert first == {"id": first["id"], "revision": 1, "status": "created"}
    assert replay == {"id": first["id"], "revision": 1, "status": "unchanged"}
    assert row["summary_text"] == summary.summary_text
    assert row["metadata"] == summary.metadata
    assert row["last_seen_scan_id"] == "scan-1"
    assert row["first_seen_at"] == row["updated_at"]
    assert row["meeting_start"] is None
    refs = db.get_stored_refs(config)
    assert refs[summary.external_id]["provider_updated_at"].utcoffset() == timedelta(0)


def test_changed_payload_increments_revision_and_older_response_cannot_overwrite(config, summary):
    db.claim_source(config, "run")
    first = db.save_progress(config, "run", {}, summary=summary)
    changed = replace(summary, summary_text="Create the importer and tests", provider_updated_at=summary.provider_updated_at + timedelta(hours=1))
    updated = db.save_progress(config, "run", {}, summary=changed)
    stale = db.save_progress(config, "run", {"id": "current", "offset": 3}, summary=summary)
    assert updated == {"id": first["id"], "revision": 2, "status": "updated"}
    assert stale == {"id": first["id"], "revision": 2, "status": "stale"}
    assert db.get_summary(first["id"])["summary_text"] == changed.summary_text
    assert db.get_stored_refs(config)[summary.external_id]["last_seen_scan_id"] == "current"
    db.release_source(config, "run", "continued")
    assert db.claim_source(config, "next")["scan"] == {"id": "current", "offset": 3}


def test_equal_timestamp_content_edit_is_detected(config, summary):
    db.claim_source(config, "run")
    first = db.save_progress(config, "run", {}, summary=summary)
    edit = db.save_progress(config, "run", {}, summary=replace(summary, title="Revised title"))
    assert edit["id"] == first["id"]
    assert edit["revision"] == 2


def test_unique_identity_is_namespaced_by_provider_and_account(config, summary):
    other = replace(config, provider="other")
    db.claim_source(config, "first")
    db.claim_source(other, "second")
    first = db.save_progress(config, "first", {}, summary=summary)
    second = db.save_progress(other, "second", {}, summary=summary)
    assert first["id"] != second["id"]


def test_claim_blocks_alias_and_stale_writes_after_takeover(config, summary):
    assert db.claim_source(config, "first") is not None
    assert db.claim_source(replace(config, name="alias"), "second") is None
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_sync_state SET claim_until = clock_timestamp() - interval '1 second' WHERE account_key = %s", (config.account_key,))
    with pytest.raises(db.ClaimLostError):
        db.save_progress(config, "first", {}, summary=summary)
    assert db.claim_source(config, "second") is not None
    with pytest.raises(db.ClaimLostError):
        db.save_progress(config, "first", {}, summary=summary)
    db.release_source(config, "first", "failed", error="secret payload")
    assert db.claim_source(config, "third") is None
    assert db.save_progress(config, "second", {}, summary=summary)["status"] == "created"


def test_changed_configuration_restarts_checkpoint_when_claim_released(config):
    db.claim_source(config, "first")
    db.save_progress(config, "first", {"id": "old", "cursor": "private-cursor"})
    db.finish_scan(config, "first", {"phase": "done", "started_at": datetime.now(timezone.utc).isoformat()})
    db.save_progress(config, "first", {"id": "old", "cursor": "private-cursor"})
    changed = replace(config, project="new-project")
    assert db.claim_source(changed, "second") is None
    with pytest.raises(db.ClaimLostError):
        db.save_progress(changed, "first", {})
    db.release_source(config, "first", "continued")
    state = db.claim_source(changed, "second")
    assert state["scan"] == {}
    assert state["last_pull_started_at"] is None


def test_source_rename_keeps_boundary_checkpoint_and_relabels_stored_rows(config, summary):
    db.claim_source(config, "first")
    saved = db.save_progress(config, "first", {}, summary=summary)
    started = datetime.now(timezone.utc) - timedelta(minutes=5)
    db.finish_scan(config, "first", {"phase": "done", "started_at": started.isoformat()})
    checkpoint = {"id": "continuing", "cursor": "next"}
    db.save_progress(config, "first", checkpoint)
    db.release_source(config, "first", "continued")
    renamed = replace(config, name="renamed-" + uuid4().hex)
    state = db.claim_source(renamed, "next")
    assert state["last_pull_started_at"] == started
    assert state["scan"] == checkpoint
    assert db.get_summary(saved["id"])["source_name"] == renamed.name
    assert db.get_summary(saved["id"])["revision"] == 1


@pytest.mark.parametrize("checkpoint", [{}, {"phase": "listing", "started_at": "2026-01-01T00:00:00Z"}, {"phase": "done", "started_at": "2026-01-01"}])
def test_incomplete_or_unsafe_scan_cannot_advance_pull_boundary(config, checkpoint):
    db.claim_source(config, "run")
    with pytest.raises(ValueError):
        db.finish_scan(config, "run", checkpoint)
    db.release_source(config, "run", "failed")
    assert db.claim_source(config, "retry")["last_pull_started_at"] is None


def test_meeting_pull_watermark_schema_is_nullable_timezone_aware():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT data_type, is_nullable, column_default FROM information_schema.columns
                       WHERE table_name = 'meeting_sync_state' AND column_name = 'last_pull_started_at'""")
        assert cur.fetchone() == ("timestamp with time zone", "YES", None)


def test_checkpoint_and_summary_roll_back_together(config, summary, monkeypatch):
    db.claim_source(config, "run")

    def fail_checkpoint(*args):
        raise RuntimeError("checkpoint failed")

    with monkeypatch.context() as patch:
        patch.setattr(db, "_save_scan", fail_checkpoint)
        with pytest.raises(RuntimeError, match="checkpoint failed"):
            db.save_progress(config, "run", {"offset": 1}, summary=summary)
    assert db.list_summaries(source=config.name)["total"] == 0
    db.release_source(config, "run", "failed")
    assert db.claim_source(config, "retry")["scan"] == {}


def test_third_missing_observation_hides_summary_and_recovery_restores_it(config, summary):
    db.claim_source(config, "run")
    saved = db.save_progress(config, "run", {}, summary=summary)
    for miss in range(1, 4):
        db.save_progress(config, "run", {"miss": miss}, unavailable_id=summary.external_id)
        assert db.get_stored_refs(config)[summary.external_id]["missing_count"] == miss
        assert db.get_summary(saved["id"], include_unavailable=True)["available"] is (miss < 3)
    assert db.list_summaries(source=config.name)["total"] == 0
    assert db.get_summary(saved["id"]) is None
    assert db.get_summary(saved["id"], include_unavailable=True)["revision"] == 2
    db.save_progress(config, "run", {}, unavailable_id=summary.external_id)
    assert db.get_summary(saved["id"], include_unavailable=True)["revision"] == 2
    restored = db.save_progress(config, "run", {}, summary=summary)
    assert restored["revision"] == 3
    assert db.list_summaries(source=config.name)["total"] == 1
    assert db.get_stored_refs(config)[summary.external_id]["missing_count"] == 0
    assert db.save_progress(config, "run", {}, unavailable_id="not-imported") is None


def test_deleted_summary_hidden_immediately(config, summary):
    db.claim_source(config, "run")
    saved = db.save_progress(config, "run", {}, summary=replace(summary, provider_deleted_at=summary.provider_updated_at))
    assert db.get_summary(saved["id"]) is None
    assert db.get_summary(saved["id"], include_unavailable=True)["available"] is False
    assert db.list_summaries(source=config.name)["total"] == 0


def test_seen_observation_updates_provenance_without_changing_content(config, summary):
    db.claim_source(config, "run")
    saved = db.save_progress(config, "run", {"id": "first"}, summary=summary)
    db.save_progress(config, "run", {"id": "second"}, seen_id=summary.external_id)
    row = db.get_summary(saved["id"])
    assert row["last_seen_scan_id"] == "second"
    assert row["revision"] == 1


def test_list_tombstone_hides_summary_immediately_when_detail_is_unavailable(config, summary):
    db.claim_source(config, "run")
    saved = db.save_progress(config, "run", {}, summary=summary)
    deleted = summary.provider_updated_at + timedelta(hours=1)
    db.save_progress(config, "run", {"id": "deletion-scan"}, unavailable_id=summary.external_id, deleted_at=deleted, observed_updated_at=deleted)
    assert db.get_summary(saved["id"]) is None
    row = db.get_summary(saved["id"], include_unavailable=True)
    assert row["provider_deleted_at"] == deleted.isoformat()
    assert row["revision"] == 2
    assert row["last_seen_scan_id"] == "deletion-scan"
    db.save_progress(config, "run", {}, unavailable_id=summary.external_id, deleted_at=deleted, observed_updated_at=deleted)
    assert db.get_summary(saved["id"], include_unavailable=True)["revision"] == 2


def test_tombstone_version_prevents_stale_detail_resurrection(config, summary):
    db.claim_source(config, "run")
    saved = db.save_progress(config, "run", {}, summary=summary)
    version_two = summary.provider_updated_at + timedelta(hours=1)
    db.save_progress(config, "run", {}, unavailable_id=summary.external_id, deleted_at=version_two, observed_updated_at=version_two)
    stale = db.save_progress(config, "run", {}, summary=summary)
    assert stale["status"] == "stale"
    assert db.get_summary(saved["id"]) is None
    row = db.get_summary(saved["id"], include_unavailable=True)
    assert row["provider_updated_at"] == version_two.isoformat()
    assert row["revision"] == 2
    deleted_detail = replace(summary, provider_updated_at=version_two, provider_deleted_at=version_two)
    duplicate = db.save_progress(config, "run", {}, summary=deleted_detail)
    assert duplicate["status"] == "unchanged"
    assert duplicate["revision"] == 2


def test_older_tombstone_cannot_hide_newer_summary(config, summary):
    db.claim_source(config, "run")
    fresh = replace(summary, provider_updated_at=summary.provider_updated_at + timedelta(hours=2))
    saved = db.save_progress(config, "run", {}, summary=fresh)
    old_version = summary.provider_updated_at + timedelta(hours=1)
    ignored = db.save_progress(config, "run", {"id": "old-list"}, unavailable_id=summary.external_id, deleted_at=old_version, observed_updated_at=old_version)
    assert ignored["status"] == "stale"
    row = db.get_summary(saved["id"])
    assert row["revision"] == 1
    assert row["available"] is True
    assert row["last_seen_scan_id"] == "old-list"


def test_readers_filter_project_source_text_dates_and_page(config, summary):
    config = replace(config, project="project-one")
    db.claim_source(config, "run")
    db.save_progress(config, "run", {}, summary=summary)
    db.save_progress(config, "run", {}, summary=replace(summary, external_id="external-2", summary_text="Something different", provider_created_at=summary.provider_created_at + timedelta(days=1)))
    assert db.list_summaries(source=config.name, project="project-one", query="IMPORTER")["total"] == 1
    assert db.list_summaries(source=config.name, project="other")["total"] == 0
    page = db.list_summaries(source=config.name, limit=1)
    assert page["total"] == 2
    assert page["items"][0]["external_id"] == "external-2"
    assert db.list_summaries(source=config.name, limit=1, offset=1)["items"][0]["external_id"] == "external-1"
    assert db.list_summaries(source=config.name, after="2026-01-02T00:00:00Z")["total"] == 1
    assert db.list_summaries(source=config.name, before="2026-01-01T12:00:00Z")["total"] == 1
    assert db.get_summary(str(uuid4())) is None
    assert db.list_summaries(source=config.name, query="' OR true --")["total"] == 0


def test_calendar_times_are_optional_and_used_in_date_filters(config, summary):
    db.claim_source(config, "run")
    summary = replace(summary, metadata={"calendar_event": {"scheduled_start_time": "2026-02-01T10:00:00Z", "scheduled_end_time": None}})
    row = db.save_progress(config, "run", {}, summary=summary)
    assert db.get_summary(row["id"])["meeting_start"] == "2026-02-01T10:00:00+00:00"
    assert db.list_summaries(source=config.name, after="2026-02-01T00:00:00Z")["total"] == 1


def test_source_status_excludes_cursor_credentials_and_note_content(config):
    db.claim_source(config, "run")
    started_at = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    db.save_progress(config, "run", {"id": "scan", "started_at": started_at, "cursor": "private-cursor", "pending": ["private-note-id"], "counts": {"created": 1, "private": "note-content"}})
    db.release_source(config, "run", "failed", "secret payload")
    row = db.source_status(config.name)[0]
    assert row["outcome"] == "failed"
    assert row["counts"] == {"created": 1}
    assert row["degraded"] is True
    assert row["scan_age_seconds"] >= 172800
    assert "private-cursor" not in str(row)
    assert "private-note-id" not in str(row)
    assert "secret" not in str(row)


def test_sql_errors_hide_meeting_content():
    with pytest.raises(db.MeetingStorageError) as captured:
        with db._cursor() as cur:
            cur.execute("SELECT %s::integer", ("private-meeting-content",))
    assert str(captured.value) == "Meeting storage operation failed (SQLSTATE 22P02)"
    assert captured.value.__suppress_context__ is True


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"offset": -1}, {"query": ""}, {"after": "not-a-date"}, {"after": "2026-01-01"}, {"after": "2026-02-01T00:00:00Z", "before": "2026-01-01T00:00:00Z"}])
def test_reader_rejects_invalid_boundary_inputs(kwargs):
    with pytest.raises(ValueError):
        db.list_summaries(**kwargs)


def test_rejects_invalid_identity_and_summary_before_commit(config, summary):
    with pytest.raises(ValueError):
        db.get_summary("not-a-uuid")
    with pytest.raises(ValueError):
        db.claim_source(config, "")
    db.claim_source(config, "run")
    with pytest.raises(ValueError):
        db.save_progress(config, "run", {}, summary=replace(summary, summary_text=" "))
    with pytest.raises(ValueError):
        db.save_progress(config, "run", {}, summary=replace(summary, provider_updated_at=datetime(2026, 1, 1)))
    with pytest.raises(ValueError):
        db.save_progress(config, "run", {}, summary=summary, seen_id=summary.external_id)
