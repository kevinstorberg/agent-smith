import re
from collections.abc import Mapping
from typing import Any

SENSITIVE_COMPOSITES = (
    "access_key",
    "api_key",
    "database_url",
    "db_url",
)
SENSITIVE_SEGMENTS = {
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
    "uri",
    "url",
}
SEGMENT_PATTERN = re.compile(r"[^a-z0-9]+")
REDACTED = "[redacted]"


def redact_mapping(value: Mapping[str, Any], *, expose_values: bool = False) -> dict[str, Any]:
    if expose_values:
        return dict(value)
    return {key: redact_value(key, item) for key, item in value.items()}


def redact_value(key: str, value: Any) -> Any:
    if _is_sensitive_key(key):
        return REDACTED
    if isinstance(value, Mapping):
        return {child_key: redact_value(child_key, child_value) for child_key, child_value in value.items()}
    if isinstance(value, list):
        return [redact_value(key, item) for item in value]
    if isinstance(value, tuple):
        return [redact_value(key, item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower()
    if any(token in normalized for token in SENSITIVE_COMPOSITES):
        return True
    segments = {segment for segment in SEGMENT_PATTERN.split(normalized) if segment}
    return bool(segments & SENSITIVE_SEGMENTS)
