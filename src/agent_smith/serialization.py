from __future__ import annotations

from datetime import date, datetime
from typing import Any


def serialize_value(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, list):
        return [serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: serialize_value(item) for key, item in value.items()}
    return value


def model_to_dict(model, *, fields: list[str] | tuple[str, ...] | None = None) -> dict:
    names = fields or [column.name for column in model.__table__.columns]
    return {name: serialize_value(getattr(model, name)) for name in names}


def sort_optional_list(value: list[str] | None) -> list[str] | None:
    return sorted(value) if value is not None else None


def normalize_harness_row(row: dict) -> dict:
    if row.get("agents") is not None:
        row["agents"] = sorted(row["agents"])
    if row.get("subagents") is not None:
        row["subagents"] = sorted(row["subagents"])
    return row


def content_metadata(item: dict) -> dict:
    return item.get("content", {}).get("metadata", {})
