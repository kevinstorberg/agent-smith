"""Shared validation utilities."""

from __future__ import annotations

import re

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


def validate_memory_id(id: str) -> None:
    """Raise ValueError if id is not a valid UUID v4 string."""
    if not _UUID_RE.match(id):
        raise ValueError(f"Invalid memory ID format: {id}")
