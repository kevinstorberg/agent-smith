from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/sync")
def run_sync():
    from scripts.shared.sync_utils import run_sync_script
    try:
        return run_sync_script()
    except FileNotFoundError as e:
        raise HTTPException(500, str(e))


@router.post("/unsync")
def run_unsync():
    from scripts.shared.agents import unsync_all
    removed = unsync_all()
    return {"success": True, "removed": removed}


@router.post("/sync/{item_type}/{item_id}")
def sync_single_item(item_type: str, item_id: int):
    from services.api.models.shared.harness import VALID_ITEM_TYPES
    from scripts.shared.sync_utils import run_sync_script

    if item_type not in VALID_ITEM_TYPES:
        raise HTTPException(400, f"Invalid item_type. Must be one of: {', '.join(VALID_ITEM_TYPES)}")

    try:
        return run_sync_script(["--item-type", item_type, "--item-id", str(item_id)])
    except FileNotFoundError as e:
        raise HTTPException(500, str(e))
