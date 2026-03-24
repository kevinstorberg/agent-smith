from __future__ import annotations

import os
import re

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)

MEMORY_METADATA_FIELDS = ("repo", "tags", "created_at", "updated_at", "last_accessed_at")


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


def extract_memory_metadata(row: dict) -> dict:
    """Extract the standard metadata fields from a LanceDB row for migration."""
    meta = row.get("metadata", {})
    return {
        "repo": meta.get("repo", ""),
        "tags": meta.get("tags", "[]"),
        "created_at": meta.get("created_at", ""),
        "updated_at": meta.get("updated_at", ""),
        "last_accessed_at": str(meta.get("last_accessed_at", "")),
    }
