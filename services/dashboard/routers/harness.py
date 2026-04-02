from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from scripts.shared.validation import (
    MAX_NAME_LENGTH, validate_item_name, validate_repo_format, validate_agents_list,
)
from services.config import ALL_AGENTS
from services.db.harness import (
    VALID_TABLES,
    list_items, list_items_full, get_item_by_id,
    create_item, update_content, update_metadata, get_version_history,
    reorder_items, content_metadata, delete_item,
    create_config, update_config, delete_config, list_configs,
)
from services.dashboard.routers.base import require_found, list_response, delete_response, empty_to_none

router = APIRouter()

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _validate_type(item_type: str) -> None:
    if item_type not in VALID_TABLES:
        raise HTTPException(400, f"Invalid type: {item_type}. Must be one of {set(VALID_TABLES)}.")


@router.get("/rules")
def get_rules(project: str = Query(""), agent: str = Query("")):
    rows = list_items("rule", project=empty_to_none(project), agent=empty_to_none(agent))
    return [{"name": r["name"], "content": r["content"]["body"]} for r in rows]


@router.get("/skills")
def get_skills(project: str = Query(""), agent: str = Query("")):
    rows = list_items("skill", project=empty_to_none(project), agent=empty_to_none(agent))
    result = []
    for r in rows:
        meta = content_metadata(r)
        files = sorted(meta.get("files", {}).keys())
        result.append({"name": r["name"], "content": r["content"]["body"], "files": files})
    return result


@router.get("/mcp")
def get_mcp(project: str = Query(""), agent: str = Query("")):
    rows = list_items("tool", project=empty_to_none(project), agent=empty_to_none(agent))
    return [{"name": r["name"], "config": content_metadata(r)} for r in rows]


@router.get("/hooks")
def get_hooks(project: str = Query(""), agent: str = Query("")):
    rows = list_items("hook", project=empty_to_none(project), agent=empty_to_none(agent))
    return [{"name": r["name"], "config": content_metadata(r)} for r in rows]


@router.get("/agents")
def get_agents(project: str = Query(""), agent: str = Query("")):
    rows = list_items("agent", project=empty_to_none(project), agent=empty_to_none(agent))
    return [{"name": r["name"], "description": content_metadata(r).get("description", "")} for r in rows]


@router.get("/items/{item_type}")
def list_harness(
    item_type: str,
    project: str = Query(""),
    agent: str = Query(""),
    name: str = Query(""),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    _validate_type(item_type)
    all_items = list_items_full(item_type, project=empty_to_none(project), agent=empty_to_none(agent))
    if name:
        name_lower = name.lower()
        all_items = [i for i in all_items if name_lower in i["name"].lower()]
    total = len(all_items)
    items = all_items[offset:offset + limit]
    for item in items:
        item["configs"] = list_configs(item["id"], item_type)
    return list_response(items, total)


class ReorderRequest(BaseModel):
    ids: list[int]

    @field_validator("ids")
    @classmethod
    def ids_must_be_valid(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("ids must not be empty")
        if any(i <= 0 for i in v):
            raise ValueError("all ids must be positive")
        return v


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
    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    content: dict
    project: str | None = None
    agents: list[str] = []
    sort_key: int | None = None
    enabled: bool = True
    device: str = "*"
    repo: str = "*"

    @field_validator("name")
    @classmethod
    def name_must_be_valid(cls, v: str) -> str:
        return validate_item_name(v)

    @field_validator("content")
    @classmethod
    def content_must_have_body(cls, v: dict) -> dict:
        if "body" not in v or not isinstance(v["body"], str):
            raise ValueError("content must have a 'body' key with a string value")
        return v

    @field_validator("agents")
    @classmethod
    def agents_must_be_known(cls, v: list[str]) -> list[str]:
        return validate_agents_list(v, ALL_AGENTS)

    @field_validator("repo")
    @classmethod
    def repo_must_be_valid(cls, v: str) -> str:
        return validate_repo_format(v)


@router.post("/items/{item_type}", status_code=201)
def create_harness(item_type: str, body: CreateRequest):
    _validate_type(item_type)
    try:
        item_id = create_item(
            item_type, body.name, body.content,
            project=body.project, agents=body.agents,
            sort_key=body.sort_key, enabled=body.enabled,
        )
        if body.device != "*" or body.repo != "*":
            configs = list_configs(item_id, item_type)
            if configs:
                update_config(configs[0]["id"], device=body.device, repo=body.repo)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(409, str(e)) from e
    return get_item_by_id(item_type, item_id)


class ContentUpdate(BaseModel):
    content: dict

    @field_validator("content")
    @classmethod
    def content_must_have_body(cls, v: dict) -> dict:
        if "body" not in v or not isinstance(v["body"], str):
            raise ValueError("content must have a 'body' key with a string value")
        return v


@router.put("/items/{item_type}/{item_id}/content")
def update_harness_content(item_type: str, item_id: int, body: ContentUpdate):
    _validate_type(item_type)
    new_id = update_content(item_type, item_id, body.content)
    return require_found(get_item_by_id(item_type, new_id), item_type, new_id)


class MetadataUpdate(BaseModel):
    enabled: bool | None = None
    agents: list[str] | None = None
    name: str | None = Field(None, min_length=1, max_length=MAX_NAME_LENGTH)
    sort_key: int | None = None
    project: str | None = None
    clone_as_skill: bool | None = None

    @field_validator("name")
    @classmethod
    def name_must_be_valid(cls, v: str | None) -> str | None:
        if v is not None:
            validate_item_name(v)
        return v

    @field_validator("agents")
    @classmethod
    def agents_must_be_known(cls, v: list[str] | None) -> list[str] | None:
        if v is not None:
            validate_agents_list(v, ALL_AGENTS)
        return v


@router.patch("/items/{item_type}/{item_id}")
def patch_harness_metadata(item_type: str, item_id: int, body: MetadataUpdate):
    _validate_type(item_type)
    if body.clone_as_skill is not None and item_type != "rule":
        raise HTTPException(422, "clone_as_skill only applies to rules")
    update_metadata(
        item_type, item_id,
        enabled=body.enabled, agents=body.agents,
        name=body.name, sort_key=body.sort_key,
        project=body.project if body.project is not None else "UNSET",
        clone_as_skill=body.clone_as_skill,
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
    delete_item(item_type, item_id)
    return delete_response(item_id)


class ConfigCreate(BaseModel):
    device: str = "*"
    repo: str = "*"
    agents: list[str] = ["claude", "codex", "gemini"]
    subagents: list[str] = []
    enabled: bool = True
    exclude: bool = False

    @field_validator("repo")
    @classmethod
    def repo_must_be_valid(cls, v: str) -> str:
        return validate_repo_format(v)

    @field_validator("agents")
    @classmethod
    def agents_must_be_known(cls, v: list[str]) -> list[str]:
        return validate_agents_list(v, ALL_AGENTS)


class ConfigUpdate(BaseModel):
    device: str | None = None
    repo: str | None = None
    agents: list[str] | None = None
    subagents: list[str] | None = None
    enabled: bool | None = None
    exclude: bool | None = None

    @field_validator("repo")
    @classmethod
    def repo_must_be_valid(cls, v: str | None) -> str | None:
        if v is not None:
            validate_repo_format(v)
        return v

    @field_validator("agents")
    @classmethod
    def agents_must_be_known(cls, v: list[str] | None) -> list[str] | None:
        if v is not None:
            validate_agents_list(v, ALL_AGENTS)
        return v


@router.post("/items/{item_type}/{item_id}/configs", status_code=201)
def add_config(item_type: str, item_id: int, body: ConfigCreate):
    _validate_type(item_type)
    require_found(get_item_by_id(item_type, item_id), item_type, item_id)
    config_id = create_config(
        item_id, item_type,
        device=body.device, repo=body.repo,
        agents=body.agents, subagents=body.subagents,
        enabled=body.enabled, exclude=body.exclude,
    )
    return {"id": config_id, "item_id": item_id, "item_type": item_type}


@router.patch("/items/{item_type}/{item_id}/configs/{config_id}")
def patch_config(item_type: str, item_id: int, config_id: int, body: ConfigUpdate):
    _validate_type(item_type)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(422, "No fields to update")
    update_config(config_id, **fields)
    return list_configs(item_id, item_type)


@router.delete("/items/{item_type}/{item_id}/configs/{config_id}")
def remove_config(item_type: str, item_id: int, config_id: int):
    _validate_type(item_type)
    delete_config(config_id)
    return {"deleted": config_id}


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
