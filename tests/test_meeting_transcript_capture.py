import asyncio
import json
import math
import os
import threading
from dataclasses import replace
from datetime import timedelta

import pytest

from services.meetings import db, digestion, digestion_db
from services.meetings.config import load_source_config
from services.meetings.types import InvalidCursorError, MeetingProviderError, TranscriptPage, TranscriptSegment
from tests.conftest import clean_meeting_rows
from tests.test_meeting_sync import STAMP, note, source as source


def transcript_page(text="Recorded decision", next_cursor=None):
    segment = TranscriptSegment(text, {"diarization_label": "Speaker 1"}, STAMP, STAMP + timedelta(seconds=2))
    return TranscriptPage((segment,), next_cursor)


def enroll(config, summary):
    db.claim_source(config, "transcript-enroller")
    try:
        return db.save_progress(config, "transcript-enroller", {}, summary=summary)["id"]
    finally:
        db.release_source(config, "transcript-enroller", "completed")


class Provider:
    def __init__(self, summary, pages=None):
        self.summary = summary
        self.pages = pages or {None: transcript_page()}
        self.summary_calls = []
        self.page_calls = []
        self.closed = False

    async def get_summary(self, external_id):
        self.summary_calls.append(external_id)
        return self.summary

    async def get_transcript_page(self, external_id, cursor=None):
        self.page_calls.append(cursor)
        result = self.pages[cursor]
        if isinstance(result, list):
            result = result.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    async def aclose(self):
        self.closed = True


@pytest.fixture
def pending(source):
    summary = note()
    return source, enroll(source, summary), summary


@pytest.fixture
def provider(pending, monkeypatch):
    client = Provider(pending[2])
    client.configs = []

    def build(config):
        client.configs.append(config)
        return client

    monkeypatch.setattr(digestion, "build_meeting_provider", build)
    return client


@pytest.mark.asyncio
async def test_capture_two_pages_snapshots_same_version_and_replay_makes_no_more_requests(pending, provider):
    config, meeting_id, summary = pending
    provider.pages = {None: transcript_page("First recorded statement", "next"), "next": transcript_page("Second recorded statement")}

    result = await digestion.capture_transcripts(config.name)
    assert result == {"outcome": "ready", "meeting_id": meeting_id, "segments": 2}
    assert provider.page_calls == [None, "next"] and provider.summary_calls == [summary.external_id] * 2
    stored = digestion_db.get_record(meeting_id)
    assert stored["snapshot"]["provider_updated_at"] == summary.provider_updated_at.isoformat()
    assert stored["snapshot"]["revision"] == 1 and stored["transcript_hash"]
    assert [item["id"] for item in stored["transcript"]["segments"]] == ["segment-0", "segment-1"]
    assert [item["text"] for item in digestion_db.get_transcript(meeting_id)["items"]] == ["First recorded statement", "Second recorded statement"]
    assert provider.closed and stored["claim_owner"] is None

    assert await digestion.capture_transcripts(config.name) == {"outcome": "idle"}
    assert provider.page_calls == [None, "next"] and len(provider.configs) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change_after_page", [False, True])
async def test_capture_discards_stale_version_without_publishing_partial_text(pending, provider, monkeypatch, change_after_page):
    config, meeting_id, summary = pending
    changed = replace(summary, provider_updated_at=STAMP + timedelta(hours=1))
    if change_after_page:
        original = provider.get_transcript_page

        async def page_then_change(external_id, cursor=None):
            result = await original(external_id, cursor)
            provider.summary = changed
            return result

        monkeypatch.setattr(provider, "get_transcript_page", page_then_change)
    else:
        provider.summary = changed

    result = await digestion.capture_transcripts(config.name)
    assert result["outcome"] == "continued" and result["error_type"] == "TranscriptChangedError"
    stored = digestion_db.get_record(meeting_id)
    assert stored["transcript"] == {} and stored["transcript_hash"] is None
    assert stored["attempts"] == 0 and stored["claim_owner"] is None
    assert digestion_db.get_transcript(meeting_id)["items"] == []
    assert provider.closed


@pytest.mark.asyncio
async def test_capture_timeout_keeps_committed_cursor_and_resumes_without_attempt_failure(pending, provider, monkeypatch):
    config, meeting_id, _ = pending
    original = provider.get_transcript_page
    provider.pages = {None: transcript_page("Committed first page", "next"), "next": transcript_page("Resumed second page")}

    async def wait_on_second_page(external_id, cursor=None):
        if cursor == "next":
            await asyncio.Event().wait()
        return await original(external_id, cursor)

    monkeypatch.setattr(provider, "get_transcript_page", wait_on_second_page)
    result = await digestion.capture_transcripts(config.name, run_budget_seconds=1)
    assert result["outcome"] == "continued"
    stored = digestion_db.get_record(meeting_id)
    assert stored["transcript"]["cursor"] == "next" and stored["attempts"] == 0
    assert len(stored["transcript"]["segments"]) == 1 and stored["claim_owner"] is None

    provider.page_calls.clear()
    monkeypatch.setattr(provider, "get_transcript_page", original)
    resumed = await digestion.capture_transcripts(config.name)
    assert resumed["outcome"] == "ready" and resumed["segments"] == 2
    assert provider.page_calls == ["next"]


@pytest.mark.asyncio
async def test_expired_cursor_restarts_once_and_drops_the_old_partial_snapshot(pending, provider):
    config, meeting_id, _ = pending
    provider.pages = {
        None: [transcript_page("Stale partial statement", "expired"), transcript_page("Fresh transcript")],
        "expired": InvalidCursorError("Sensitive cursor data must not appear"),
    }

    result = await digestion.capture_transcripts(config.name)
    assert result["outcome"] == "ready" and result["segments"] == 1
    assert provider.page_calls == [None, "expired", None]
    assert [item["text"] for item in digestion_db.get_transcript(meeting_id)["items"]] == ["Fresh transcript"]


@pytest.mark.asyncio
@pytest.mark.parametrize("pages,expected_calls", [
    ({None: [InvalidCursorError("sensitive cursor"), InvalidCursorError("sensitive cursor")]}, [None, None]),
    ({None: transcript_page(next_cursor="first"), "first": transcript_page(next_cursor="second"),
      "second": transcript_page(next_cursor="first")}, [None, "first", "second"]),
])
async def test_invalid_cursors_are_bounded_and_fail_without_publishing_text(pending, provider, pages, expected_calls):
    config, meeting_id, _ = pending
    provider.pages = pages

    result = await digestion.capture_transcripts(config.name)
    assert result["outcome"] == "failed" and result["error_type"] == "MeetingProviderError"
    assert provider.page_calls == expected_calls
    stored = digestion_db.get_record(meeting_id)
    assert stored["attempts"] == 1 and stored["claim_owner"] is None
    assert digestion_db.get_transcript(meeting_id)["items"] == [] and provider.closed
    assert "sensitive" not in json.dumps(result)


@pytest.mark.asyncio
async def test_legacy_provider_without_transcript_capability_is_explicitly_unsupported(pending, monkeypatch):
    config, meeting_id, _ = pending

    class LegacyProvider:
        closed = False

        async def aclose(self):
            self.closed = True

    legacy = LegacyProvider()
    monkeypatch.setattr(digestion, "build_meeting_provider", lambda _: legacy)
    result = await digestion.capture_transcripts(config.name)
    assert result["outcome"] == "unsupported" and legacy.closed
    stored = digestion_db.get_record(meeting_id)
    assert stored["transcript_status"] == "unsupported" and stored["claim_owner"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 404])
async def test_permission_and_missing_transcripts_are_unavailable_without_leaking_responses(pending, provider, status, caplog):
    config, meeting_id, _ = pending
    provider.pages = {None: MeetingProviderError("Private API payload and secret-token", status_code=status)}
    result = await digestion.capture_transcripts(config.name)
    stored = digestion_db.get_record(meeting_id)

    assert result["outcome"] == "failed" and result["error_type"] == "MeetingProviderError"
    assert stored["transcript_status"] == "unavailable" and stored["error_type"] == "MeetingProviderError"
    assert stored["claim_owner"] is None and provider.closed
    assert "Private API" not in json.dumps(result) + json.dumps(stored) + caplog.text
    assert "secret-token" not in json.dumps(result) + json.dumps(stored) + caplog.text


@pytest.mark.asyncio
async def test_unexpected_capture_errors_persist_only_a_safe_category(pending, provider, caplog):
    config, meeting_id, _ = pending
    provider.pages = {None: RuntimeError("Private transcript and secret-token")}
    result = await digestion.capture_transcripts(config.name)
    stored = digestion_db.get_record(meeting_id)

    assert result["error_type"] == stored["error_type"] == "RuntimeError"
    assert stored["attempts"] == 1 and stored["transcript_status"] == "pending"
    assert "Private transcript" not in json.dumps(result) + json.dumps(stored) + caplog.text
    assert "secret-token" not in json.dumps(result) + json.dumps(stored) + caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["claim_transcript", "save_capture"])
async def test_cancelled_claim_or_write_drains_before_releasing_its_lease(pending, provider, monkeypatch, operation):
    config, meeting_id, _ = pending
    entered, unblock = threading.Event(), threading.Event()
    original = getattr(digestion_db, operation)
    original_release = digestion_db.release_owner
    events = []

    def blocked(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        if not unblock.wait(5):
            raise RuntimeError("Test did not release its database operation")
        events.append("operation_finished")
        return result

    def release(owner):
        events.append("claim_released")
        return original_release(owner)

    monkeypatch.setattr(digestion_db, operation, blocked)
    monkeypatch.setattr(digestion_db, "release_owner", release)
    task = asyncio.create_task(digestion.capture_transcripts(config.name))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        assert digestion_db.get_record(meeting_id)["claim_owner"] is not None
        assert "claim_released" not in events
        unblock.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
    finally:
        unblock.set()
        await asyncio.gather(task, return_exceptions=True)
    assert events == ["operation_finished", "claim_released"]
    assert digestion_db.get_record(meeting_id)["claim_owner"] is None
    if operation == "save_capture":
        assert provider.closed
    else:
        assert provider.configs == []


@pytest.mark.asyncio
async def test_removed_source_is_not_captured_and_explicit_source_does_not_claim_another_account(pending, provider, monkeypatch):
    config, meeting_id, summary = pending
    settings = json.loads(os.environ["MEETING_SOURCES_JSON"])
    other_name = config.name + "-other"
    other_account = config.account_key + "-other"
    settings[other_name] = {"provider": config.provider, "account_key": other_account, "api_key_env": "MEETING_SYNC_TEST_KEY"}
    monkeypatch.setenv("MEETING_SOURCES_JSON", json.dumps(settings))
    other = load_source_config(other_name)
    provider.summary = replace(summary, external_id="other-note")
    other_id = enroll(other, provider.summary)
    try:
        result = await digestion.capture_transcripts(other_name)
        assert result["outcome"] == "ready" and result["meeting_id"] == other_id
        assert digestion_db.get_record(meeting_id)["transcript_status"] == "pending"
        assert provider.configs[0].account_key == other_account

        monkeypatch.setenv("MEETING_SOURCES_JSON", "{}")
        assert await digestion.capture_transcripts() == {"outcome": "idle"}
        assert digestion_db.get_record(meeting_id)["claim_owner"] is None
        assert len(provider.configs) == 1
    finally:
        clean_meeting_rows(other_account)


@pytest.mark.asyncio
@pytest.mark.parametrize("budget", [True, False, None, "1", 0, -1, 481, math.inf, -math.inf, math.nan])
async def test_capture_rejects_invalid_budgets_before_acquiring_a_claim(pending, provider, budget):
    config, meeting_id, _ = pending
    with pytest.raises(ValueError, match="finite number"):
        await digestion.capture_transcripts(config.name, run_budget_seconds=budget)
    assert digestion_db.get_record(meeting_id)["claim_owner"] is None
    assert provider.configs == []


@pytest.mark.asyncio
async def test_provider_setup_failure_consumes_an_attempt_without_leaking_private_context(pending, monkeypatch, caplog):
    config, meeting_id, _ = pending

    def setup_failure(_):
        raise RuntimeError("PRIVATE_SETUP_SENTINEL secret-token")

    monkeypatch.setattr(digestion, "build_meeting_provider", setup_failure)
    result = await digestion.capture_transcripts(config.name)
    stored = digestion_db.get_record(meeting_id)

    assert result == {"outcome": "failed", "meeting_id": meeting_id, "error_type": "RuntimeError"}
    assert stored["attempts"] == 1 and stored["error_type"] == "RuntimeError"
    assert stored["claim_owner"] is None
    assert "PRIVATE_SETUP_SENTINEL" not in json.dumps(result) + json.dumps(stored) + caplog.text
    assert "secret-token" not in json.dumps(result) + json.dumps(stored) + caplog.text


@pytest.mark.asyncio
async def test_provider_close_failure_preserves_capture_and_reports_only_a_safe_category(pending, provider, monkeypatch, caplog):
    config, meeting_id, _ = pending

    async def close_failure():
        raise RuntimeError("PRIVATE_CLOSE_SENTINEL secret-token")

    monkeypatch.setattr(provider, "aclose", close_failure)
    result = await digestion.capture_transcripts(config.name)
    stored = digestion_db.get_record(meeting_id)

    assert result["outcome"] == "failed" and result["error_type"] == "RuntimeError"
    assert result["meeting_id"] == meeting_id
    assert stored["transcript_status"] == "ready" and stored["claim_owner"] is None
    assert digestion_db.get_transcript(meeting_id)["items"][0]["text"] == "Recorded decision"
    assert "PRIVATE_CLOSE_SENTINEL" not in json.dumps(result) + json.dumps(stored) + caplog.text
    assert "secret-token" not in json.dumps(result) + json.dumps(stored) + caplog.text


@pytest.mark.asyncio
async def test_overall_deadline_includes_context_loading_and_still_drains_the_database_thread(pending, provider, monkeypatch):
    config, meeting_id, _ = pending
    entered, unblock = threading.Event(), threading.Event()
    original = digestion_db.get_context

    def slow_context(key):
        entered.set()
        if not unblock.wait(5):
            raise RuntimeError("Test did not release context loading")
        return original(key)

    monkeypatch.setattr(digestion_db, "get_context", slow_context)
    task = asyncio.create_task(digestion.capture_transcripts(config.name, run_budget_seconds=0.05))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        await asyncio.sleep(0.08)
        assert not task.done() and digestion_db.get_record(meeting_id)["claim_owner"] is not None
        unblock.set()
        result = await asyncio.wait_for(task, 5)
    finally:
        unblock.set()
        await asyncio.gather(task, return_exceptions=True)
    assert result == {"outcome": "continued", "meeting_id": meeting_id, "error_type": "TimeoutError"}
    assert digestion_db.get_record(meeting_id)["claim_owner"] is None
    assert digestion_db.get_record(meeting_id)["attempts"] == 0 and provider.configs == []


@pytest.mark.asyncio
@pytest.mark.parametrize("close_budget,run_budget,outcome", [(5, 0.25, "continued"), (0.05, 1, "failed")])
async def test_provider_close_obeys_the_overall_and_cleanup_deadlines(pending, provider, monkeypatch, close_budget, run_budget, outcome):
    config, meeting_id, _ = pending
    entered = asyncio.Event()

    async def stalled_close():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            provider.closed = True

    monkeypatch.setattr(provider, "aclose", stalled_close)
    monkeypatch.setattr(digestion, "PROVIDER_CLOSE_SECONDS", close_budget)
    result = await asyncio.wait_for(digestion.capture_transcripts(config.name, run_budget_seconds=run_budget), 2)

    assert entered.is_set() and provider.closed
    assert result["outcome"] == outcome and result["error_type"] == "TimeoutError"
    stored = digestion_db.get_record(meeting_id)
    assert stored["transcript_status"] == "ready" and stored["claim_owner"] is None
