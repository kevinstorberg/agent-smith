import asyncio
import json
import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from psycopg2.extras import RealDictCursor

from services.db import get_connection
from services.meetings import db, service
from services.meetings import digestion_db
from services.meetings.config import load_source_config
from services.meetings.types import InvalidCursorError, MeetingProviderError, MeetingSummary, NotePage, NoteReference
from tests.conftest import clean_meeting_rows

STAMP = datetime(2026, 1, 1, tzinfo=timezone.utc)


def note(external_id="one", text="A useful meeting summary", *, updated_at=STAMP):
    return MeetingSummary(external_id, "Meeting " + external_id, text, None, "https://example.test/" + external_id, STAMP, updated_at)


def page(*summaries, next_cursor=None):
    return NotePage(tuple(NoteReference(item.external_id, item.provider_updated_at, item.provider_deleted_at) for item in summaries), next_cursor)


class Provider:
    def __init__(self, summaries, pages=None):
        self.summaries = {item.external_id: item for item in summaries}
        self.pages = pages if pages is not None else {None: page(*summaries)}
        self.list_calls = []
        self.list_cutoffs = []
        self.get_calls = []
        self.closed = False

    async def list_page(self, cursor=None, *, updated_after=None):
        self.list_calls.append(cursor)
        self.list_cutoffs.append(updated_after)
        result = self.pages[cursor]
        if isinstance(result, Exception):
            raise result
        return result

    async def get_summary(self, external_id):
        self.get_calls.append(external_id)
        return self.summaries.get(external_id)

    async def aclose(self):
        self.closed = True


@pytest.fixture
def source(monkeypatch):
    source_name, account = "sync-" + uuid4().hex, "account-" + uuid4().hex
    monkeypatch.setenv("MEETING_SOURCES_JSON", json.dumps({source_name: {
        "provider": "test", "account_key": account, "api_key_env": "MEETING_SYNC_TEST_KEY",
    }}))
    monkeypatch.setenv("MEETING_SYNC_TEST_KEY", "not-a-real-credential")
    config = load_source_config(source_name)
    yield config
    clean_meeting_rows(account)


def state(source):
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM meeting_sync_state WHERE provider = %s AND account_key = %s", (source.provider, source.account_key))
        row = cur.fetchone()
        return dict(row) if row else None


def require_deep_scan(source):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_sync_state SET last_deep_completed_at = clock_timestamp() - interval '25 hours' WHERE account_key = %s", (source.account_key,))


@pytest.mark.asyncio
async def test_full_scan_then_selective_scan_imports_changed_and_new_older_notes(source):
    first_note, second_note = note(), note("two")
    first_provider = Provider([first_note, second_note], {None: page(first_note, next_cursor="next"), "next": page(second_note)})
    first = await service.sync_source(source.name, provider=first_provider)
    assert first["created"] == 2
    assert first_provider.get_calls == ["one", "two"]
    assert first_provider.list_cutoffs == [None, None]
    assert first_provider.closed
    replay_provider = Provider([first_note, second_note])
    replay = await service.sync_source(source.name, provider=replay_provider)
    assert replay["unchanged"] >= 2
    assert replay_provider.get_calls == []
    changed = replace(first_note, summary_text="The decision changed", provider_updated_at=STAMP + timedelta(hours=1))
    old_new_note = replace(note("older-new-note"), provider_created_at=STAMP - timedelta(days=60))
    changed_provider = Provider([changed, second_note, old_new_note])
    result = await service.sync_source(source.name, provider=changed_provider)
    assert result["updated"] == 1
    assert result["created"] == 1
    assert changed_provider.get_calls == ["one", "older-new-note"]
    rows = db.list_summaries(source=source.name)["items"]
    assert len(rows) == 3
    assert next(row for row in rows if row["external_id"] == "one")["revision"] == 2


@pytest.mark.asyncio
async def test_daily_old_notes_are_not_refetched_without_a_new_source_timestamp(source):
    original = note()
    await service.sync_source(source.name, provider=Provider([original]))
    previous_start = state(source)["last_pull_started_at"]
    require_deep_scan(source)
    changed = replace(original, summary_text="Content changed without updated_at advancing")
    provider = Provider([changed])
    result = await service.sync_source(source.name, provider=provider)
    row = db.list_summaries(source=source.name)["items"][0]
    assert result["updated"] == 0
    assert result["deep"] is False
    assert provider.get_calls == []
    assert row["summary_text"] == original.summary_text
    assert row["revision"] == 1
    assert provider.list_cutoffs == [previous_start - timedelta(seconds=60)]


@pytest.mark.asyncio
async def test_explicit_project_change_updates_same_version_once_and_preserves_receipts(source):
    original = note()
    await service.sync_source(source.name, provider=Provider([original]))
    summary_id = db.list_summaries(source=source.name)["items"][0]["id"]
    receipt = digestion_db.get_record(summary_id)
    changed = replace(source, project="explicit-project")

    class RestartingProvider(Provider):
        expired = False

        async def list_page(self, cursor=None, *, updated_after=None):
            self.list_calls.append(cursor)
            self.list_cutoffs.append(updated_after)
            if cursor == "expired":
                self.expired = True
                raise InvalidCursorError("Cursor expired", 400)
            return page(original, next_cursor=None if self.expired else "expired")

    provider = RestartingProvider([original])
    result = await service.sync_source(source.name, config=changed, provider=provider)
    updated = db.get_summary(summary_id)
    assert result["updated"] == 1
    assert updated["project"] == "explicit-project"
    assert updated["revision"] == 2
    assert provider.list_calls == [None, "expired", None]
    assert provider.list_cutoffs == [None] * 3
    assert provider.get_calls == ["one"]
    assert digestion_db.get_record(summary_id) == receipt
    next_pull = Provider([original])
    await service.sync_source(source.name, config=changed, provider=next_pull)
    assert next_pull.list_cutoffs[0] is not None
    assert next_pull.get_calls == []
    assert db.get_summary(summary_id)["revision"] == 2


@pytest.mark.asyncio
async def test_budget_exhaustion_resumes_midpage_without_refetching_committed_item(source):
    first, second, third = note(), note("two"), note("three")
    pages = {None: page(first, second, next_cursor="next"), "next": page(third)}

    class PausingProvider(Provider):
        async def get_summary(self, external_id):
            if external_id == "two":
                await asyncio.Event().wait()
            return await super().get_summary(external_id)

    provider = PausingProvider([first, second, third], pages)
    result = await service.sync_source(source.name, provider=provider, run_budget_seconds=1)
    assert result["outcome"] == "continued"
    checkpoint = state(source)
    assert checkpoint["claim_owner"] is None
    assert checkpoint["scan"]["offset"] == 1
    assert checkpoint["scan"]["next_cursor"] == "next"
    assert db.list_summaries(source=source.name)["total"] == 1
    resumed = Provider([first, second, third], pages)
    result = await service.sync_source(source.name, provider=resumed)
    assert result["outcome"] == "completed"
    assert resumed.get_calls == ["two", "three"]
    assert resumed.list_calls == ["next"]
    assert db.list_summaries(source=source.name)["total"] == 3
    assert state(source)["scan"] == {}


@pytest.mark.asyncio
async def test_incremental_budget_resume_keeps_start_cutoff_and_committed_offset(source):
    await service.sync_source(source.name, provider=Provider([]))
    previous_start = state(source)["last_pull_started_at"]
    first, second, third = note(), note("two"), note("three")
    pages = {None: page(first, second, next_cursor="next"), "next": page(third)}

    class PausingProvider(Provider):
        async def get_summary(self, external_id):
            if external_id == "two":
                await asyncio.Event().wait()
            return await super().get_summary(external_id)

    provider = PausingProvider([first, second, third], pages)
    result = await service.sync_source(source.name, provider=provider, run_budget_seconds=1)
    assert result["outcome"] == "continued"
    checkpoint = state(source)
    assert checkpoint["last_pull_started_at"] == previous_start
    started = datetime.fromisoformat(checkpoint["scan"]["started_at"])
    cutoff = previous_start - timedelta(seconds=60)
    assert datetime.fromisoformat(checkpoint["scan"]["updated_after"]) == cutoff
    resumed = Provider([first, second, third], pages)
    await service.sync_source(source.name, provider=resumed)
    assert provider.list_cutoffs == resumed.list_cutoffs == [cutoff]
    assert resumed.list_calls == ["next"]
    assert resumed.get_calls == ["two", "three"]
    assert state(source)["last_pull_started_at"] == started


@pytest.mark.asyncio
async def test_success_anchors_to_start_not_finish_or_later_provider_update(source, monkeypatch):
    original_new_scan = service._new_scan
    started = datetime.now(timezone.utc) - timedelta(hours=2)

    def new_scan(state):
        return {**original_new_scan(state), "started_at": started.isoformat()}

    monkeypatch.setattr(service, "_new_scan", new_scan)
    await service.sync_source(source.name, provider=Provider([]))
    started += timedelta(hours=1)
    changed_during_pull = replace(note(), provider_updated_at=started + timedelta(minutes=5))
    await service.sync_source(source.name, provider=Provider([changed_during_pull]))
    assert state(source)["last_pull_started_at"] == started
    assert state(source)["last_completed_at"] > changed_during_pull.provider_updated_at
    next_pull = Provider([])
    await service.sync_source(source.name, provider=next_pull)
    assert next_pull.list_cutoffs == [started - timedelta(seconds=60)]


@pytest.mark.asyncio
async def test_failed_or_cancelled_incremental_pull_does_not_advance_boundary(source):
    await service.sync_source(source.name, provider=Provider([]))
    previous_start = state(source)["last_pull_started_at"]
    failed = Provider([], {None: MeetingProviderError("Synthetic failure")})
    with pytest.raises(MeetingProviderError):
        await service.sync_source(source.name, provider=failed)
    assert state(source)["last_pull_started_at"] == previous_start
    entered = asyncio.Event()

    class WaitingProvider(Provider):
        async def list_page(self, cursor=None, *, updated_after=None):
            self.list_cutoffs.append(updated_after)
            entered.set()
            await asyncio.Event().wait()

    waiting = WaitingProvider([])
    task = asyncio.create_task(service.sync_source(source.name, provider=waiting))
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert state(source)["last_pull_started_at"] == previous_start
    assert state(source)["claim_owner"] is None
    assert failed.list_cutoffs == waiting.list_cutoffs == [previous_start - timedelta(seconds=60)]


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["listing", "missing"])
async def test_legacy_checkpoint_upgrade_skips_unchanged_details_and_drops_omission_sweep(source, phase):
    original = note()
    await service.sync_source(source.name, provider=Provider([original]))
    db.claim_source(source, "legacy")
    legacy = service._new_scan({})
    legacy.pop("version")
    legacy.pop("updated_after")
    legacy.update(deep=True, phase=phase, page=[{"id": "one", "updated_at": STAMP.isoformat() if phase == "listing" else None, "deleted_at": None}])
    db.save_progress(source, "legacy", legacy)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_sync_state SET last_pull_started_at = NULL WHERE account_key = %s", (source.account_key,))
    db.release_source(source, "legacy", "continued")
    provider = Provider([original])
    await service.sync_source(source.name, provider=provider)
    assert provider.list_calls == provider.get_calls == []
    assert state(source)["last_pull_started_at"] == datetime.fromisoformat(legacy["started_at"])
    assert db.get_stored_refs(source)["one"]["available"]


@pytest.mark.asyncio
async def test_legacy_source_without_safe_boundary_gets_one_metadata_baseline(source):
    original = note()
    await service.sync_source(source.name, provider=Provider([original]))
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_sync_state SET last_pull_started_at = NULL WHERE account_key = %s", (source.account_key,))
    provider = Provider([original])
    await service.sync_source(source.name, provider=provider)
    assert provider.list_cutoffs == [None]
    assert provider.get_calls == []
    next_pull = Provider([original])
    await service.sync_source(source.name, provider=next_pull)
    assert next_pull.list_cutoffs[0] is not None
    assert next_pull.get_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("version", 2), ("version", True), ("started_at", "2026-01-01"), ("updated_after", "2026-01-01"), ("updated_after", "9999-01-01T00:00:00Z")])
async def test_invalid_checkpoint_fails_before_provider_requests(source, field, value):
    db.claim_source(source, "seed")
    checkpoint = service._new_scan({})
    checkpoint[field] = value
    db.save_progress(source, "seed", checkpoint)
    db.release_source(source, "seed", "continued")
    provider = Provider([])
    with pytest.raises(ValueError, match="checkpoint"):
        await service.sync_source(source.name, provider=provider)
    assert provider.list_calls == provider.get_calls == []
    assert state(source)["last_pull_started_at"] is None


@pytest.mark.asyncio
async def test_note_not_ready_retries_next_run_and_then_imports(source):
    summary = note()
    pending = Provider([], {None: page(summary)})
    first = await service.sync_source(source.name, provider=pending)
    assert first["outcome"] == "continued"
    assert db.list_summaries(source=source.name)["total"] == 0
    ready = await service.sync_source(source.name, provider=Provider([summary]))
    assert ready["created"] == 1
    assert ready["outcome"] == "completed"


@pytest.mark.asyncio
async def test_new_note_missing_three_times_finishes_with_warning_without_empty_row(source):
    reference = note()
    results = []
    for _ in range(3):
        provider = Provider([], {None: page(reference)})
        results.append(await service.sync_source(source.name, provider=provider))
        assert provider.get_calls == ["one"]
        assert db.list_summaries(source=source.name)["total"] == 0
    assert [result["outcome"] for result in results] == ["continued", "continued", "completed_with_warnings"]
    assert state(source)["scan"] == {}


@pytest.mark.asyncio
async def test_incremental_listing_absence_never_rechecks_or_hides_old_notes(source):
    summary = note()
    await service.sync_source(source.name, provider=Provider([summary]))
    summary_id = db.list_summaries(source=source.name)["items"][0]["id"]
    require_deep_scan(source)
    for _ in range(3):
        provider = Provider([])
        result = await service.sync_source(source.name, provider=provider)
        assert provider.get_calls == []
        assert db.get_stored_refs(source)["one"]["missing_count"] == 0
        assert db.get_summary(summary_id) is not None
    assert result["outcome"] == "completed"
    assert db.get_summary(summary_id)["revision"] == 1


@pytest.mark.asyncio
async def test_list_tombstone_hides_stored_summary_even_when_detail_is_unavailable(source):
    summary = note()
    await service.sync_source(source.name, provider=Provider([summary]))
    summary_id = db.list_summaries(source=source.name)["items"][0]["id"]
    deleted = replace(summary, provider_deleted_at=STAMP + timedelta(hours=1))
    await service.sync_source(source.name, provider=Provider([], {None: page(deleted)}))
    assert db.get_summary(summary_id) is None
    assert db.get_summary(summary_id, include_unavailable=True)["provider_deleted_at"] == deleted.provider_deleted_at.isoformat()


@pytest.mark.asyncio
async def test_empty_continuation_page_does_not_end_listing(source):
    summary = note()
    provider = Provider([summary], {None: NotePage((), "next"), "next": page(summary)})
    result = await service.sync_source(source.name, provider=provider)
    assert result["created"] == 1
    assert provider.list_calls == [None, "next"]


@pytest.mark.asyncio
async def test_pagination_cursor_cycle_fails_with_visible_safe_diagnostics(source):
    provider = Provider([], {None: NotePage((), "first"), "first": NotePage((), "second"), "second": NotePage((), "first")})
    with pytest.raises(MeetingProviderError, match="[Cc]ursor|[Cc]ycle|[Pp]agination"):
        await service.sync_source(source.name, provider=provider)
    assert provider.closed
    assert state(source)["claim_owner"] is None
    assert state(source)["outcome"] == "failed"


@pytest.mark.asyncio
async def test_invalid_cursor_restarts_once_and_recovers_without_duplicate_summaries(source):
    first, second = note(), note("two")
    await service.sync_source(source.name, provider=Provider([]))
    cutoff = state(source)["last_pull_started_at"] - timedelta(seconds=60)

    class CursorExpiryProvider(Provider):
        expired = False

        async def list_page(self, cursor=None, *, updated_after=None):
            self.list_calls.append(cursor)
            self.list_cutoffs.append(updated_after)
            if cursor == "expired":
                self.expired = True
                raise InvalidCursorError("Cursor expired", 400)
            if cursor is None:
                return page(first, next_cursor="fresh" if self.expired else "expired")
            return page(second)

    provider = CursorExpiryProvider([first, second])
    await service.sync_source(source.name, provider=provider)
    assert provider.list_calls == [None, "expired", None, "fresh"]
    assert provider.list_cutoffs == [cutoff] * 4
    assert provider.get_calls == ["one", "two"]
    rows = db.list_summaries(source=source.name)["items"]
    assert len(rows) == 2
    assert all(row["revision"] == 1 for row in rows)


@pytest.mark.asyncio
async def test_repeated_invalid_cursor_stops_after_one_restart(source):
    provider = Provider([], {None: NotePage((), "expired"), "expired": InvalidCursorError("Cursor expired", 400)})
    with pytest.raises(MeetingProviderError):
        await service.sync_source(source.name, provider=provider)
    assert provider.list_calls == [None, "expired", None, "expired"]
    assert state(source)["outcome"] == "failed"


@pytest.mark.asyncio
async def test_concurrent_source_run_skips_busy_and_closes_both_providers(source):
    entered, release = asyncio.Event(), asyncio.Event()

    class WaitingProvider(Provider):
        async def list_page(self, cursor=None, *, updated_after=None):
            entered.set()
            await release.wait()
            return await super().list_page(cursor, updated_after=updated_after)

    first_provider, second_provider = WaitingProvider([]), Provider([])
    first = asyncio.create_task(service.sync_source(source.name, provider=first_provider))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        result = await service.sync_source(source.name, provider=second_provider)
        assert result["outcome"] == "skipped_busy"
        assert second_provider.list_calls == []
    finally:
        release.set()
        await asyncio.wait_for(first, 5)
    assert first_provider.closed and second_provider.closed


@pytest.mark.asyncio
async def test_cancellation_drains_inflight_summary_write_before_releasing_claim(source, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original_save, original_release = db.save_progress, db.release_source
    events = []

    def blocking_save(*args, **kwargs):
        if kwargs.get("summary") is not None:
            entered.set()
            if not release.wait(5):
                raise RuntimeError("Test did not release summary transaction")
            result = original_save(*args, **kwargs)
            events.append("write_committed")
            return result
        return original_save(*args, **kwargs)

    def record_release(*args, **kwargs):
        events.append("claim_released")
        return original_release(*args, **kwargs)

    monkeypatch.setattr(db, "save_progress", blocking_save)
    monkeypatch.setattr(db, "release_source", record_release)
    provider = Provider([note()])
    task = asyncio.create_task(service.sync_source(source.name, provider=provider))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        assert state(source)["claim_owner"] is not None
        assert "claim_released" not in events
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
    assert events == ["write_committed", "claim_released"]
    assert state(source)["claim_owner"] is None
    assert state(source)["outcome"] == "interrupted"
    assert provider.closed
    assert db.list_summaries(source=source.name)["total"] == 1
    resumed = await service.sync_source(source.name, provider=Provider([note()]))
    assert resumed["outcome"] == "completed"
    assert db.list_summaries(source=source.name)["items"][0]["revision"] == 1


@pytest.mark.asyncio
async def test_cancellation_during_claim_acquisition_releases_its_server_applied_claim(source, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original_claim = db.claim_source

    def blocking_claim(*args, **kwargs):
        result = original_claim(*args, **kwargs)
        entered.set()
        if not release.wait(5):
            raise RuntimeError("Test did not release claim acquisition")
        return result

    monkeypatch.setattr(db, "claim_source", blocking_claim)
    provider = Provider([])
    task = asyncio.create_task(service.sync_source(source.name, provider=provider))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        assert state(source)["claim_owner"] is not None
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
    assert state(source)["claim_owner"] is None
    assert state(source)["outcome"] == "interrupted"
    assert provider.list_calls == []
    assert provider.closed
