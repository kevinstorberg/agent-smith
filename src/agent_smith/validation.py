from __future__ import annotations

import re
from datetime import timedelta

from src.agent_smith.constants import ALL_AGENTS, ITEM_TYPES

MAX_NAME_LENGTH = 40
MAX_TITLE_LENGTH = 200
MAX_BODY_LENGTH = 100_000
INTERVAL_KEYS = ("seconds", "minutes", "hours", "days")
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def assert_not_empty(value, field: str) -> None:
    if not value:
        raise ValueError(f"{field} must not be empty.")


def validate_item_type(item_type: str) -> str:
    if item_type not in ITEM_TYPES:
        raise ValueError(f"Invalid item_type: {item_type}. Must be one of {set(ITEM_TYPES)}.")
    return item_type


def validate_item_name(name: str) -> str:
    if not _NAME_RE.match(name):
        raise ValueError(
            "name must start with a lowercase letter and contain only lowercase letters, digits, and underscores"
        )
    return name


def validate_content(content: dict) -> dict:
    if not isinstance(content, dict) or "body" not in content or not isinstance(content["body"], str):
        raise ValueError("content must have a 'body' key with a string value")
    return content


def validate_agents_list(agents: list[str], allowed: list[str] | None = None) -> list[str]:
    allowed_agents = allowed or ALL_AGENTS
    invalid = set(agents) - set(allowed_agents)
    if invalid:
        raise ValueError(f"Invalid agents: {invalid}. Must be from {allowed_agents}")
    return agents


def validate_repo_format(repo: str) -> str:
    if repo != "*" and not repo.startswith("/"):
        raise ValueError("repo must be '*' or an absolute path")
    return repo


def validate_memory_id(memory_id: str) -> str:
    if not _UUID_RE.match(memory_id):
        raise ValueError(f"Invalid memory ID format: {memory_id}")
    return memory_id


def parse_interval(schedule_config: dict) -> timedelta:
    if not isinstance(schedule_config, dict) or not schedule_config:
        raise ValueError("schedule_config must be a non-empty interval dict, e.g. {'minutes': 5}")
    unknown = set(schedule_config) - set(INTERVAL_KEYS)
    if unknown:
        raise ValueError(
            f"schedule_config has unsupported keys {sorted(unknown)}; allowed keys are {list(INTERVAL_KEYS)}"
        )
    kwargs: dict[str, float] = {}
    for key, value in schedule_config.items():
        if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
            raise ValueError(f"schedule_config['{key}'] must be a positive number, got {value!r}")
        kwargs[key] = value
    interval = timedelta(**kwargs)
    if interval.total_seconds() <= 0:
        raise ValueError("schedule_config must describe a positive interval")
    return interval


def require_command(input_params: dict | None) -> None:
    if not isinstance(input_params, dict) or not str(input_params.get("command", "")).strip():
        raise ValueError("input_params.command is required")
