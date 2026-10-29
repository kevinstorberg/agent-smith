from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from services.meetings.config import SourceConfig
from services.meetings.providers.granola import GranolaProvider
from services.meetings.types import InvalidCursorError, MeetingProviderError

NOTE_ID = "not_1d3tmYTlCICgjy"
OTHER_NOTE_ID = "not_2d3tmYTlCICgjy"
STAMP = "2026-01-27T15:30:00Z"
CONFIG = SourceConfig(name="test", provider="granola", account_key="test-account", api_key="test-credential")


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def _provider(handler, config=CONFIG):
    clock = Clock()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GranolaProvider(config, client=client, sleep=clock.sleep, clock=clock), clock


def _note(**overrides):
    return {
        "id": NOTE_ID,
        "title": "Product discussion",
        "created_at": STAMP,
        "updated_at": STAMP,
        "deleted_at": None,
        "web_url": "https://notes.granola.ai/d/test",
        "summary_text": "We agreed to write the ticket.",
        "summary_markdown": "We agreed to **write the ticket**.",
        "owner": {"name": "Test Person", "email": "owner@example.test", "private": "exclude"},
        "attendees": [{"email": "attendee@example.test", "transcript": "exclude"}],
        "calendar_event": {
            "event_title": "Discussion", "organiser": "owner@example.test",
            "calendar_event_id": "event-1", "invitees": [{"email": "invitee@example.test", "private": "exclude"}],
            "scheduled_start_time": STAMP, "scheduled_end_time": None, "private": "exclude",
        },
        "folder_membership": [{"id": "fol_4y6LduVdwSKC27", "name": "Team", "private": "exclude"}],
        "space_membership": [{"id": "spa_8kTq2mWxLp4Rz7", "name": "Work", "private": "exclude"}],
        "private_notes_text": "exclude secret text",
        "private_notes_markdown": "exclude secret markdown",
        "transcript": [{"text": "exclude recorded speech"}],
        "attachments": [{"url": "https://example.test/private-image"}],
        **overrides,
    }


@pytest.mark.asyncio
async def test_meeting_provider_lists_scoped_pages_and_paces_requests():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={
            "notes": [{"id": NOTE_ID, "updated_at": STAMP, "deleted_at": None}],
            "hasMore": len(requests) == 1, "cursor": "next" if len(requests) == 1 else None,
        })

    provider, clock = _provider(handler, replace(CONFIG, provider_options={"folder_id": "fol_4y6LduVdwSKC27"}))
    try:
        first = await provider.list_page()
        second = await provider.list_page(first.next_cursor)
        assert first.next_cursor == "next"
        assert second.next_cursor is None
        assert first.notes[0].external_id == NOTE_ID
        assert first.notes[0].updated_at == datetime(2026, 1, 27, 15, 30, tzinfo=timezone.utc)
        assert requests[0].headers["Authorization"] == "Bearer test-credential"
        assert dict(requests[0].url.params) == {"page_size": "30", "folder_id": "fol_4y6LduVdwSKC27"}
        assert requests[1].url.params["cursor"] == "next"
        assert clock.sleeps == [0.25]
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_meeting_provider_sends_frozen_utc_timestamp_filter_with_every_cursor():
    requests = []

    def handler(request):
        requests.append(dict(request.url.params))
        return httpx.Response(200, json={"notes": [], "hasMore": len(requests) == 1, "cursor": "next"})

    provider, _ = _provider(handler, replace(CONFIG, provider_options={"space_id": "spa_8kTq2mWxLp4Rz7"}))
    cutoff = datetime(2026, 1, 27, 17, 30, 12, 345000, tzinfo=timezone(timedelta(hours=2)))
    try:
        first = await provider.list_page(updated_after=cutoff)
        await provider.list_page(first.next_cursor, updated_after=cutoff)
        assert [params["updated_after"] for params in requests] == ["2026-01-27T15:30:12.345000Z"] * 2
        assert all(params["space_id"] == "spa_8kTq2mWxLp4Rz7" for params in requests)
        assert requests[1]["cursor"] == "next"
    finally:
        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("cutoff", [datetime(2026, 1, 1), "2026-01-01", True, 123])
async def test_meeting_provider_rejects_unsafe_cutoff_before_requesting(cutoff):
    requests = []
    provider, _ = _provider(lambda request: requests.append(request))
    try:
        with pytest.raises(ValueError, match="timezone-aware datetime"):
            await provider.list_page(updated_after=cutoff)
        assert requests == []
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_meeting_provider_projects_summary_and_metadata_only():
    provider, _ = _provider(lambda request: httpx.Response(200, json=_note()))
    try:
        summary = await provider.get_summary(NOTE_ID)
        assert summary.summary_text == "We agreed to write the ticket."
        assert summary.metadata["owner"] == {"name": "Test Person", "email": "owner@example.test"}
        assert summary.metadata["calendar_event"]["scheduled_start_time"] == "2026-01-27T15:30:00+00:00"
        serialized = json.dumps(summary.metadata)
        assert "exclude" not in serialized
        assert "private" not in serialized
        assert "transcript" not in serialized
        assert "attachments" not in serialized
        assert not hasattr(summary, "private_notes_text")
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_meeting_provider_accepts_nullable_fields():
    provider, _ = _provider(lambda request: httpx.Response(200, json=_note(title=None, summary_markdown=None, calendar_event=None)))
    try:
        summary = await provider.get_summary(NOTE_ID)
        assert summary.title is None
        assert summary.summary_markdown is None
        assert "calendar_event" not in summary.metadata
    finally:
        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("summary_text", [None, "", "  "])
async def test_meeting_provider_keeps_notes_without_summaries_pending(summary_text):
    provider, _ = _provider(lambda request: httpx.Response(200, json=_note(summary_text=summary_text)))
    try:
        assert await provider.get_summary(NOTE_ID) is None
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_meeting_provider_missing_details_are_pending():
    provider, _ = _provider(lambda request: httpx.Response(404, json={"message": "private text"}))
    try:
        assert await provider.get_summary(NOTE_ID) is None
        with pytest.raises(MeetingProviderError) as caught:
            await provider.list_page()
        assert caught.value.status_code == 404
    finally:
        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["list", "detail"])
@pytest.mark.parametrize("payload", [None, [], "unexpected"])
async def test_meeting_provider_rejects_non_object_success_responses(endpoint, payload):
    provider, _ = _provider(lambda request: httpx.Response(200, content=json.dumps(payload), headers={"Content-Type": "application/json"}))
    try:
        with pytest.raises(MeetingProviderError, match="response: must be an object"):
            if endpoint == "list":
                await provider.list_page()
            else:
                await provider.get_summary(NOTE_ID)
    finally:
        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("changes,field", [
    ({"id": OTHER_NOTE_ID}, "id"),
    ({"updated_at": "invalid sensitive value"}, "updated_at"),
    ({"created_at": "2026-01-27T15:30:00"}, "created_at"),
    ({"summary_text": []}, "summary_text"),
    ({"attendees": ["invalid sensitive value"]}, "attendees"),
    ({"calendar_event": {"scheduled_start_time": "invalid sensitive value"}}, "scheduled_start_time"),
    ({"web_url": "https://user:password@example.test"}, "web_url"),
])
async def test_meeting_provider_rejects_invalid_details_without_leaking_values(changes, field):
    provider, _ = _provider(lambda request: httpx.Response(200, json=_note(**changes)))
    try:
        with pytest.raises(MeetingProviderError, match=field) as caught:
            await provider.get_summary(NOTE_ID)
        assert "invalid sensitive value" not in str(caught.value)
        assert "password" not in str(caught.value)
    finally:
        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"notes": {}, "hasMore": False, "cursor": None},
    {"notes": [], "hasMore": "true", "cursor": "next"},
    {"notes": [], "hasMore": True, "cursor": None},
    {"notes": [], "hasMore": True, "cursor": "previous"},
    {"notes": [{"id": "invalid", "updated_at": STAMP}], "hasMore": False},
])
async def test_meeting_provider_rejects_malformed_or_stuck_pagination(payload):
    provider, _ = _provider(lambda request: httpx.Response(200, json=payload))
    try:
        with pytest.raises(MeetingProviderError):
            await provider.list_page("previous")
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_meeting_provider_allows_empty_continuation_pages():
    provider, _ = _provider(lambda request: httpx.Response(200, json={"notes": [], "hasMore": True, "cursor": "next"}))
    try:
        page = await provider.list_page()
        assert page.notes == ()
        assert page.next_cursor == "next"
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_meeting_provider_retries_transient_failures_and_honors_retry_after():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("sensitive provider message", request=request)
        if calls == 2:
            return httpx.Response(429, headers={"Retry-After": "5"})
        return httpx.Response(200, json=_note())

    provider, clock = _provider(handler)
    try:
        assert await provider.get_summary(NOTE_ID) is not None
        assert calls == 3
        assert 0.8 <= clock.sleeps[0] <= 1.2
        assert clock.sleeps[1] == 5
    finally:
        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,attempts", [(401, 1), (403, 1), (302, 1), (408, 4), (429, 4), (503, 4)])
async def test_meeting_provider_bounds_retries_and_redacts_failures(status, attempts):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={"error": "private body test-credential"})

    provider, _ = _provider(handler)
    try:
        with pytest.raises(MeetingProviderError) as caught:
            await provider.list_page()
        assert caught.value.status_code == status
        assert calls == attempts
        assert "private body" not in str(caught.value)
        assert "test-credential" not in str(caught.value)
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_meeting_provider_does_not_wait_beyond_retry_budget():
    provider, clock = _provider(lambda request: httpx.Response(429, headers={"Retry-After": "120"}))
    try:
        with pytest.raises(MeetingProviderError, match="retry budget"):
            await provider.list_page()
        assert clock.sleeps == []
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_meeting_provider_exposes_cursor_rejection_for_bounded_scan_restart():
    provider, _ = _provider(lambda request: httpx.Response(400, json={"error": "private body"}))
    try:
        with pytest.raises(InvalidCursorError) as caught:
            await provider.list_page("expired")
        assert caught.value.status_code == 400
        with pytest.raises(MeetingProviderError) as caught:
            await provider.list_page()
        assert not isinstance(caught.value, InvalidCursorError)
    finally:
        await provider.aclose()


@pytest.mark.parametrize("options", [
    {"page_size": 31}, {"page_size": True}, {"page_size": 0},
    {"folder_id": "bad"}, {"space_id": "bad"}, {"base_url": "https://unsafe.test"},
])
def test_meeting_provider_validates_provider_options_before_connecting(options):
    with pytest.raises(ValueError, match="Granola"):
        GranolaProvider(replace(CONFIG, provider_options=options))
