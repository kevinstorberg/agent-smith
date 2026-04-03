from __future__ import annotations

import os
import re

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

MAX_NAME_LENGTH = 40
MAX_TITLE_LENGTH = 200
MAX_BODY_LENGTH = 100_000

def assert_not_empty(value: str, field: str) -> None:
    assert value, f"{field} must not be empty."


def validate_memory_id(id: str) -> None:
    if not _UUID_RE.match(id):
        raise ValueError(f"Invalid memory ID format: {id}")


def require_env(name: str, hint: str = "") -> str:
    value = os.environ.get(name, "")
    if not value:
        msg = f"{name} is required. Set it in your environment."
        if hint:
            msg += f"\n{hint}"
        raise SystemExit(msg)
    return value


def validate_postgres_url(url: str, label: str = "DATABASE_URL") -> None:
    if not url.startswith(("postgresql://", "postgres://")):
        raise ValueError(f"{label} must be a postgresql:// URL, got: {url[:20]}...")


def empty_to_none(value: str) -> str | None:
    return value or None


def validate_item_name(name: str) -> str:
    if not _NAME_RE.match(name):
        raise ValueError(
            "name must start with a lowercase letter and contain only "
            "lowercase letters, digits, and underscores (e.g. 'my_rule')"
        )
    return name


def validate_repo_format(repo: str) -> str:
    if repo != "*" and not repo.startswith("/"):
        raise ValueError("repo must be '*' or an absolute path")
    return repo


def validate_agents_list(agents: list[str], allowed: list[str]) -> list[str]:
    invalid = set(agents) - set(allowed)
    if invalid:
        raise ValueError(f"Invalid agents: {invalid}. Must be from {allowed}")
    return agents


def extract_memory_metadata(row: dict) -> dict:
    meta = row.get("metadata", {})
    return {
        "repo": meta.get("repo", ""),
        "tags": meta.get("tags", "[]"),
        "created_at": meta.get("created_at", ""),
        "updated_at": meta.get("updated_at", ""),
        "last_accessed_at": str(meta.get("last_accessed_at", "")),
    }
