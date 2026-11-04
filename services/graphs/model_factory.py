from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar
import logging
from threading import Lock
from typing import Any
from uuid import UUID, uuid4

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGeneration, Generation, LLMResult
from langchain_openai import ChatOpenAI as ChatCompletionsTransportAdapter

from scripts.shared.automated_tests import require_model_calls_allowed
from services.graphs.model_config import SUPPORTED_PROVIDERS, GraphModelConfig, load_model_config
from services.observability import BillableEvent, error_outcome

_model_invocation: ContextVar[UUID | None] = ContextVar("model_invocation", default=None)
_FINISH_REASONS = frozenset({"stop", "length", "tool_calls", "function_call", "content_filter"})


class ModelOutputTruncatedError(RuntimeError):
    """A completion stopped at its token cap, so its text is incomplete."""


def build_chat_model(role: str, fallback_role: str | None = None) -> BaseChatModel:
    # Rubric INFO records include full criteria; owned events retain only invocation metadata.
    logging.getLogger("deepagents.middleware.rubric").setLevel(logging.WARNING)
    config = load_model_config(role, fallback_role)
    return _PROVIDER_BUILDERS[config.provider](config)


class _ObservedChatCompletionsTransportAdapter(ChatCompletionsTransportAdapter):
    async def agenerate(self, *args: Any, **kwargs: Any) -> LLMResult:
        invocation = uuid4()
        token = _model_invocation.set(invocation)
        try:
            return await super().agenerate(*args, **kwargs)
        except BaseException as error:
            # Native agenerate can cancel its gather without dispatching on_llm_error.
            callbacks = getattr(self.callbacks, "handlers", self.callbacks) or []
            for callback in callbacks:
                if isinstance(callback, _ModelGuard):
                    callback.finish_invocation(invocation, error)
            raise
        finally:
            _model_invocation.reset(token)


def _build_bedrock(config: GraphModelConfig) -> BaseChatModel:
    optional: dict[str, Any] = {}
    if config.streaming:
        optional["stream_usage"] = True
    if config.extra_body:
        optional["extra_body"] = dict(config.extra_body)
    return _ObservedChatCompletionsTransportAdapter(
        model=config.model_id,
        base_url=config.server_url,
        api_key=config.server_api_key,
        temperature=config.temperature,
        top_p=config.top_p,
        max_tokens=config.max_tokens,
        max_retries=config.max_retries,
        timeout=config.request_timeout,
        streaming=config.streaming,
        callbacks=[_ModelGuard(config)],
        **optional,
    )


_PROVIDER_BUILDERS = {
    "bedrock": _build_bedrock,
}
assert set(_PROVIDER_BUILDERS) == set(SUPPORTED_PROVIDERS), (
    "model_config.SUPPORTED_PROVIDERS and model_factory._PROVIDER_BUILDERS must list the same providers"
)


class _TruncationGuard(BaseCallbackHandler):
    # Without raise_error LangChain only logs callback exceptions, and a cut-off
    # reply would be graded, parsed, or posted as if it were complete.
    raise_error = True
    run_inline = True

    def __init__(self, config: GraphModelConfig) -> None:
        self._config = config

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        reasons = (_finish_reason(g) for generations in response.generations for g in generations)
        if "length" not in reasons:
            return
        config = self._config
        settings = ", ".join(f"{prefix}_MODEL_MAX_TOKENS" for prefix in config.settings_chain)
        raise ModelOutputTruncatedError(
            f"Graph model role '{config.role}' ({config.model_id}) stopped at its "
            f"{config.max_tokens}-token output cap (finish_reason=length), so the reply is "
            f"incomplete; reasoning tokens count against the cap. Raise one of: {settings}."
        )


class _ModelGuard(_TruncationGuard):
    def __init__(self, config: GraphModelConfig) -> None:
        super().__init__(config)
        self._events: dict[UUID, tuple[BillableEvent, UUID | None]] = {}
        self._events_lock = Lock()

    def on_chat_model_start(
        self, serialized: dict[str, Any], messages: list[list[BaseMessage]], *,
        run_id: UUID, parent_run_id: UUID | None = None, **kwargs: Any,
    ) -> None:
        require_model_calls_allowed()
        config = self._config
        parameters = kwargs.get("invocation_params")
        streaming = parameters.get("stream") if isinstance(parameters, Mapping) else None
        streaming = streaming if type(streaming) is bool else config.streaming
        with self._events_lock:
            if run_id in self._events:
                raise ValueError("Model call run_id is already active")
            event = BillableEvent.start(
                config.provider, "chat_completion", model_role=config.role, model=config.model_id,
                streaming=streaming, sdk_retries=config.max_retries,
                model_run_id=run_id, parent_model_run_id=parent_run_id, **_input_size(messages),
            )
            self._events[run_id] = (event, _model_invocation.get())

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        with self._events_lock:
            pending = self._events.pop(run_id, None)
        if pending is not None:
            pending[0].finish(**_completion_fields(response))
        super().on_llm_end(response, run_id=run_id, **kwargs)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        with self._events_lock:
            pending = self._events.pop(run_id, None)
        if pending is not None:
            pending[0].finish(error_outcome(error), error=error)

    def finish_invocation(self, invocation: UUID, error: BaseException) -> None:
        with self._events_lock:
            active = [run_id for run_id, (_, owner) in self._events.items() if owner == invocation]
            pending = [self._events.pop(run_id)[0] for run_id in active]
        for event in pending:
            event.finish(error_outcome(error), error=error)


def _completion_fields(response: LLMResult) -> dict[str, Any]:
    usage = (response.llm_output or {}).get("token_usage")
    aliases = {"prompt_tokens": "tokens_input", "completion_tokens": "tokens_output", "total_tokens": "total_tokens"}
    if not isinstance(usage, Mapping):
        usage = next((getattr(generation.message, "usage_metadata", None)
                      for group in response.generations for generation in group
                      if isinstance(generation, ChatGeneration)
                      and isinstance(getattr(generation.message, "usage_metadata", None), Mapping)), {})
        aliases = {"input_tokens": "tokens_input", "output_tokens": "tokens_output", "total_tokens": "total_tokens"}
    fields = {target: usage[source] for source, target in aliases.items()
              if type(usage.get(source)) is int and usage[source] >= 0}
    reasons = [_finish_reason(generation) for group in response.generations for generation in group]
    known = [reason for reason in reasons if isinstance(reason, str) and reason in _FINISH_REASONS]
    return {**fields, "finish_reason": known[0] if known else "unknown", "completion": "sdk_call"}


def _input_size(messages: list[list[BaseMessage]]) -> dict[str, int]:
    count = characters = 0
    for group in messages:
        for message in group:
            count += 1
            content = message.content
            if isinstance(content, str):
                characters += len(content)
            elif isinstance(content, list):
                for block in content:
                    text = block.get("text") if isinstance(block, Mapping) else block
                    if isinstance(text, str):
                        characters += len(text)
    return {"input_messages": count, "input_characters": characters}


def _finish_reason(generation: Generation) -> str | None:
    reason = (generation.generation_info or {}).get("finish_reason")
    if reason is None and isinstance(generation, ChatGeneration):
        reason = generation.message.response_metadata.get("finish_reason")
    return reason
