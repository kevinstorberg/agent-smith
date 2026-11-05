import asyncio
from concurrent.futures import (
    CancelledError as FutureCancelledError,
    ThreadPoolExecutor,
)
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import subprocess
import sys
from threading import Barrier, Event
from uuid import UUID, uuid4

import pytest

from services.observability import (
    BillableEvent,
    billable_operation,
    current_trigger,
    submit_with_context,
    trigger_context,
)


LOGGER = "agent_smith.billable"
SECRET = "PRIVATE_PROMPT_PROPOSAL_RULE_CRITERIA_KEY_CANARY"


@pytest.fixture(autouse=True)
def capture_billable_logs(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)


def records(caplog):
    return [record for record in caplog.records if record.name == LOGGER]


def events(caplog):
    return [record.billable_event for record in records(caplog)]


def assert_utc(value):
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)


def test_before_is_visible_inside_provider_and_end_follows_completion(caplog):
    def provider():
        assert [event["phase"] for event in events(caplog)] == ["START"]
        return "provider-result"

    with billable_operation(
        "openai", "completion", model="test-model", sdk_retries=2
    ) as event:
        assert provider() == "provider-result"
        assert events(caplog)[0]["event_id"] == event.event_id
        assert [item["phase"] for item in events(caplog)] == ["START"]

    start, end = events(caplog)
    assert start["phase"] == "START" and end["phase"] == "END"
    assert start["event_id"] == end["event_id"]
    UUID(start["event_id"])
    assert start["provider"] == end["provider"] == "openai"
    assert start["operation"] == end["operation"] == "completion"
    assert start["trigger"] == end["trigger"] == "unknown"
    assert start["model"] == end["model"] == "test-model"
    assert start["sdk_retries"] == end["sdk_retries"] == 2
    assert end["outcome"] == "success" and end["duration_ms"] >= 0
    for record in records(caplog):
        payload = record.billable_event
        assert_utc(payload["utc_timestamp"])
        assert json.loads(record.getMessage().split(" ", 2)[2]) == payload
        assert record.getMessage().startswith(f"BILLABLE {payload['phase']} ")


@pytest.mark.parametrize(
    "error,outcome",
    [
        (RuntimeError(SECRET), "failed"),
        (TimeoutError(SECRET), "timeout"),
        (asyncio.CancelledError(SECRET), "cancelled"),
        (FutureCancelledError(SECRET), "cancelled"),
        (GeneratorExit(SECRET), "cancelled"),
        (KeyboardInterrupt(SECRET), "cancelled"),
        (SystemExit(SECRET), "failed"),
    ],
)
def test_failed_provider_has_one_terminal_event_and_preserves_exception(
    caplog, error, outcome
):
    with pytest.raises(type(error)) as caught:
        with billable_operation("anthropic", "messages.stream", streaming=True):
            assert [event["phase"] for event in events(caplog)] == ["START"]
            raise error

    assert caught.value is error
    start, end = events(caplog)
    assert end["event_id"] == start["event_id"]
    assert end["outcome"] == outcome
    assert end["error_type"] == type(error).__name__
    assert SECRET not in caplog.text
    assert all(record.exc_info is None for record in records(caplog))


def test_async_cancellation_logs_end_before_propagating_and_restores_context(caplog):
    async def run():
        baseline = current_trigger()
        entered = asyncio.Event()
        interrupted = asyncio.CancelledError(SECRET)

        async def work():
            with trigger_context(trigger="manual", request_id="cancelled-request"):
                with billable_operation("openai", "judge.a_generate"):
                    entered.set()
                    await asyncio.Future()

        task = asyncio.create_task(work())
        await entered.wait()
        task.cancel(interrupted)
        with pytest.raises(asyncio.CancelledError):
            await task
        assert current_trigger() == baseline
        assert events(caplog)[-1]["outcome"] == "cancelled"

    asyncio.run(run())
    assert [event["phase"] for event in events(caplog)] == ["START", "END"]
    assert SECRET not in caplog.text


def test_finish_records_only_safe_details_and_is_idempotent(caplog):
    class ProviderFailure(RuntimeError):
        status_code = 503

    error = ProviderFailure(SECRET)
    event = BillableEvent.start("openai", "completion")
    assert event.finish(
        "failed", error=error, tokens_input=12, tokens_output=4, total_tokens=16
    )
    assert not event.finish("success", http_status=200)

    start, end = events(caplog)
    assert end["event_id"] == start["event_id"]
    assert end["outcome"] == "failed" and end["http_status"] == 503
    assert end["error_type"] == "ProviderFailure"
    assert (end["tokens_input"], end["tokens_output"], end["total_tokens"]) == (
        12,
        4,
        16,
    )
    assert SECRET not in caplog.text
    assert all(record.exc_info is None for record in records(caplog))


def test_concurrent_finish_emits_exactly_one_end(caplog):
    event = BillableEvent.start("pinecone", "query", index="unit-index")
    ready = Barrier(4)

    def finish():
        ready.wait(timeout=5)
        return event.finish(read_units=1)

    with ThreadPoolExecutor(max_workers=4) as executor:
        completions = [executor.submit(finish) for _ in range(4)]
        assert sum(future.result(timeout=5) for future in completions) == 1
    assert [item["phase"] for item in events(caplog)] == ["START", "END"]


def test_trigger_is_a_snapshot_and_current_trigger_returns_an_independent_copy(caplog):
    baseline = current_trigger()
    meeting_id = uuid4()
    source_time = datetime(2026, 11, 4, 9, 30, tzinfo=timezone(timedelta(hours=-5)))
    with trigger_context(
        trigger="manual",
        meeting_id=meeting_id,
        requested_at=source_time,
        source_revision=3,
    ):
        snapshot = current_trigger()
        snapshot["trigger"] = "tampered-copy"
        assert current_trigger()["trigger"] == "manual"
        with trigger_context(source_revision=None):
            assert current_trigger()["source_revision"] == 3
        event = BillableEvent.start("openai", "completion")
        with trigger_context(trigger="scheduler", source_revision=4):
            event.finish()
        assert current_trigger()["trigger"] == "manual"
    assert current_trigger() == baseline

    start, end = events(caplog)
    for item in (start, end):
        assert item["trigger"] == "manual"
        assert item["meeting_id"] == str(meeting_id)
        assert item["requested_at"] == "2026-11-04T14:30:00+00:00"
        assert item["source_revision"] == 3


def test_nested_operations_preserve_cause_and_record_parent_identity(caplog):
    baseline = current_trigger()
    with trigger_context(trigger="mcp", request_id="request-1", tool="run_graph"):
        with billable_operation("openai", "outer") as outer:
            assert current_trigger()["parent_event_id"] == outer.event_id
            with billable_operation("openai", "inner") as inner:
                assert current_trigger()["parent_event_id"] == inner.event_id
            assert current_trigger()["parent_event_id"] == outer.event_id
        assert "parent_event_id" not in current_trigger()
    assert current_trigger() == baseline

    start_outer, start_inner, end_inner, end_outer = events(caplog)
    assert (
        start_inner["parent_event_id"]
        == end_inner["parent_event_id"]
        == start_outer["event_id"]
    )
    assert end_outer["event_id"] == start_outer["event_id"]
    assert all(
        item["request_id"] == "request-1" and item["trigger"] == "mcp"
        for item in events(caplog)
    )


def test_concurrent_async_operations_do_not_share_trigger_fields(caplog):
    async def run():
        barrier = asyncio.Barrier(2)
        baseline = current_trigger()

        async def work(request_id):
            with trigger_context(trigger="manual", request_id=request_id):
                with billable_operation("openai", "judge.a_generate"):
                    await barrier.wait()
                    await asyncio.sleep(0)
                    assert current_trigger()["request_id"] == request_id

        await asyncio.gather(work("request-a"), work("request-b"))
        assert current_trigger() == baseline

    asyncio.run(run())
    assert len(events(caplog)) == 4
    for request_id in ("request-a", "request-b"):
        pair = [item for item in events(caplog) if item["request_id"] == request_id]
        assert [item["phase"] for item in pair] == ["START", "END"]
        assert pair[0]["event_id"] == pair[1]["event_id"]


def test_executor_submission_captures_trigger_before_later_context_changes(caplog):
    release = Event()

    def work(prefix, *, suffix):
        assert release.wait(timeout=5)
        with billable_operation("pinecone", "query"):
            return prefix + suffix, current_trigger()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with trigger_context(
            trigger="mcp", request_id="captured-request", attempt=0, streaming=False
        ):
            future = submit_with_context(executor, work, "context-", suffix="copied")
        with trigger_context(trigger="scheduler", request_id="later-request"):
            release.set()
            result, snapshot = future.result(timeout=5)
        assert executor.submit(current_trigger).result(timeout=5) == {}

    assert result == "context-copied"
    assert snapshot["request_id"] == "captured-request"
    assert snapshot["attempt"] == 0 and snapshot["streaming"] is False
    assert all(
        item["trigger"] == "mcp" and item["request_id"] == "captured-request"
        for item in events(caplog)
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("prompt", SECRET),
        ("proposal", SECRET),
        ("content", SECRET),
        ("url", SECRET),
        ("command", SECRET),
        ("criteria", SECRET),
        ("error", SECRET),
        ("stage", {"payload": SECRET}),
        ("stage", [SECRET]),
        ("stage", RuntimeError(SECRET)),
        ("requested_at", datetime(2026, 11, 4, 9, 30)),
        ("count", float("nan")),
        ("count", float("inf")),
    ],
)
def test_unsafe_start_fields_are_rejected_before_any_billable_event(
    caplog, field, value
):
    with pytest.raises(ValueError):
        BillableEvent.start("openai", "completion", **{field: value})
    assert records(caplog) == []
    assert SECRET not in caplog.text


@pytest.mark.parametrize(
    "field", ["trigger", "provider", "operation", "event_id", "request_id", "model"]
)
def test_end_metadata_cannot_rewrite_original_cause(caplog, field):
    with trigger_context(trigger="manual", request_id="original-request"):
        event = BillableEvent.start("openai", "completion", model="original-model")
    with pytest.raises(ValueError):
        event.finish(**{field: "rewritten"})
    assert [item["phase"] for item in events(caplog)] == ["START"]
    event.finish()
    assert events(caplog)[-1]["trigger"] == "manual"
    assert events(caplog)[-1]["request_id"] == "original-request"
    assert events(caplog)[-1]["model"] == "original-model"


def test_invalid_trigger_scope_does_not_change_current_context(caplog):
    baseline = current_trigger()
    with pytest.raises(ValueError):
        with trigger_context(prompt=SECRET):
            pytest.fail("Unsafe trigger metadata entered a scope")
    assert current_trigger() == baseline
    assert records(caplog) == []


def test_cli_without_logging_setup_still_emits_paired_structured_records():
    program = """
from services.observability import billable_operation
with billable_operation('openai', 'unit-test'):
    pass
"""
    completed = subprocess.run(
        [sys.executable, "-c", program],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    payloads = [
        json.loads(line.split(" ", 2)[2]) for line in completed.stderr.splitlines()
    ]
    assert [item["phase"] for item in payloads] == ["START", "END"]
    assert payloads[0]["event_id"] == payloads[1]["event_id"]
    assert payloads[1]["outcome"] == "success"
