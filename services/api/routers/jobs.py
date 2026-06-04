from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, field_validator

from services.jobs.models.config import create_config, delete_config, list_configs, update_config
from services.jobs.models.execution import get_execution, list_executions_for_job
from services.jobs.models.job import delete_job, get_job, list_jobs, update_job
from services.jobs.schedule import parse_interval
from services.jobs.scheduler import execute_job
from services.jobs.service import create_job_with_default_config
from services.api.routers.base import (
    delete_response,
    list_response,
    require_found,
    update_fields,
)

router = APIRouter()


def _job_detail(job_id: int) -> dict:
    job = require_found(get_job(job_id), "Job", job_id)
    job["configs"] = list_configs(job_id)
    return job


@router.get("")
def list_all(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    items, total = list_jobs(limit=limit, offset=offset)
    return list_response(items, total)


@router.get("/{job_id}")
def get_one(job_id: int):
    return _job_detail(job_id)


class JobCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    schedule_config: dict
    input_params: dict = Field(default_factory=dict)
    description: str | None = None

    @field_validator("schedule_config")
    @classmethod
    def _valid_schedule(cls, value):
        parse_interval(value)  # raises ValueError -> 422
        return value


@router.post("", status_code=201)
def create(body: JobCreateRequest):
    job_id = create_job_with_default_config(
        body.name, body.schedule_config, body.input_params, body.description
    )
    return _job_detail(job_id)


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


@router.put("/{job_id}")
def update(job_id: int, body: JobUpdateRequest):
    require_found(get_job(job_id), "Job", job_id)
    update_job(
        job_id,
        name=body.name,
        schedule_config=body.schedule_config,
        input_params=body.input_params,
        description=body.description,
    )
    return _job_detail(job_id)


@router.delete("/{job_id}")
def delete(job_id: int):
    require_found(get_job(job_id), "Job", job_id)
    delete_job(job_id)
    return delete_response(job_id)


@router.post("/{job_id}/run-now")
async def run_now(job_id: int):
    job = require_found(get_job(job_id), "Job", job_id)
    return await execute_job(job)


@router.get("/{job_id}/executions")
def executions(
    job_id: int,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    require_found(get_job(job_id), "Job", job_id)
    items, total = list_executions_for_job(job_id, limit=limit, offset=offset)
    return list_response(items, total)


@router.get("/{job_id}/executions/{execution_id}")
def execution_one(job_id: int, execution_id: int):
    return require_found(get_execution(execution_id), "Execution", execution_id)


class ConfigCreateRequest(BaseModel):
    device: str = "*"
    repo: str = "*"
    enabled: bool = True
    exclude: bool = False


@router.post("/{job_id}/configs", status_code=201)
def add_config(job_id: int, body: ConfigCreateRequest):
    require_found(get_job(job_id), "Job", job_id)
    create_config(
        job_id=job_id,
        device=body.device,
        repo=body.repo,
        enabled=body.enabled,
        exclude=body.exclude,
    )
    return list_configs(job_id)


class ConfigUpdateRequest(BaseModel):
    device: str | None = None
    repo: str | None = None
    enabled: bool | None = None
    exclude: bool | None = None


@router.patch("/{job_id}/configs/{config_id}")
def patch_config(job_id: int, config_id: int, body: ConfigUpdateRequest):
    update_config(config_id, **update_fields(body))
    return list_configs(job_id)


@router.delete("/{job_id}/configs/{config_id}")
def remove_config(job_id: int, config_id: int):
    delete_config(config_id)
    return delete_response(config_id)
