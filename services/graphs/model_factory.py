from __future__ import annotations

import os
import re
from dataclasses import dataclass

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI as ChatCompletionsTransportAdapter

DEFAULT_MODEL_PROVIDER = "bedrock"
DEFAULT_MODEL_ID = "moonshotai.kimi-k2.5"
DEFAULT_BEDROCK_REGION = "us-east-1"

_BEDROCK_MANTLE_URL_PATTERN = re.compile(r"https://bedrock-mantle\.[a-z0-9-]+\.api\.aws/v1")
_PLACEHOLDER_API_KEYS = frozenset({"", "your-bedrock-api-key", "local-kimi", "changeme"})
_MIN_API_KEY_LENGTH = 20
_OBSOLETE_SETTING_SUFFIXES = ("MODEL_THINKING",)


@dataclass(frozen=True)
class GraphModelConfig:
    provider: str
    model_id: str
    server_url: str
    server_api_key: str
    temperature: float
    top_p: float
    max_tokens: int


def build_chat_model(role: str, fallback_role: str | None = None) -> BaseChatModel:
    config = load_model_config(role, fallback_role=fallback_role)
    return _PROVIDER_BUILDERS[config.provider](config)


def load_model_config(role: str, fallback_role: str | None = None) -> GraphModelConfig:
    _reject_obsolete_settings(role, fallback_role)

    provider = _setting(
        role, "MODEL_PROVIDER", DEFAULT_MODEL_PROVIDER, fallback_role=fallback_role,
    ).strip()
    if provider not in _PROVIDER_BUILDERS:
        raise ValueError(
            f"Unsupported graph model provider '{provider}' for role '{role}'. "
            f"Supported providers: {', '.join(sorted(_PROVIDER_BUILDERS))}"
        )

    model_id = _setting(
        role, "MODEL_ID", DEFAULT_MODEL_ID, fallback_role=fallback_role,
        legacy_suffixes=("MODEL",),
    )
    server_url = _setting(
        role, "MODEL_SERVER_URL", "", fallback_role=fallback_role,
        legacy_suffixes=("MODEL_BASE_URL",),
    ).strip()
    if not server_url:
        region = _setting(
            role, "MODEL_REGION", DEFAULT_BEDROCK_REGION, fallback_role=fallback_role,
        ).strip()
        server_url = f"https://bedrock-mantle.{region}.api.aws/v1"
    server_api_key = _setting(
        role, "MODEL_SERVER_API_KEY", "",
        fallback_role=fallback_role, legacy_suffixes=("MODEL_API_KEY",),
    )

    config = GraphModelConfig(
        provider=provider,
        model_id=model_id.strip(),
        server_url=server_url,
        server_api_key=server_api_key.strip(),
        temperature=_float_setting(role, "MODEL_TEMPERATURE", 1.0, fallback_role),
        top_p=_float_setting(role, "MODEL_TOP_P", 0.95, fallback_role),
        max_tokens=_int_setting(role, "MODEL_MAX_TOKENS", 8192, fallback_role),
    )
    _validate_config(role, config)
    return config


def _build_bedrock(config: GraphModelConfig) -> BaseChatModel:
    return ChatCompletionsTransportAdapter(
        model=config.model_id,
        base_url=config.server_url,
        api_key=config.server_api_key,
        temperature=config.temperature,
        top_p=config.top_p,
        max_tokens=config.max_tokens,
    )


_PROVIDER_BUILDERS = {
    "bedrock": _build_bedrock,
}


def _validate_config(role: str, config: GraphModelConfig) -> None:
    prefix = _role_prefix(role)
    assert config.model_id, f"{prefix}_MODEL_ID must be set"
    if config.provider == "bedrock":
        _validate_bedrock_config(prefix, config)
    if config.temperature < 0:
        raise ValueError(f"{prefix}_MODEL_TEMPERATURE must be non-negative")
    if not 0 < config.top_p <= 1:
        raise ValueError(f"{prefix}_MODEL_TOP_P must be in (0, 1]")
    if config.max_tokens <= 0:
        raise ValueError(f"{prefix}_MODEL_MAX_TOKENS must be positive")


def _validate_bedrock_config(prefix: str, config: GraphModelConfig) -> None:
    if "/" in config.model_id:
        raise ValueError(
            f"{prefix}_MODEL_ID must use Bedrock dot notation, e.g. "
            f"'moonshotai.kimi-k2.5', not a Hugging Face path like '{config.model_id}'"
        )
    if not _BEDROCK_MANTLE_URL_PATTERN.fullmatch(config.server_url):
        raise ValueError(
            f"{prefix}_MODEL_SERVER_URL must look like "
            f"https://bedrock-mantle.<region>.api.aws/v1, got '{config.server_url}'"
        )
    if (
        config.server_api_key in _PLACEHOLDER_API_KEYS
        or len(config.server_api_key) < _MIN_API_KEY_LENGTH
    ):
        raise ValueError(
            f"{prefix}_MODEL_SERVER_API_KEY must be a real Amazon Bedrock API key "
            "(Bedrock console -> API keys -> create long-term key). "
            "See docs/kimi-bedrock.md."
        )


def _reject_obsolete_settings(role: str, fallback_role: str | None) -> None:
    prefixes = [_role_prefix(role)]
    if fallback_role:
        prefixes.append(_role_prefix(fallback_role))
    prefixes.append("GRAPH")
    for prefix in prefixes:
        for suffix in _OBSOLETE_SETTING_SUFFIXES:
            name = f"{prefix}_{suffix}"
            if name in os.environ:
                raise ValueError(
                    f"{name} is obsolete: the SGLang 'thinking' toggle was removed "
                    "with the self-hosted aws_kimi provider. Remove the variable; "
                    "Bedrock manages Kimi reasoning server-side. "
                    "See docs/kimi-bedrock.md."
                )


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


def _int_setting(
    role: str,
    suffix: str,
    default: int,
    fallback_role: str | None,
) -> int:
    raw = _setting(role, suffix, str(default), fallback_role=fallback_role)
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{_role_prefix(role)}_{suffix} must be an integer") from exc


def _role_prefix(role: str) -> str:
    prefix = re.sub(r"[^A-Z0-9]+", "_", role.upper()).strip("_")
    assert prefix, "model role must be non-empty"
    return prefix
