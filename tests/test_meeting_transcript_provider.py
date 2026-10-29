import asyncio
import json
import traceback
from datetime import datetime, timezone

import httpx
import pytest

from services.meetings.types import InvalidCursorError, MeetingProviderError
from tests.test_meeting_provider import NOTE_ID, STAMP, _provider


def segment(**changes):
    return {
        "text": "Décision: 次のステップを確認します。",
        "speaker": {"source": "microphone", "attribution": "me", "diarization_label": "Speaker A"},
        "start_time": STAMP, "end_time": "2026-01-27T15:30:10Z", **changes,
    }


def page(segments=None, **changes):
    return {"transcript": [segment()] if segments is None else segments, "hasMore": False, "cursor": None, **changes}


@pytest.mark.asyncio
async def test_transcript_pages_preserve_order_unicode_and_unknown_speakers_and_reuse_pacing():
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, json=page([
                segment(speaker={"source": "microphone", "diarization_label": "Speaker A", "private": "exclude"}, private_notes="exclude"),
                segment(text="Second simultaneous speaker", speaker={"source": "microphone", "name": "Explicit name"}),
            ], hasMore=True, cursor="next"))
        return httpx.Response(200, json=page([segment(text="Final segment", speaker=None, start_time=None, end_time=None)]))

    provider, clock = _provider(handler)
    try:
        first = await provider.get_transcript_page(NOTE_ID)
        second = await provider.get_transcript_page(NOTE_ID, first.next_cursor)
        assert first.next_cursor == "next" and second.next_cursor is None
        assert [item.text for item in first.segments] == [segment()["text"], "Second simultaneous speaker"]
        assert first.segments[0].speaker == {"source": "microphone", "diarization_label": "Speaker A"}
        assert "name" not in first.segments[0].speaker
        assert first.segments[1].speaker["name"] == "Explicit name"
        assert second.segments[0].speaker == {} and second.segments[0].start_time is None
        assert first.segments[0].start_time == datetime(2026, 1, 27, 15, 30, tzinfo=timezone.utc)
        assert "exclude" not in json.dumps(first.segments[0].to_dict(1))
        assert requests[0].url.path == f"/v1/notes/{NOTE_ID}/transcript"
        assert dict(requests[0].url.params) == {"page_size": "100"}
        assert dict(requests[1].url.params) == {"page_size": "100", "cursor": "next"}
        assert requests[0].headers["Authorization"] == "Bearer test-credential"
        assert clock.sleeps == [0.25]
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_transcript_empty_continuation_page_is_not_end_of_transcript():
    provider, _ = _provider(lambda request: httpx.Response(200, json=page([], hasMore=True, cursor="next")))
    try:
        result = await provider.get_transcript_page(NOTE_ID)
        assert result.segments == () and result.next_cursor == "next"
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_transcript_dates_normalize_timezone_and_accept_missing_times():
    provider, _ = _provider(lambda request: httpx.Response(200, json=page([
        segment(start_time="2026-01-27T17:30:00+02:00", end_time="2026-01-27T17:30:10+02:00"),
        {"text": "No timestamps or identified speaker"},
    ])))
    try:
        result = await provider.get_transcript_page(NOTE_ID)
        assert result.segments[0].to_dict(1)["start_time"] == "2026-01-27T15:30:00+00:00"
        assert result.segments[1].to_dict(2) == {
            "id": "segment-2", "text": "No timestamps or identified speaker", "speaker": {}, "start_time": None, "end_time": None,
        }
    finally:
        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [None, [], "private response", {"transcript": None, "hasMore": False}])
async def test_transcript_rejects_invalid_success_payload_without_private_values(payload):
    provider, _ = _provider(lambda request: httpx.Response(200, content=json.dumps(payload), headers={"Content-Type": "application/json"}))
    try:
        with pytest.raises(MeetingProviderError) as caught:
            await provider.get_transcript_page(NOTE_ID)
        assert "private response" not in str(caught.value)
    finally:
        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"text": None}, {"text": ["private value"]}, {"speaker": "private value"}, {"speaker": {"name": ["private value"]}},
    {"start_time": "private value"}, {"start_time": "2026-01-27T15:30:00"},
    {"end_time": "2026-01-27T15:29:00Z"}, {"text": "\ud800"},
])
async def test_transcript_rejects_invalid_segments_without_echoing_remote_values(changes):
    provider, _ = _provider(lambda request: httpx.Response(200, content=json.dumps(page([segment(**changes)])), headers={"Content-Type": "application/json"}))
    try:
        with pytest.raises(MeetingProviderError) as caught:
            await provider.get_transcript_page(NOTE_ID)
        assert "private value" not in str(caught.value)
        assert "private value" not in "".join(traceback.format_exception(caught.value))
    finally:
        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    page([], hasMore="true"), page([], hasMore=True), page([], hasMore=True, cursor="previous"),
    page([], hasMore=True, cursor=123), page([segment()] * 101),
])
async def test_transcript_rejects_invalid_pagination_or_oversized_pages(payload):
    provider, _ = _provider(lambda request: httpx.Response(200, json=payload))
    try:
        with pytest.raises(MeetingProviderError):
            await provider.get_transcript_page(NOTE_ID, "previous")
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_transcript_segment_limit_uses_utf8_bytes_instead_of_character_count():
    provider, _ = _provider(lambda request: httpx.Response(200, json=page([segment(text="界" * 700_000)])))
    try:
        with pytest.raises(MeetingProviderError, match="exceeds 2000000 bytes"):
            await provider.get_transcript_page(NOTE_ID)
    finally:
        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 404])
async def test_transcript_unavailable_is_a_safe_error_not_an_empty_success(status):
    provider, _ = _provider(lambda request: httpx.Response(status, json={"error": "private response test-credential"}))
    try:
        with pytest.raises(MeetingProviderError) as caught:
            await provider.get_transcript_page(NOTE_ID)
        assert caught.value.status_code == status
        assert "private response" not in str(caught.value) and "test-credential" not in str(caught.value)
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_transcript_cursor_rejection_is_distinguished_for_bounded_restart():
    provider, _ = _provider(lambda request: httpx.Response(400, json={"error": "private response"}))
    try:
        with pytest.raises(InvalidCursorError) as caught:
            await provider.get_transcript_page(NOTE_ID, "expired")
        assert caught.value.status_code == 400
        with pytest.raises(MeetingProviderError) as caught:
            await provider.get_transcript_page(NOTE_ID)
        assert not isinstance(caught.value, InvalidCursorError)
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_transcript_retries_transient_failures_using_existing_request_policy():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "5"})
        if calls == 2:
            return httpx.Response(503)
        return httpx.Response(200, json=page())

    provider, clock = _provider(handler)
    try:
        result = await provider.get_transcript_page(NOTE_ID)
        assert len(result.segments) == 1 and calls == 3
        assert clock.sleeps[0] == 5
        assert 1.6 <= clock.sleeps[1] <= 2.4
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_transcript_request_cancellation_propagates():
    entered = asyncio.Event()

    async def handler(request):
        entered.set()
        await asyncio.Event().wait()

    provider, _ = _provider(handler)
    task = asyncio.create_task(provider.get_transcript_page(NOTE_ID))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
    finally:
        task.cancel()
        await provider.aclose()
