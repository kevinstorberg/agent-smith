from __future__ import annotations

from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatGeneration, Generation, LLMResult
from langchain_openai import ChatOpenAI as ChatCompletionsTransportAdapter

from scripts.shared.automated_tests import require_model_calls_allowed
from services.graphs.model_config import SUPPORTED_PROVIDERS, GraphModelConfig, load_model_config


class ModelOutputTruncatedError(RuntimeError):
    """A completion stopped at its token cap, so its text is incomplete."""


def build_chat_model(role: str, fallback_role: str | None = None) -> BaseChatModel:
    config = load_model_config(role, fallback_role)
    return _PROVIDER_BUILDERS[config.provider](config)


def _build_bedrock(config: GraphModelConfig) -> BaseChatModel:
    optional: dict[str, Any] = {}
    if config.streaming:
        optional["stream_usage"] = True
    if config.extra_body:
        optional["extra_body"] = dict(config.extra_body)
    return ChatCompletionsTransportAdapter(
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
    def on_chat_model_start(self, *args: Any, **kwargs: Any) -> None:
        require_model_calls_allowed()


def _finish_reason(generation: Generation) -> str | None:
    reason = (generation.generation_info or {}).get("finish_reason")
    if reason is None and isinstance(generation, ChatGeneration):
        reason = generation.message.response_metadata.get("finish_reason")
    return reason
