from __future__ import annotations

import os
import re
from dataclasses import dataclass

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI as ChatCompletionsTransportAdapter

DEFAULT_MODEL_PROVIDER = "aws_kimi"
DEFAULT_MODEL_ID = "moonshotai/Kimi-K2.6"
DEFAULT_MODEL_SERVER_URL = "http://localhost:30000/v1"
DEFAULT_MODEL_SERVER_API_KEY = "local-kimi"


@dataclass(frozen=True)
class GraphModelConfig:
    provider: str
    model_id: str
    server_url: str
    server_api_key: str
    temperature: float
    top_p: float
    thinking: bool


def build_chat_model(role: str, fallback_role: str | None = None) -> BaseChatModel:
    config = load_model_config(role, fallback_role=fallback_role)
    if config.provider == "aws_kimi":
        return _build_chat_completions_adapter(config)
    raise ValueError(
        f"Unsupported graph model provider '{config.provider}' for role '{role}'"
    )


def load_model_config(role: str, fallback_role: str | None = None) -> GraphModelConfig:
    provider = _setting(
        role, "MODEL_PROVIDER", DEFAULT_MODEL_PROVIDER, fallback_role=fallback_role,
    )
    model_id = _setting(
        role, "MODEL_ID", DEFAULT_MODEL_ID, fallback_role=fallback_role,
        legacy_suffixes=("MODEL",),
    )
    server_url = _setting(
        role, "MODEL_SERVER_URL", DEFAULT_MODEL_SERVER_URL, fallback_role=fallback_role,
        legacy_suffixes=("MODEL_BASE_URL",),
    )
    server_api_key = _setting(
        role, "MODEL_SERVER_API_KEY", DEFAULT_MODEL_SERVER_API_KEY,
        fallback_role=fallback_role, legacy_suffixes=("MODEL_API_KEY",),
    )

    config = GraphModelConfig(
        provider=provider.strip(),
        model_id=model_id.strip(),
        server_url=server_url.strip(),
        server_api_key=server_api_key.strip(),
        temperature=_float_setting(role, "MODEL_TEMPERATURE", 1.0, fallback_role),
        top_p=_float_setting(role, "MODEL_TOP_P", 0.95, fallback_role),
        thinking=_bool_setting(role, "MODEL_THINKING", True, fallback_role),
    )
    _validate_config(role, config)
    return config


def _build_chat_completions_adapter(config: GraphModelConfig) -> BaseChatModel:
    return ChatCompletionsTransportAdapter(
        model=config.model_id,
        base_url=config.server_url,
        api_key=config.server_api_key,
        temperature=config.temperature,
        top_p=config.top_p,
        extra_body={"chat_template_kwargs": {"thinking": config.thinking}},
    )


def _validate_config(role: str, config: GraphModelConfig) -> None:
    assert config.provider, f"{_role_prefix(role)}_MODEL_PROVIDER must be set"
    assert config.model_id, f"{_role_prefix(role)}_MODEL_ID must be set"
    assert config.server_url, f"{_role_prefix(role)}_MODEL_SERVER_URL must be set"
    assert config.server_api_key, f"{_role_prefix(role)}_MODEL_SERVER_API_KEY must be set"
    if config.temperature < 0:
        raise ValueError(f"{_role_prefix(role)}_MODEL_TEMPERATURE must be non-negative")
    if not 0 < config.top_p <= 1:
        raise ValueError(f"{_role_prefix(role)}_MODEL_TOP_P must be in (0, 1]")


def _setting(
    role: str,
    suffix: str,
    default: str,
    *,
    fallback_role: str | None = None,
    legacy_suffixes: tuple[str, ...] = (),
) -> str:
    suffixes = (suffix, *legacy_suffixes)
    prefixes = [_role_prefix(role)]
    if fallback_role:
        prefixes.append(_role_prefix(fallback_role))
    prefixes.append("GRAPH")

    for prefix in prefixes:
        for candidate_suffix in suffixes:
            value = os.environ.get(f"{prefix}_{candidate_suffix}")
            if value is not None:
                return value
    return default


def _float_setting(
    role: str,
    suffix: str,
    default: float,
    fallback_role: str | None,
) -> float:
    raw = _setting(role, suffix, str(default), fallback_role=fallback_role)
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{_role_prefix(role)}_{suffix} must be a number") from exc


def _bool_setting(
    role: str,
    suffix: str,
    default: bool,
    fallback_role: str | None,
) -> bool:
    raw = _setting(role, suffix, "true" if default else "false", fallback_role=fallback_role)
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{_role_prefix(role)}_{suffix} must be a boolean")


def _role_prefix(role: str) -> str:
    prefix = re.sub(r"[^A-Z0-9]+", "_", role.upper()).strip("_")
    assert prefix, "model role must be non-empty"
    return prefix
