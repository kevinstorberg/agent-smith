import asyncio
from collections.abc import Callable
import logging
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from scripts.shared.automated_tests import PaidModelCallBlocked
from services.graphs import model_factory
from services.graphs.model_config import load_model_config
from services.observability import trigger_context
from tests.test_graph_model_factory import (
    _FixedReplyModel,
    captured_adapter_kwargs as captured_adapter_kwargs,
    model_env as model_env,
)


def records(caplog):
    return [record.billable_event for record in caplog.records if hasattr(record, "billable_event")]


class LoggedReply(_FixedReplyModel):
    reported_usage: dict[str, Any] | None = None
    observer: Callable[[], None] | None = None

    def _generate(self, *args, **kwargs):
        if self.observer is not None:
            self.observer()
        result = super()._generate(*args, **kwargs)
        result.llm_output = {"token_usage": self.reported_usage, "private": "PRIVATE_PROVIDER_METADATA"}
        return result

    def _stream(self, *args, **kwargs):
        if self.observer is not None:
            self.observer()
        for chunk in super()._stream(*args, **kwargs):
            if chunk.generation_info:
                chunk.message.usage_metadata = self.reported_usage
            yield chunk


@pytest.fixture
def observed_guard(model_env, monkeypatch):
    # Only scripted models or MockTransport clients run in these tests.
    monkeypatch.setattr(model_factory, "require_model_calls_allowed", lambda: None)

    def create(streaming=False):
        model_env.setenv("OPINION_MODEL_STREAMING", str(streaming).lower())
        return model_factory._ModelGuard(load_model_config("opinion"))

    return create


async def invoke(model, mode):
    if mode == "sync":
        return model.invoke("PRIVATE_INPUT").content
    if mode == "async":
        return (await model.ainvoke("PRIVATE_INPUT")).content
    if mode == "stream":
        return "".join(chunk.content for chunk in model.stream("PRIVATE_INPUT"))
    return "".join([chunk.content async for chunk in model.astream("PRIVATE_INPUT")])


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async", "stream", "async_stream"])
async def test_native_model_dispatch_pairs_before_after_and_reports_actual_usage(observed_guard, caplog, mode):
    streaming = "stream" in mode
    guard = observed_guard(streaming)
    usage = {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7} if streaming else {
        "prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7,
    }

    def provider_started():
        assert [record["phase"] for record in records(caplog)] == ["START"]

    model = LoggedReply(finish_reason="stop", streaming=streaming, callbacks=[guard],
                        reported_usage=usage, observer=provider_started)
    with trigger_context(trigger="job", job_id=12, execution_id=34, graph="opinion", reason="scheduled_interval"):
        assert await invoke(model, mode) == "partial"

    before, after = records(caplog)
    assert before["phase"] == "START" and after["phase"] == "END"
    assert before["event_id"] == after["event_id"]
    assert before["provider"] == "bedrock" and before["operation"] == "chat_completion"
    assert before["model_role"] == "opinion" and before["model"] == "us.moonshotai.kimi-k3"
    assert before["streaming"] is streaming and before["sdk_retries"] == 6
    assert (before["job_id"], before["execution_id"], before["reason"]) == (12, 34, "scheduled_interval")
    assert before["input_messages"] == 1 and before["input_characters"] == len("PRIVATE_INPUT")
    UUID(before["model_run_id"])
    assert after["outcome"] == "success" and after["finish_reason"] == "stop"
    assert {key: after[key] for key in ("tokens_input", "tokens_output", "total_tokens")} == {
        "tokens_input": 3, "tokens_output": 4, "total_tokens": 7,
    }
    assert after["duration_ms"] >= 0 and after["completion"] == "sdk_call"
    assert "PRIVATE_INPUT" not in caplog.text and "PRIVATE_PROVIDER_METADATA" not in caplog.text
    assert guard._events == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async", "stream", "async_stream"])
async def test_completed_but_truncated_provider_response_has_one_successful_end(observed_guard, caplog, mode):
    guard = observed_guard("stream" in mode)
    model = LoggedReply(finish_reason="length", streaming="stream" in mode, callbacks=[guard])

    with pytest.raises(model_factory.ModelOutputTruncatedError):
        await invoke(model, mode)

    before, after = records(caplog)
    assert after["outcome"] == "success" and after["finish_reason"] == "length"
    guard.on_llm_error(RuntimeError("PRIVATE_LATE_ERROR"), run_id=UUID(before["model_run_id"]))
    assert len(records(caplog)) == 2 and guard._events == {}
    assert "PRIVATE_LATE_ERROR" not in caplog.text


def test_paid_call_guard_prevents_provider_start_and_invocation(model_env, caplog):
    provider_calls = []
    guard = model_factory._ModelGuard(load_model_config("opinion"))
    model = LoggedReply(finish_reason="stop", callbacks=[guard], observer=lambda: provider_calls.append(True))

    with pytest.raises(PaidModelCallBlocked):
        model.invoke("PRIVATE_INPUT")

    assert provider_calls == [] and records(caplog) == [] and guard._events == {}


def test_provider_failure_logs_only_safe_error_type_and_cleans_state(observed_guard, caplog):
    class FailedReply(_FixedReplyModel):
        def _generate(self, *args, **kwargs):
            raise RuntimeError("PRIVATE_PROVIDER_FAILURE")

    guard = observed_guard()
    model = FailedReply(finish_reason="stop", callbacks=[guard])
    with pytest.raises(RuntimeError, match="PRIVATE_PROVIDER_FAILURE"):
        model.invoke("PRIVATE_INPUT")

    before, after = records(caplog)
    assert before["event_id"] == after["event_id"] and after["outcome"] == "failed"
    assert after["error_type"] == "RuntimeError" and guard._events == {}
    assert "PRIVATE_PROVIDER_FAILURE" not in caplog.text and "PRIVATE_INPUT" not in caplog.text


def test_usage_and_finish_reason_do_not_log_untrusted_values(observed_guard, caplog):
    guard = observed_guard()
    model = LoggedReply(finish_reason="PRIVATE_REASON", callbacks=[guard], reported_usage={
        "prompt_tokens": True, "completion_tokens": "PRIVATE_USAGE", "total_tokens": -1,
    })
    model.invoke("PRIVATE_INPUT")

    after = records(caplog)[1]
    assert not {"tokens_input", "tokens_output", "total_tokens"} & after.keys()
    assert after["finish_reason"] == "unknown"
    assert "PRIVATE_REASON" not in caplog.text and "PRIVATE_USAGE" not in caplog.text


def test_message_counts_include_system_user_and_tool_text_without_serializing_payloads(observed_guard, caplog):
    guard = observed_guard()
    model = LoggedReply(finish_reason="stop", callbacks=[guard])
    model.invoke([
        SystemMessage(content="PRIVATE_SYSTEM"),
        HumanMessage(content=[{"type": "text", "text": "PRIVATE_USER"},
                              {"type": "image_url", "image_url": {"url": "https://never-contact.invalid/private"}}]),
        ToolMessage(content="PRIVATE_TOOL", tool_call_id="tool-id"),
    ])

    before = records(caplog)[0]
    assert before["input_messages"] == 3
    assert before["input_characters"] == sum(map(len, ("PRIVATE_SYSTEM", "PRIVATE_USER", "PRIVATE_TOOL")))
    assert "PRIVATE_" not in caplog.text and "never-contact" not in caplog.text


def test_native_callback_identity_and_repeated_error_finish_once(observed_guard, caplog):
    guard = observed_guard()
    run_id, parent_id = uuid4(), uuid4()
    guard.on_chat_model_start({}, [[HumanMessage(content="PRIVATE_INPUT")]], run_id=run_id, parent_run_id=parent_id,
                              invocation_params={"stream": True})
    guard.on_llm_error(TimeoutError("PRIVATE_TIMEOUT"), run_id=run_id)
    guard.on_llm_error(TimeoutError("PRIVATE_TIMEOUT"), run_id=run_id)

    before, after = records(caplog)
    assert before["model_run_id"] == str(run_id) and before["parent_model_run_id"] == str(parent_id)
    assert before["streaming"] is True and after["outcome"] == "timeout"
    assert guard._events == {} and "PRIVATE_TIMEOUT" not in caplog.text


@pytest.mark.asyncio
async def test_actual_adapter_cancellation_cleans_only_its_concurrent_invocation(observed_guard, model_env, monkeypatch, caplog):
    entered = asyncio.Queue()
    release = asyncio.Event()

    async def respond(request):
        entered.put_nowait(True)
        await release.wait()
        return httpx.Response(200, json={
            "id": "scripted-reply", "object": "chat.completion", "created": 1, "model": "scripted",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "PRIVATE_REPLY"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
        })

    adapter = model_factory._ObservedChatCompletionsTransportAdapter
    model_env.setenv("OPINION_MODEL_MAX_RETRIES", "0")
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(model_factory, "_ObservedChatCompletionsTransportAdapter",
                            lambda **kwargs: adapter(http_async_client=client, **kwargs))
        model = model_factory.build_chat_model("opinion")
        guard = model.callbacks[0]

        async def call(name):
            with trigger_context(trigger="job", request_id=name):
                return await model.ainvoke("PRIVATE_INPUT")

        first = asyncio.create_task(call("first"))
        second = asyncio.create_task(call("second"))
        try:
            await asyncio.wait_for(entered.get(), timeout=2)
            await asyncio.wait_for(entered.get(), timeout=2)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            assert len(guard._events) == 1
            release.set()
            assert (await second).content == "PRIVATE_REPLY"
        finally:
            release.set()
            for task in (first, second):
                if not task.done():
                    task.cancel()
            await asyncio.gather(first, second, return_exceptions=True)

    result = records(caplog)
    assert len(result) == 4 and guard._events == {}
    for name, outcome in (("first", "cancelled"), ("second", "success")):
        before, after = [record for record in result if record["request_id"] == name]
        assert before["event_id"] == after["event_id"] and after["outcome"] == outcome
    assert model_factory._model_invocation.get() is None
    assert "PRIVATE_INPUT" not in caplog.text and "PRIVATE_REPLY" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_closing_native_stream_early_records_cancellation(observed_guard, caplog, asynchronous):
    guard = observed_guard(True)
    model = LoggedReply(finish_reason="stop", streaming=True, callbacks=[guard])
    if asynchronous:
        stream = model.astream("PRIVATE_INPUT")
        await anext(stream)
        assert len(records(caplog)) == 1
        await stream.aclose()
    else:
        stream = model.stream("PRIVATE_INPUT")
        next(stream)
        assert len(records(caplog)) == 1
        stream.close()

    assert len(records(caplog)) == 2 and records(caplog)[1]["outcome"] == "cancelled"
    assert guard._events == {}


def test_factory_suppresses_full_rubric_info_payload_but_keeps_warnings(model_env, captured_adapter_kwargs, caplog):
    vendor = logging.getLogger("deepagents.middleware.rubric")
    previous = vendor.level
    try:
        vendor.setLevel(logging.INFO)
        model_factory.build_chat_model("opinion")
        vendor.info("PRIVATE_RUBRIC_CRITERIA")
        vendor.warning("rubric warning retained")
        assert vendor.level == logging.WARNING
        assert "PRIVATE_RUBRIC_CRITERIA" not in caplog.text
        assert "rubric warning retained" in caplog.text
    finally:
        vendor.setLevel(previous)
