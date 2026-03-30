from __future__ import annotations

from fastapi import HTTPException


def require_found(item, label: str = "Item", item_id: int | str = ""):
    """Return item if truthy, raise 404 otherwise."""
    if not item:
        detail = f"{label} not found" + (f": {item_id}" if item_id else "")
        raise HTTPException(status_code=404, detail=detail)
    return item


def list_response(items: list, total: int) -> dict:
    return {"items": items, "total": total}
