from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from services.db.harness import (
    VALID_TABLES,
    list_items, list_items_full, get_item_by_id,
    create_item, update_content, update_metadata, get_version_history,
    reorder_items, content_metadata,
)
from services.dashboard.routers.base import require_found

router = APIRouter()

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _validate_type(item_type: str) -> None:
    if item_type not in VALID_TABLES:
        raise HTTPException(400, f"Invalid type: {item_type}. Must be one of {set(VALID_TABLES)}.")


@router.get("/rules")
def get_rules(project: str = Query(""), agent: str = Query("")):
    rows = list_items("rule", project=project or None, agent=agent or None)
    return [{"name": r["name"], "content": r["content"]["body"]} for r in rows]


@router.get("/skills")
def get_skills(project: str = Query(""), agent: str = Query("")):
    rows = list_items("skill", project=project or None, agent=agent or None)
    result = []
    for r in rows:
        meta = content_metadata(r)
        files = sorted(meta.get("files", {}).keys())
        result.append({"name": r["name"], "content": r["content"]["body"], "files": files})
    return result


@router.get("/mcp")
def get_mcp(project: str = Query(""), agent: str = Query("")):
    rows = list_items("tool", project=project or None, agent=agent or None)
    return [{"name": r["name"], "config": content_metadata(r)} for r in rows]


@router.get("/hooks")
def get_hooks(project: str = Query(""), agent: str = Query("")):
    rows = list_items("hook", project=project or None, agent=agent or None)
    return [{"name": r["name"], "config": content_metadata(r)} for r in rows]


@router.get("/items/{item_type}")
def list_harness(
    item_type: str,
    project: str = Query(""),
    agent: str = Query(""),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    _validate_type(item_type)
    all_items = list_items_full(item_type, project=project or None, agent=agent or None)
    total = len(all_items)
    items = all_items[offset:offset + limit]
    return {"items": items, "total": total}


class ReorderRequest(BaseModel):
    ids: list[int]


@router.put("/items/{item_type}/reorder")
def reorder_harness(item_type: str, body: ReorderRequest):
    _validate_type(item_type)
    reorder_items(item_type, body.ids)
    return {"reordered": True, "count": len(body.ids)}


@router.get("/items/{item_type}/{item_id}")
def get_harness(item_type: str, item_id: int):
    _validate_type(item_type)
    return require_found(get_item_by_id(item_type, item_id), item_type, item_id)


class CreateRequest(BaseModel):
    name: str
    content: dict
    project: str | None = None
    agents: list[str] = []
    sort_key: str | None = None
    enabled: bool = True


@router.post("/items/{item_type}", status_code=201)
def create_harness(item_type: str, body: CreateRequest):
    _validate_type(item_type)
    try:
        item_id = create_item(
            item_type, body.name, body.content,
            project=body.project, agents=body.agents,
            sort_key=body.sort_key, enabled=body.enabled,
        )
    except Exception as e:
        raise HTTPException(409, str(e)) from e
    return get_item_by_id(item_type, item_id)


class ContentUpdate(BaseModel):
    content: dict


@router.put("/items/{item_type}/{item_id}/content")
def update_harness_content(item_type: str, item_id: int, body: ContentUpdate):
    _validate_type(item_type)
    require_found(get_item_by_id(item_type, item_id), item_type, item_id)
    new_id = update_content(item_type, item_id, body.content)
    return get_item_by_id(item_type, new_id)


class MetadataUpdate(BaseModel):
    enabled: bool | None = None
    agents: list[str] | None = None
    name: str | None = None
    sort_key: str | None = None
    project: str | None = None


@router.patch("/items/{item_type}/{item_id}")
def patch_harness_metadata(item_type: str, item_id: int, body: MetadataUpdate):
    _validate_type(item_type)
    require_found(get_item_by_id(item_type, item_id), item_type, item_id)
    update_metadata(
        item_type, item_id,
        enabled=body.enabled, agents=body.agents,
        name=body.name, sort_key=body.sort_key,
        project=body.project if body.project is not None else "UNSET",
    )
    return get_item_by_id(item_type, item_id)


@router.get("/items/{item_type}/{item_id}/history")
def get_harness_history(item_type: str, item_id: int):
    _validate_type(item_type)
    item = require_found(get_item_by_id(item_type, item_id), item_type, item_id)
    return get_version_history(item_type, item["name"], project=item.get("project"))


@router.delete("/items/{item_type}/{item_id}")
def delete_harness(item_type: str, item_id: int):
    _validate_type(item_type)
    require_found(get_item_by_id(item_type, item_id), item_type, item_id)
    update_metadata(item_type, item_id, enabled=False)
    return {"deleted": True, "id": item_id}


@router.post("/sync")
def run_sync():
    sync_script = _REPO_ROOT / "sync.py"
    if not sync_script.exists():
        raise HTTPException(500, f"sync.py not found at {sync_script}")
    result = subprocess.run(
        [sys.executable, str(sync_script)],
        capture_output=True, text=True, cwd=str(_REPO_ROOT), timeout=60,
    )
    return {
        "success": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


@router.post("/unsync")
def run_unsync():
    from scripts.shared.agents import unsync_all
    removed = unsync_all()
    return {"success": True, "removed": removed}
