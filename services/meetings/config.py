from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Mapping

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}")
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_FIELDS = {"provider", "account_key", "api_key_env", "project", "provider_options"}


@dataclass(frozen=True)
class SourceConfig:
    name: str
    provider: str
    account_key: str
    api_key: str = field(repr=False)
    project: str | None = None
    provider_options: dict = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        settings = {"options": self.provider_options, "project": self.project}
        return hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()


def _source_settings(env: Mapping[str, str]) -> dict[str, dict]:
    try:
        sources = json.loads(env.get("MEETING_SOURCES_JSON", "{}"))
    except (ValueError, TypeError):
        raise ValueError("MEETING_SOURCES_JSON must contain a JSON object") from None
    if not isinstance(sources, dict):
        raise ValueError("MEETING_SOURCES_JSON must contain a JSON object")
    identities: set[tuple[str, str]] = set()
    for source_name, settings in sources.items():
        if not _NAME.fullmatch(source_name) or not isinstance(settings, dict):
            raise ValueError("Meeting sources must map valid names to settings objects")
        if set(settings) - _FIELDS:
            raise ValueError(f"Meeting source '{source_name}' has unsupported settings")
        for required in ("provider", "account_key", "api_key_env"):
            value = settings.get(required)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Meeting source '{source_name}' requires {required}")
        if not _NAME.fullmatch(settings["account_key"]):
            raise ValueError(f"Meeting source '{source_name}' requires a stable account_key name")
        if not _ENV_NAME.fullmatch(settings["api_key_env"]):
            raise ValueError(f"Meeting source '{source_name}' has an invalid api_key_env reference")
        options = settings.get("provider_options", {})
        if not isinstance(options, dict):
            raise ValueError(f"Meeting source '{source_name}' provider_options must be an object")
        project = settings.get("project")
        if project is not None and (not isinstance(project, str) or not project.strip() or len(project) > 200):
            raise ValueError(f"Meeting source '{source_name}' project must be nonblank or null")
        identity = (settings["provider"], settings["account_key"])
        if identity in identities:
            raise ValueError("Configure only one meeting source per provider/account_key")
        identities.add(identity)
    return sources


def list_source_names(env: Mapping[str, str] | None = None) -> list[str]:
    return sorted(_source_settings(os.environ if env is None else env))


def load_source_config(name: str, env: Mapping[str, str] | None = None) -> SourceConfig:
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError("Meeting source must be a nonblank name of at most 100 characters")
    env = os.environ if env is None else env
    sources = _source_settings(env)
    if name not in sources:
        raise ValueError(f"Unknown meeting source '{name}'; configure MEETING_SOURCES_JSON")
    settings = sources[name]
    key = env.get(settings["api_key_env"], "").strip()
    if not key or key in {"changeme", "your-granola-api-key"}:
        raise ValueError(f"Meeting source '{name}' requires the {settings['api_key_env']} environment variable")
    return SourceConfig(
        name=name,
        provider=settings["provider"],
        account_key=settings["account_key"],
        api_key=key,
        project=settings.get("project"),
        provider_options=dict(settings.get("provider_options", {})),
    )
