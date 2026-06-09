from __future__ import annotations

from fastapi import HTTPException


def empty_to_none(value: str | None) -> str | None:
    return value or None


def require_found(item, label: str = "Item", item_id: int | str = ""):
    if not item:
        detail = f"{label} not found" + (f": {item_id}" if item_id else "")
        raise HTTPException(status_code=404, detail=detail)
    return item


def list_response(items: list, total: int) -> dict:
    return {"items": items, "total": total}


def delete_response(item_id: int | str) -> dict:
    return {"deleted": True, "id": item_id}


def update_fields(body) -> dict:
    return {key: value for key, value in body.model_dump().items() if value is not None}


def paginate(items: list, offset: int, limit: int) -> tuple[list, int]:
    return items[offset : offset + limit], len(items)


def resolve_project(value: str | None) -> str | None:
    return value if value is not None else "UNSET"
