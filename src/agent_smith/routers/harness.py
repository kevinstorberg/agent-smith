from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from db.unit_of_work import UnitOfWork, get_unit_of_work
from src.agent_smith.constants import ALL_AGENTS
from src.agent_smith.responses import (
    delete_response,
    empty_to_none,
    list_response,
    require_found,
    resolve_project,
    update_fields,
)
from src.agent_smith.serialization import content_metadata
from src.agent_smith.services.harness import HarnessService
from src.agent_smith.validation import (
    MAX_NAME_LENGTH,
    validate_agents_list,
    validate_content,
    validate_item_name,
    validate_repo_format,
)

router = APIRouter()
service = HarnessService()


def _optional(fn):
    return lambda value: fn(value) if value is not None else value


class CreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    content: dict
    project: str | None = None
    agents: list[str] = Field(default_factory=list)
    sort_key: int | None = None
    enabled: bool = True
    device: str = "*"
    repo: str = "*"

    _val_name = field_validator("name")(validate_item_name)
    _val_content = field_validator("content")(validate_content)
    _val_agents = field_validator("agents")(lambda value: validate_agents_list(value, ALL_AGENTS))
    _val_repo = field_validator("repo")(validate_repo_format)


class ContentUpdate(BaseModel):
    content: dict

    _val_content = field_validator("content")(validate_content)


class MetadataUpdate(BaseModel):
    enabled: bool | None = None
    agents: list[str] | None = None
    name: str | None = Field(None, min_length=1, max_length=MAX_NAME_LENGTH)
    sort_key: int | None = None
    project: str | None = None
    clone_as_skill: bool | None = None

    _val_name = field_validator("name")(_optional(validate_item_name))
    _val_agents = field_validator("agents")(_optional(lambda value: validate_agents_list(value, ALL_AGENTS)))


class ReorderRequest(BaseModel):
    ids: list[int]

    @field_validator("ids")
    @classmethod
    def ids_must_be_valid(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError("ids must not be empty")
        if any(item_id <= 0 for item_id in value):
            raise ValueError("all ids must be positive")
        return value


class ConfigCreate(BaseModel):
    device: str = "*"
    repo: str = "*"
    agents: list[str] = Field(default_factory=lambda: list(ALL_AGENTS))
    subagents: list[str] = Field(default_factory=list)
    enabled: bool = True
    exclude: bool = False

    _val_repo = field_validator("repo")(validate_repo_format)
    _val_agents = field_validator("agents")(lambda value: validate_agents_list(value, ALL_AGENTS))


class ConfigUpdate(BaseModel):
    device: str | None = None
    repo: str | None = None
    agents: list[str] | None = None
    subagents: list[str] | None = None
    enabled: bool | None = None
    exclude: bool | None = None

    _val_repo = field_validator("repo")(_optional(validate_repo_format))
    _val_agents = field_validator("agents")(_optional(lambda value: validate_agents_list(value, ALL_AGENTS)))


def _format_convenience(item_type: str, row: dict) -> dict:
    metadata = content_metadata(row)
    if item_type == "rule":
        return {"name": row["name"], "content": row["content"]["body"]}
    if item_type == "skill":
        return {
            "name": row["name"],
            "content": row["content"]["body"],
            "files": sorted(metadata.get("files", {}).keys()),
        }
    if item_type == "tool":
        return {"name": row["name"], "config": metadata}
    if item_type == "hook":
        return {"name": row["name"], "config": metadata}
    if item_type == "agent":
        return {"name": row["name"], "description": metadata.get("description", "")}
    raise HTTPException(status_code=404, detail=f"Unknown harness item type: {item_type}")


def _register_item_routes(item_type: str, convenience_path: str) -> None:
    @router.get(convenience_path)
    async def convenience_list(
        uow: Annotated[UnitOfWork, Depends(get_unit_of_work)],
        project: str = Query(""),
        agent: str = Query(""),
    ):
        rows = await service.convenience_list(
            uow, item_type, project=empty_to_none(project), agent=empty_to_none(agent)
        )
        return [_format_convenience(item_type, row) for row in rows]

    @router.get(f"/items/{item_type}")
    async def list_items(
        uow: Annotated[UnitOfWork, Depends(get_unit_of_work)],
        project: str = Query(""),
        agent: str = Query(""),
        name: str = Query(""),
        limit: int = Query(10, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ):
        items, total = await service.list_page(
            uow,
            item_type,
            project=empty_to_none(project),
            agent=empty_to_none(agent),
            name=name,
            limit=limit,
            offset=offset,
        )
        return list_response(items, total)

    @router.put(f"/items/{item_type}/reorder")
    async def reorder(body: ReorderRequest, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]):
        await service.reorder_items(uow, item_type, body.ids)
        return {"reordered": True, "count": len(body.ids)}

    @router.get(f"/items/{item_type}/{{item_id}}")
    async def get_item(item_id: int, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]):
        return require_found(await service.get_item(uow, item_type, item_id), item_type, item_id)

    @router.post(f"/items/{item_type}", status_code=201)
    async def create_item(body: CreateRequest, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]):
        try:
            return await service.create_item(
                uow,
                item_type,
                name=body.name,
                content=body.content,
                project=body.project,
                agents=body.agents,
                sort_key=body.sort_key,
                enabled=body.enabled,
                device=body.device,
                repo_path=body.repo,
            )
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.put(f"/items/{item_type}/{{item_id}}/content")
    async def update_content(item_id: int, body: ContentUpdate, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]):
        return require_found(await service.update_content(uow, item_type, item_id, body.content), item_type, item_id)

    @router.patch(f"/items/{item_type}/{{item_id}}")
    async def patch_metadata(item_id: int, body: MetadataUpdate, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]):
        fields = update_fields(body)
        if "project" in fields:
            fields["project"] = resolve_project(body.project)
        return require_found(await service.update_metadata(uow, item_type, item_id, **fields), item_type, item_id)

    @router.get(f"/items/{item_type}/{{item_id}}/history")
    async def get_history(item_id: int, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]):
        item = require_found(await service.get_item(uow, item_type, item_id), item_type, item_id)
        return await service.history(uow, item_type, item["id"])

    @router.delete(f"/items/{item_type}/{{item_id}}")
    async def delete_item(item_id: int, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]):
        require_found(await service.get_item(uow, item_type, item_id), item_type, item_id)
        await service.delete_item(uow, item_type, item_id)
        return delete_response(item_id)

    @router.post(f"/items/{item_type}/{{item_id}}/configs", status_code=201)
    async def add_config(item_id: int, body: ConfigCreate, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]):
        require_found(await service.get_item(uow, item_type, item_id), item_type, item_id)
        config_id = await service.create_config(
            uow,
            item_id,
            item_type,
            device=body.device,
            repo=body.repo,
            agents=body.agents,
            subagents=body.subagents,
            enabled=body.enabled,
            exclude=body.exclude,
        )
        return {"id": config_id, "item_id": item_id, "item_type": item_type}

    @router.patch(f"/items/{item_type}/{{item_id}}/configs/{{config_id}}")
    async def patch_config(
        item_id: int, config_id: int, body: ConfigUpdate, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]
    ):
        fields = update_fields(body)
        if not fields:
            raise HTTPException(status_code=422, detail="No fields to update")
        await service.update_config(uow, config_id, **fields)
        return await service.list_configs(uow, item_id, item_type)

    @router.delete(f"/items/{item_type}/{{item_id}}/configs/{{config_id}}")
    async def remove_config(item_id: int, config_id: int, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]):
        await service.delete_config(uow, config_id)
        return {"deleted": config_id}


for _item_type, _path in {
    "rule": "/rules",
    "skill": "/skills",
    "tool": "/mcp",
    "hook": "/hooks",
    "agent": "/agents",
}.items():
    _register_item_routes(_item_type, _path)
