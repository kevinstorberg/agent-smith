import asyncio
from dataclasses import replace

import httpx
import pytest

from services.meetings.providers import granola
from services.meetings.types import MeetingProviderError
from services.observability import current_trigger, trigger_context
from tests.test_meeting_provider import CONFIG, NOTE_ID, Clock, _note


def records(caplog):
    return [
        record.billable_event
        for record in caplog.records
        if hasattr(record, "billable_event")
    ]


def provider_for(handler, *, clock=None):
    clock = clock or Clock()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    config = replace(CONFIG, name="synthetic-source", api_key="PRIVATE_TOKEN")
    return granola.GranolaProvider(
        config, client=client, sleep=clock.sleep, clock=clock
    ), clock


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint,operation",
    [("list", "list_notes"), ("summary", "get_note"), ("transcript", "get_transcript")],
)
async def test_http_attempt_starts_at_sdk_boundary_and_ends_after_body_and_cleanup(
    caplog, endpoint, operation
):
    closed = []

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            assert [record["phase"] for record in records(caplog)] == ["START"]
            yield b'{"PRIVATE_BODY": true}'

        async def aclose(self):
            assert len(records(caplog)) == 1
            closed.append(True)

    def handler(request):
        assert [record["phase"] for record in records(caplog)] == ["START"]
        assert request.headers["Authorization"] == "Bearer PRIVATE_TOKEN"
        return httpx.Response(200, stream=Body())

    provider, _ = provider_for(handler)
    path = (
        "/notes"
        if endpoint == "list"
        else f"/notes/{NOTE_ID}" + ("/transcript" if endpoint == "transcript" else "")
    )
    try:
        with trigger_context(
            trigger="job",
            job_id=12,
            execution_id=34,
            request_id="synthetic",
            reason="scheduled_interval",
        ):
            assert await provider._request(
                path, params={"cursor": "PRIVATE_CURSOR"}
            ) == {"PRIVATE_BODY": True}
    finally:
        await provider.aclose()
    before, after = records(caplog)
    assert before["event_id"] == after["event_id"] and after["outcome"] == "success"
    assert (
        before["provider"],
        before["operation"],
        before["source"],
        before["attempt"],
    ) == ("granola", operation, "synthetic-source", 1)
    assert after["http_status"] == 200 and before["reason"] == "scheduled_interval"
    assert before["request_id"] == "synthetic" and (
        before["job_id"],
        before["execution_id"],
    ) == (12, 34)
    assert closed == [True] and current_trigger() == {}
    assert (
        "PRIVATE_" not in caplog.text
        and NOTE_ID not in caplog.text
        and "granola.ai" not in caplog.text
    )


@pytest.mark.asyncio
async def test_each_retried_http_or_network_attempt_gets_its_own_pair(
    caplog, monkeypatch
):
    calls = []
    monkeypatch.setattr(granola.random, "uniform", lambda *_: 1.0)

    def handler(request):
        calls.append(request)
        assert len(records(caplog)) == len(calls) * 2 - 1
        assert records(caplog)[-1]["phase"] == "START"
        if len(calls) == 1:
            raise httpx.ConnectError("PRIVATE_NETWORK", request=request)
        if len(calls) == 2:
            return httpx.Response(
                429, headers={"Retry-After": "5"}, json={"error": "PRIVATE_BODY"}
            )
        if len(calls) == 3:
            return httpx.Response(503, json={"error": "PRIVATE_BODY"})
        return httpx.Response(
            200, json=_note(title="PRIVATE_TITLE", summary_text="PRIVATE_SUMMARY")
        )

    provider, clock = provider_for(handler)
    try:
        with trigger_context(trigger="mcp", tool="meetings", request_id="synthetic"):
            summary = await provider.get_summary(NOTE_ID)
        assert (
            summary.title == "PRIVATE_TITLE"
            and summary.summary_text == "PRIVATE_SUMMARY"
        )
    finally:
        await provider.aclose()
    result = records(caplog)
    assert len(calls) == 4 and clock.sleeps == [1.0, 5.0, 4.0]
    assert [event["attempt"] for event in result[::2]] == [1, 2, 3, 4]
    assert [event["outcome"] for event in result[1::2]] == [
        "failed",
        "failed",
        "failed",
        "success",
    ]
    assert [event.get("http_status") for event in result[1::2]] == [None, 429, 503, 200]
    assert result[1]["error_type"] == "ConnectError"
    assert len({event["event_id"] for event in result[::2]}) == 4
    assert all(event["request_id"] == "synthetic" for event in result)
    assert "PRIVATE_" not in caplog.text and NOTE_ID not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,attempts", [(401, 1), (302, 1), (408, 4), (429, 4), (503, 4)]
)
async def test_status_failure_logs_per_attempt_without_changing_public_error(
    caplog, status, attempts
):
    provider, _ = provider_for(
        lambda _: httpx.Response(status, json={"error": "PRIVATE_BODY"})
    )
    try:
        with pytest.raises(MeetingProviderError) as raised:
            await provider.list_page()
    finally:
        await provider.aclose()
    assert raised.value.status_code == status
    assert str(raised.value) == f"Granola request failed (HTTP {status})"
    assert len(records(caplog)) == attempts * 2
    assert all(
        event["outcome"] == "failed" and event["http_status"] == status
        for event in records(caplog)[1::2]
    )
    assert "PRIVATE_" not in caplog.text


@pytest.mark.asyncio
async def test_missing_summary_is_an_accepted_response_but_missing_listing_fails(
    caplog,
):
    provider, _ = provider_for(
        lambda _: httpx.Response(404, json={"error": "PRIVATE_BODY"})
    )
    try:
        assert await provider.get_summary(NOTE_ID) is None
        with pytest.raises(MeetingProviderError):
            await provider.list_page()
    finally:
        await provider.aclose()
    result = records(caplog)
    assert [event["outcome"] for event in result[1::2]] == ["success", "failed"]
    assert [event["http_status"] for event in result[1::2]] == [404, 404]


@pytest.mark.asyncio
async def test_invalid_json_keeps_completed_http_success_and_application_failure(
    caplog,
):
    provider, _ = provider_for(
        lambda _: httpx.Response(200, content="PRIVATE_INVALID_JSON")
    )
    try:
        with pytest.raises(MeetingProviderError, match="invalid JSON"):
            await provider.list_page()
    finally:
        await provider.aclose()
    assert len(records(caplog)) == 2 and records(caplog)[-1]["outcome"] == "success"
    assert records(caplog)[-1]["http_status"] == 200 and "PRIVATE_" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,outcome",
    [(asyncio.CancelledError, "cancelled"), (KeyboardInterrupt, "cancelled")],
)
async def test_interrupted_transport_preserves_exception_identity_and_context(
    caplog, kind, outcome
):
    failure = kind("PRIVATE_ERROR")

    def handler(_):
        raise failure

    provider, _ = provider_for(handler)
    try:
        with trigger_context(trigger="mcp", request_id="synthetic"):
            with pytest.raises(kind) as raised:
                await provider.get_summary(NOTE_ID)
        assert raised.value is failure
    finally:
        await provider.aclose()
    before, after = records(caplog)
    assert before["event_id"] == after["event_id"] and after["outcome"] == outcome
    assert after["error_type"] == kind.__name__ and current_trigger() == {}
    assert "PRIVATE_" not in caplog.text


@pytest.mark.asyncio
async def test_task_cancellation_at_actual_transport_closes_one_attempt(caplog):
    entered = asyncio.Event()

    async def handler(_):
        entered.set()
        await asyncio.Event().wait()

    provider, _ = provider_for(handler)

    async def call():
        with trigger_context(request_id="cancelled"):
            return await provider.list_page()

    task = asyncio.create_task(call())
    try:
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await provider.aclose()
    assert len(records(caplog)) == 2
    assert (
        records(caplog)[-1]["outcome"] == "cancelled"
        and records(caplog)[-1]["request_id"] == "cancelled"
    )
    assert current_trigger() == {}


@pytest.mark.asyncio
async def test_request_budget_timeout_logs_original_timeout_before_public_translation(
    monkeypatch, caplog
):
    monkeypatch.setattr(granola, "_REQUEST_BUDGET_SECONDS", 0.001)

    async def handler(_):
        await asyncio.Event().wait()

    provider, _ = provider_for(handler)
    try:
        with pytest.raises(MeetingProviderError, match="retry budget"):
            await provider.list_page()
    finally:
        await provider.aclose()
    assert len(records(caplog)) == 2
    assert (
        records(caplog)[-1]["outcome"] == "timeout"
        and records(caplog)[-1]["error_type"] == "TimeoutError"
    )


@pytest.mark.asyncio
async def test_retry_budget_wait_does_not_fabricate_another_http_attempt(caplog):
    provider, clock = provider_for(
        lambda _: httpx.Response(429, headers={"Retry-After": "120"})
    )
    try:
        with pytest.raises(MeetingProviderError, match="retry budget"):
            await provider.list_page()
    finally:
        await provider.aclose()
    assert clock.sleeps == [] and len(records(caplog)) == 2
    assert (
        records(caplog)[-1]["http_status"] == 429
        and records(caplog)[-1]["outcome"] == "failed"
    )
