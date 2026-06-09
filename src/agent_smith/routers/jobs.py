from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from db.unit_of_work import UnitOfWork, get_unit_of_work
from src.agent_smith.responses import delete_response, list_response, require_found, update_fields
from src.agent_smith.services.jobs import JobService
from src.agent_smith.validation import parse_interval, require_command

router = APIRouter()
service = JobService()


class JobCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    schedule_config: dict
    input_params: dict
    description: str | None = None

    @field_validator("schedule_config")
    @classmethod
    def _valid_schedule(cls, value):
        parse_interval(value)
        return value

    @field_validator("input_params")
    @classmethod
    def _require_command(cls, value):
        require_command(value)
        return value


class JobUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1)
    schedule_config: dict | None = None
    input_params: dict | None = None
    description: str | None = None

    @field_validator("schedule_config")
    @classmethod
    def _valid_schedule(cls, value):
        if value is not None:
            parse_interval(value)
        return value

    @field_validator("input_params")
    @classmethod
    def _require_command(cls, value):
        if value is not None:
            require_command(value)
        return value


class ConfigCreateRequest(BaseModel):
    device: str = "*"
    repo: str = "*"
    enabled: bool = True
    exclude: bool = False


class ConfigUpdateRequest(BaseModel):
    device: str | None = None
    repo: str | None = None
    enabled: bool | None = None
    exclude: bool | None = None


@router.get("")
async def list_all(
    uow: Annotated[UnitOfWork, Depends(get_unit_of_work)],
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    items, total = await service.list_jobs(uow, limit=limit, offset=offset)
    return list_response(items, total)


@router.get("/{job_id}")
async def get_one(job_id: int, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]):
    return require_found(await service.get_job(uow, job_id, detail=True), "Job", job_id)


@router.post("", status_code=201)
async def create(body: JobCreateRequest, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]):
    try:
        return await service.create_job(uow, **body.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put("/{job_id}")
async def update(job_id: int, body: JobUpdateRequest, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]):
    require_found(await service.get_job(uow, job_id), "Job", job_id)
    try:
        return require_found(await service.update_job(uow, job_id, **update_fields(body)), "Job", job_id)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/{job_id}")
async def delete(job_id: int, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]):
    require_found(await service.get_job(uow, job_id), "Job", job_id)
    await service.delete_job(uow, job_id)
    return delete_response(job_id)


@router.post("/{job_id}/run-now")
async def run_now(job_id: int, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]):
    job = require_found(await service.get_job(uow, job_id, detail=True), "Job", job_id)
    return await service.run_now(job)


@router.get("/{job_id}/executions")
async def executions(
    job_id: int,
    uow: Annotated[UnitOfWork, Depends(get_unit_of_work)],
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    require_found(await service.get_job(uow, job_id), "Job", job_id)
    items, total = await service.list_executions(uow, job_id, limit=limit, offset=offset)
    return list_response(items, total)


@router.get("/{job_id}/executions/{execution_id}")
async def execution_one(job_id: int, execution_id: int, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]):
    return require_found(await service.get_execution(uow, execution_id), "Execution", execution_id)


@router.post("/{job_id}/configs", status_code=201)
async def add_config(job_id: int, body: ConfigCreateRequest, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]):
    require_found(await service.get_job(uow, job_id), "Job", job_id)
    return await service.create_config(uow, job_id, **body.model_dump())


async def _require_config_of_job(uow: UnitOfWork, job_id: int, config_id: int) -> dict:
    config = require_found(await service.get_config(uow, config_id), "Config", config_id)
    if config["job_id"] != job_id:
        raise HTTPException(status_code=404, detail=f"Config {config_id} does not belong to job {job_id}")
    return config


@router.patch("/{job_id}/configs/{config_id}")
async def patch_config(
    job_id: int, config_id: int, body: ConfigUpdateRequest, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]
):
    await _require_config_of_job(uow, job_id, config_id)
    await service.update_config(uow, config_id, **update_fields(body))
    return await service.list_configs(uow, job_id)


@router.delete("/{job_id}/configs/{config_id}")
async def remove_config(job_id: int, config_id: int, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]):
    await _require_config_of_job(uow, job_id, config_id)
    await service.delete_config(uow, config_id)
    return delete_response(config_id)
