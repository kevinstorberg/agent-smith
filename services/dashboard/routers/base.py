from __future__ import annotations

from fastapi import HTTPException


def require_found(item, label: str = "Item", item_id: int | str = ""):
    if not item:
        detail = f"{label} not found" + (f": {item_id}" if item_id else "")
        raise HTTPException(status_code=404, detail=detail)
    return item


def list_response(items: list, total: int) -> dict:
    return {"items": items, "total": total}


def delete_response(item_id: int | str) -> dict:
    return {"deleted": True, "id": item_id}


from scripts.shared.validation import empty_to_none  # noqa: F401
