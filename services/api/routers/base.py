from __future__ import annotations

from collections.abc import Callable
from typing import ParamSpec, TypeVar
from fastapi import HTTPException

P = ParamSpec("P")
R = TypeVar("R")


def query_result(operation: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
    try:
        return operation(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


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
    return {k: v for k, v in body.model_dump().items() if v is not None}


def paginate(items: list, offset: int, limit: int) -> tuple[list, int]:
    return items[offset:offset + limit], len(items)


def resolve_project(value: str | None) -> str:
    return value if value is not None else "UNSET"


from scripts.shared.validation import empty_to_none  # noqa: F401
