from __future__ import annotations

from fastapi import APIRouter

from src.agent_smith.services.sync import AgentSmithSyncService

router = APIRouter()


@router.post("/sync")
async def run_sync():
    return await AgentSmithSyncService().sync_all()


@router.post("/unsync")
async def run_unsync():
    removed = await AgentSmithSyncService().unsync_all()
    return {"success": True, "removed": removed}


@router.post("/sync/{item_type}/{item_id}")
async def sync_single_item(item_type: str, item_id: int):
    message = await AgentSmithSyncService().sync_item(item_type=item_type, item_id=item_id)
    return {"success": not message.startswith("Not found:"), "stdout": message, "stderr": ""}
