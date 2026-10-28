"""Graph model settings, resolved from environment variables.

A graph model role (opinion, opinion_grader, curator, chat_kimi, ...) reads each
MODEL_* setting from the first of these that defines it:

1. <ROLE>_MODEL_*    the role itself
2. <PRESET>_MODEL_*  the preset named by the role's own <ROLE>_MODEL_PRESET
3. <PARENT>_MODEL_*  the parent role's own settings (credentials, region, limits)
4. GRAPH_MODEL_*     global defaults

A preset bundles a model id with the endpoint that serves it and its limits, so
switching or adding a model is a configuration change. Presets are never
inherited from the parent role: every role names its own model.

Pure environment parsing (no LangChain, no HTTP), so the chat participant
registry can validate participants without building clients.
"""
from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, TypeVar

from scripts.shared.env import env_prefix

GLOBAL_PREFIX = "GRAPH"
SUPPORTED_PROVIDERS = ("bedrock",)
SETTINGS_REFERENCE = "See the graph model settings in .env.default."

_REGION = r"[a-z]{2}(?:-[a-z]+)+-\d+"
_REGION_PATTERN = re.compile(_REGION)
_BEDROCK_URL_PATTERN = re.compile(
    rf"https://bedrock-[a-z0-9-]+\.(?P<region>{_REGION})\.(?:api\.aws|amazonaws\.com)(?:/\S*)?"
)
_REGION_PLACEHOLDER = "{region}"
_PLACEHOLDER_API_KEYS = frozenset({"", "your-bedrock-api-key", "local-kimi", "changeme"})
_MIN_API_KEY_LENGTH = 20
_BOOLEANS = {"true": True, "false": False}
_PROVIDER_REQUIREMENT = f"one of the supported providers: {', '.join(SUPPORTED_PROVIDERS)}"
_BEDROCK_URL_EXAMPLES = (
    "https://bedrock-mantle.{region}.api.aws/v1 or "
    "https://bedrock-runtime.{region}.amazonaws.com/openai/v1"
)

# Request fields the factory or LangChain already send. EXTRA_BODY is merged
# last, so letting it set these would silently override the dedicated setting.
_MANAGED_REQUEST_FIELDS = {
    "model": "MODEL_ID",
    "max_tokens": "MODEL_MAX_TOKENS",
    "max_completion_tokens": "MODEL_MAX_TOKENS",
    "temperature": "MODEL_TEMPERATURE",
    "top_p": "MODEL_TOP_P",
    "stream": "MODEL_STREAMING",
    "stream_options": "MODEL_STREAMING",
    "messages": None,
    "tools": None,
    "tool_choice": None,
    "response_format": None,
}

# Suffixes that fail loudly instead of being ignored or silently aliased. The
# legacy aliases are rejected because a preset prefix would otherwise read
# unrelated variables (a preset named EVAL would pick up EVAL_MODEL).
_OBSOLETE_SUFFIXES = {
    "MODEL_THINKING": (
        "the SGLang 'thinking' toggle was removed with the self-hosted aws_kimi "
        "provider; Bedrock manages Kimi reasoning server-side"
    ),
    "MODEL": "it was renamed to MODEL_ID",
    "MODEL_BASE_URL": "it was renamed to MODEL_SERVER_URL",
    "MODEL_API_KEY": "it was renamed to MODEL_SERVER_API_KEY",
}

T = TypeVar("T")


@dataclass(frozen=True)
class GraphModelConfig:
    role: str
    settings_chain: tuple[str, ...]
    provider: str
    model_id: str
    server_url: str
    server_api_key: str = field(repr=False)
    temperature: float
    top_p: float
    max_tokens: int
    max_retries: int
    request_timeout: float
    streaming: bool
    extra_body: Mapping[str, Any] | None


def load_model_config(
    role: str,
    fallback_role: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> GraphModelConfig:
    settings = _role_settings(role, fallback_role, env)
    provider = settings.require("MODEL_PROVIDER", _parse_provider, _PROVIDER_REQUIREMENT)
    return GraphModelConfig(
        role=role,
        settings_chain=settings.prefixes,
        provider=provider,
        model_id=_model_id(settings),
        server_url=_bedrock_server_url(settings),
        server_api_key=_bedrock_api_key(settings),
        temperature=settings.require("MODEL_TEMPERATURE", _non_negative_float, "a number >= 0"),
        top_p=settings.require("MODEL_TOP_P", _unit_interval_float, "a number in (0, 1]"),
        max_tokens=settings.require("MODEL_MAX_TOKENS", _positive_int, "a positive integer"),
        max_retries=settings.require("MODEL_MAX_RETRIES", _non_negative_int, "an integer >= 0"),
        request_timeout=settings.require(
            "MODEL_REQUEST_TIMEOUT", _positive_float, "a positive number of seconds"
        ),
        streaming=settings.require("MODEL_STREAMING", _parse_boolean, "true or false"),
        extra_body=_extra_body(settings),
    )


def resolve_model_id(
    role: str,
    fallback_role: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> str:
    """The role's model id, checked without reading credentials."""
    return _model_id(_role_settings(role, fallback_role, env))


@dataclass(frozen=True)
class _RoleSettings:
    role: str
    prefixes: tuple[str, ...]
    env: Mapping[str, str]

    def candidates(self, suffix: str) -> list[str]:
        return [f"{prefix}_{suffix}" for prefix in self.prefixes]

    def find(self, suffix: str) -> tuple[str, str] | None:
        for name in self.candidates(suffix):
            if name in self.env:
                return name, self.env[name]
        return None

    def require_raw(self, suffix: str, hint: str = "") -> tuple[str, str]:
        found = self.find(suffix)
        if found is None:
            raise ValueError(
                f"Graph model role '{self.role}' has no {suffix} configured; set one of: "
                f"{', '.join(self.candidates(suffix))}{hint}. {SETTINGS_REFERENCE}"
            )
        return found

    def require(
        self,
        suffix: str,
        parse: Callable[[str], T],
        requirement: str,
        hint: str = "",
    ) -> T:
        source, raw = self.require_raw(suffix, hint)
        try:
            return parse(raw.strip())
        except ValueError:
            raise ValueError(
                f"{source} must be {requirement}, got {raw!r} (graph model role '{self.role}')"
            ) from None


def _role_settings(
    role: str,
    fallback_role: str | None,
    env: Mapping[str, str] | None,
) -> _RoleSettings:
    assert isinstance(role, str) and role.strip(), "graph model role must be a non-empty string"
    env = os.environ if env is None else env
    role_prefix = env_prefix(role)
    levels = [role_prefix]
    if fallback_role is not None:
        levels.append(env_prefix(fallback_role))
    levels.append(GLOBAL_PREFIX)
    if len(set(levels)) != len(levels):
        raise ValueError(
            f"Graph model role '{role}' (parent {fallback_role!r}) must not share a settings "
            f"prefix with its parent or {GLOBAL_PREFIX}; got {' -> '.join(levels)}"
        )
    if f"{GLOBAL_PREFIX}_MODEL_PRESET" in env:
        raise ValueError(
            f"{GLOBAL_PREFIX}_MODEL_PRESET is not supported: each role names its own "
            f"preset with <ROLE>_MODEL_PRESET. {SETTINGS_REFERENCE}"
        )

    prefixes = [role_prefix]
    preset_name = env.get(f"{role_prefix}_MODEL_PRESET")
    if preset_name is not None:
        prefixes.append(_validated_preset(role_prefix, preset_name, levels, env))
    prefixes.extend(levels[1:])
    _reject_obsolete_settings(prefixes, env)
    return _RoleSettings(role=role, prefixes=tuple(prefixes), env=env)


def _validated_preset(
    role_prefix: str,
    preset_name: str,
    levels: list[str],
    env: Mapping[str, str],
) -> str:
    setting = f"{role_prefix}_MODEL_PRESET"
    if not preset_name.strip():
        raise ValueError(f"{setting} is empty; name a preset or remove the setting. {SETTINGS_REFERENCE}")
    try:
        preset = env_prefix(preset_name)
    except ValueError as exc:
        raise ValueError(f"{setting}: {exc}. {SETTINGS_REFERENCE}") from None
    if preset in levels:
        raise ValueError(
            f"{setting}={preset_name!r} names a role settings level, not a preset. {SETTINGS_REFERENCE}"
        )
    if f"{preset}_MODEL_PRESET" in env:
        raise ValueError(
            f"{setting} names preset {preset}, which sets {preset}_MODEL_PRESET itself; "
            f"presets cannot name other presets. {SETTINGS_REFERENCE}"
        )
    if not any(name.startswith(f"{preset}_MODEL_") for name in env):
        raise ValueError(
            f"{setting} names preset {preset!r}, but no {preset}_MODEL_* settings are "
            f"defined. {SETTINGS_REFERENCE}"
        )
    return preset


def _reject_obsolete_settings(prefixes: list[str], env: Mapping[str, str]) -> None:
    for prefix in prefixes:
        for suffix, reason in _OBSOLETE_SUFFIXES.items():
            name = f"{prefix}_{suffix}"
            if name in env:
                raise ValueError(f"{name} is obsolete: {reason}. Remove it. {SETTINGS_REFERENCE}")


def _model_id(settings: _RoleSettings) -> str:
    return settings.require(
        "MODEL_ID",
        _parse_model_id,
        "a Bedrock model id in dot notation such as 'moonshotai.kimi-k2.5', "
        "not a Hugging Face path",
        hint=f" (or name a preset with {settings.prefixes[0]}_MODEL_PRESET)",
    )


def _bedrock_server_url(settings: _RoleSettings) -> str:
    source, template = settings.require_raw("MODEL_SERVER_URL")
    template = template.strip()
    region_source, region = settings.find("MODEL_REGION") or (None, None)
    if region is not None:
        region = region.strip()
        if not _REGION_PATTERN.fullmatch(region):
            raise ValueError(f"{region_source} must be an AWS region such as us-east-1, got {region!r}")

    if _REGION_PLACEHOLDER in template:
        if region is None:
            raise ValueError(
                f"{source} uses {_REGION_PLACEHOLDER}, but graph model role '{settings.role}' has "
                f"no MODEL_REGION; set one of: {', '.join(settings.candidates('MODEL_REGION'))}"
            )
        url = template.replace(_REGION_PLACEHOLDER, region)
    else:
        url = template

    if "{" in url or "}" in url:
        raise ValueError(
            f"{source} contains an unknown placeholder; only {_REGION_PLACEHOLDER} is "
            f"supported, got {template!r}"
        )
    match = _BEDROCK_URL_PATTERN.fullmatch(url)
    if match is None:
        raise ValueError(
            f"{source} must be an https Amazon Bedrock endpoint such as "
            f"{_BEDROCK_URL_EXAMPLES}, got {template!r}"
        )
    if region is not None and _REGION_PLACEHOLDER not in template and match["region"] != region:
        raise ValueError(
            f"{source} targets region {match['region']}, but {region_source} is {region!r}; "
            f"use {_REGION_PLACEHOLDER} in the URL or make them agree"
        )
    return url


def _bedrock_api_key(settings: _RoleSettings) -> str:
    found = settings.find("MODEL_SERVER_API_KEY")
    key = found[1].strip() if found else ""
    if key in _PLACEHOLDER_API_KEYS or len(key) < _MIN_API_KEY_LENGTH:
        source = found[0] if found else f"one of {', '.join(settings.candidates('MODEL_SERVER_API_KEY'))}"
        raise ValueError(
            f"{source} must be a real Amazon Bedrock API key for graph model role "
            f"'{settings.role}' (Bedrock console -> API keys -> create long-term key). "
            f"{SETTINGS_REFERENCE}"
        )
    return key


def _extra_body(settings: _RoleSettings) -> Mapping[str, Any] | None:
    found = settings.find("MODEL_EXTRA_BODY")
    if found is None:
        return None
    source, raw = found
    try:
        body = json.loads(raw)
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise ValueError(f"{source} must be a JSON object such as '{{\"service_tier\": \"flex\"}}', got {raw!r}")
    for key in body:
        if key in _MANAGED_REQUEST_FIELDS:
            dedicated = _MANAGED_REQUEST_FIELDS[key]
            remedy = f"set {dedicated} instead" if dedicated else "the graph runtime sets it"
            raise ValueError(f"{source} may not set {key!r}: {remedy}")
    return MappingProxyType(body)



def _parse_provider(raw: str) -> str:
    if raw not in SUPPORTED_PROVIDERS:
        raise ValueError(raw)
    return raw


def _parse_model_id(raw: str) -> str:
    if not raw or "/" in raw:
        raise ValueError(raw)
    return raw


def _parse_boolean(raw: str) -> bool:
    try:
        return _BOOLEANS[raw.lower()]
    except KeyError:
        raise ValueError(raw) from None


def _finite_float(raw: str) -> float:
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(raw)
    return value


def _non_negative_float(raw: str) -> float:
    value = _finite_float(raw)
    if value < 0:
        raise ValueError(raw)
    return value


def _positive_float(raw: str) -> float:
    value = _finite_float(raw)
    if value <= 0:
        raise ValueError(raw)
    return value


def _unit_interval_float(raw: str) -> float:
    value = _finite_float(raw)
    if not 0 < value <= 1:
        raise ValueError(raw)
    return value


def _non_negative_int(raw: str) -> int:
    value = int(raw)
    if value < 0:
        raise ValueError(raw)
    return value


def _positive_int(raw: str) -> int:
    value = int(raw)
    if value <= 0:
        raise ValueError(raw)
    return value
