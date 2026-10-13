from __future__ import annotations

import asyncio
import os

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI

from services.graphs import model_factory
from services.graphs.model_config import GraphModelConfig
from services.graphs.model_factory import ModelOutputTruncatedError, build_chat_model

API_KEY = "bedrock-test-key-0123456789abcdef"
RUNTIME_US_EAST_1 = "https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1"

FACTORY_ENV = {
    "GRAPH_MODEL_PROVIDER": "bedrock",
    "GRAPH_MODEL_REGION": "us-east-1",
    "GRAPH_MODEL_TEMPERATURE": "1.0",
    "GRAPH_MODEL_TOP_P": "0.95",
    "GRAPH_MODEL_MAX_TOKENS": "8192",
    "GRAPH_MODEL_MAX_RETRIES": "6",
    "GRAPH_MODEL_REQUEST_TIMEOUT": "300",
    "GRAPH_MODEL_STREAMING": "false",
    "BIG_MODEL_ID": "us.moonshotai.kimi-k3",
    "BIG_MODEL_SERVER_URL": "https://bedrock-runtime.{region}.amazonaws.com/openai/v1",
    "BIG_MODEL_MAX_TOKENS": "16384",
    "SMALL_MODEL_ID": "moonshotai.kimi-k2.5",
    "SMALL_MODEL_SERVER_URL": "https://bedrock-mantle.{region}.api.aws/v1",
    "OPINION_MODEL_PRESET": "BIG",
    "OPINION_GRADER_MODEL_PRESET": "SMALL",
    "OPINION_MODEL_SERVER_API_KEY": API_KEY,
}


@pytest.fixture
def model_env(monkeypatch):
    """os.environ holding only FACTORY_ENV's graph model settings."""
    for name in [name for name in os.environ if "_MODEL_" in name]:
        monkeypatch.delenv(name)
    for name, value in FACTORY_ENV.items():
        monkeypatch.setenv(name, value)
    return monkeypatch


@pytest.fixture
def captured_adapter_kwargs(monkeypatch):
    captured: dict = {}

    class _FakeTransportAdapter:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(model_factory, "ChatCompletionsTransportAdapter", _FakeTransportAdapter)
    return captured


def test_adapter_is_built_from_the_resolved_config(model_env, captured_adapter_kwargs):
    build_chat_model("opinion")

    captured = captured_adapter_kwargs
    assert captured["model"] == "us.moonshotai.kimi-k3"
    assert captured["base_url"] == RUNTIME_US_EAST_1
    assert captured["api_key"] == API_KEY
    assert (captured["temperature"], captured["top_p"]) == (1.0, 0.95)
    assert captured["max_tokens"] == 16384
    assert (captured["max_retries"], captured["timeout"]) == (6, 300.0)
    assert captured["streaming"] is False
    assert "stream_usage" not in captured
    assert "extra_body" not in captured
    assert [type(callback).__name__ for callback in captured["callbacks"]] == ["_TruncationGuard"]


def test_grader_role_builds_from_its_own_preset(model_env, captured_adapter_kwargs):
    build_chat_model("opinion_grader", fallback_role="opinion")

    assert captured_adapter_kwargs["model"] == "moonshotai.kimi-k2.5"
    assert captured_adapter_kwargs["base_url"] == "https://bedrock-mantle.us-east-1.api.aws/v1"
    assert captured_adapter_kwargs["api_key"] == API_KEY


def test_streaming_also_requests_usage_in_the_stream(model_env, captured_adapter_kwargs):
    model_env.setenv("BIG_MODEL_STREAMING", "true")

    build_chat_model("opinion")

    assert captured_adapter_kwargs["streaming"] is True
    assert captured_adapter_kwargs["stream_usage"] is True


def test_extra_body_is_passed_through_as_a_plain_dict(model_env, captured_adapter_kwargs):
    model_env.setenv("OPINION_MODEL_EXTRA_BODY", '{"service_tier": "flex"}')

    build_chat_model("opinion")

    assert captured_adapter_kwargs["extra_body"] == {"service_tier": "flex"}
    assert type(captured_adapter_kwargs["extra_body"]) is dict


def test_real_adapter_accepts_every_factory_option(model_env):
    model_env.setenv("BIG_MODEL_STREAMING", "true")
    model_env.setenv("OPINION_MODEL_EXTRA_BODY", '{"service_tier": "flex"}')

    model = build_chat_model("opinion")

    assert isinstance(model, ChatOpenAI)
    assert (model.model_name, model.max_tokens, model.streaming, model.stream_usage) == (
        "us.moonshotai.kimi-k3",
        16384,
        True,
        True,
    )
    assert model.extra_body == {"service_tier": "flex"}
    assert model.openai_api_base == RUNTIME_US_EAST_1


class _FixedReplyModel(BaseChatModel):
    """Returns one canned generation so the guard runs inside LangChain's real invoke path."""

    finish_reason: str
    metadata_only: bool = False
    streaming: bool = False

    @property
    def _llm_type(self) -> str:
        return "fixed-reply"

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        # Streamed replies report finish_reason only on the final chunk.
        yield ChatGenerationChunk(message=AIMessageChunk(content="par"))
        yield ChatGenerationChunk(
            message=AIMessageChunk(content="tial"),
            generation_info={"finish_reason": self.finish_reason},
        )

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if self.metadata_only:
            message = AIMessage(content="partial", response_metadata={"finish_reason": self.finish_reason})
            generation = ChatGeneration(message=message)
        else:
            generation = ChatGeneration(
                message=AIMessage(content="partial"),
                generation_info={"finish_reason": self.finish_reason},
            )
        return ChatResult(generations=[generation])


def _guarded(finish_reason: str, *, metadata_only: bool = False, streaming: bool = False) -> _FixedReplyModel:
    config = GraphModelConfig(
        role="opinion",
        settings_chain=("OPINION", "BIG", "GRAPH"),
        provider="bedrock",
        model_id="us.moonshotai.kimi-k3",
        server_url=RUNTIME_US_EAST_1,
        server_api_key=API_KEY,
        temperature=1.0,
        top_p=0.95,
        max_tokens=64,
        max_retries=2,
        request_timeout=120.0,
        streaming=False,
        extra_body=None,
    )
    return _FixedReplyModel(
        finish_reason=finish_reason,
        metadata_only=metadata_only,
        streaming=streaming,
        callbacks=[model_factory._TruncationGuard(config)],
    )


def test_truncated_reply_raises_through_ainvoke():
    with pytest.raises(ModelOutputTruncatedError) as failure:
        asyncio.run(_guarded("length").ainvoke("hello"))

    message = str(failure.value)
    assert "Graph model role 'opinion' (us.moonshotai.kimi-k3)" in message
    assert "64-token output cap" in message
    assert "OPINION_MODEL_MAX_TOKENS, BIG_MODEL_MAX_TOKENS, GRAPH_MODEL_MAX_TOKENS" in message


def test_truncated_reply_raises_through_invoke():
    with pytest.raises(ModelOutputTruncatedError):
        _guarded("length").invoke("hello")


def test_truncation_on_the_final_streamed_chunk_raises():
    with pytest.raises(ModelOutputTruncatedError):
        asyncio.run(_guarded("length", streaming=True).ainvoke("hello"))


def test_complete_streamed_reply_passes_the_guard():
    assert _guarded("stop", streaming=True).invoke("hello").content == "partial"


def test_truncation_reported_only_in_response_metadata_still_raises():
    with pytest.raises(ModelOutputTruncatedError):
        _guarded("length", metadata_only=True).invoke("hello")


@pytest.mark.parametrize("finish_reason", ["stop", "tool_calls"])
def test_complete_replies_pass_the_guard(finish_reason):
    assert asyncio.run(_guarded(finish_reason).ainvoke("hello")).content == "partial"
