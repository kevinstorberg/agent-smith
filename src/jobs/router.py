from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from src.api.errors import APIException
from src.jobs.runtime import JobRuntime
from src.jobs.stores import JobRunRecord
from src.policies.base import Permission
from src.policies.dependencies import require_permission


class ManualJobRunResponse(BaseModel):
    run: dict[str, Any]


class JobRunsResponse(BaseModel):
    runs: list[dict[str, Any]]


class JobListResponse(BaseModel):
    jobs: list[dict[str, Any]]


class JobHealthResponse(BaseModel):
    health: dict[str, Any]


class RunJobRequest(BaseModel):
    source: str = Field(default="manual", min_length=1, max_length=64)


def create_jobs_router() -> APIRouter:
    router = APIRouter(
        prefix="/jobs",
        tags=["jobs"],
        dependencies=[Depends(require_permission(Permission.ADMIN))],
    )

    @router.get("/health", response_model=JobHealthResponse)
    async def job_health(request: Request) -> JobHealthResponse:
        return JobHealthResponse(health=_runtime_from_request(request).health())

    @router.get("", response_model=JobListResponse)
    async def list_jobs(request: Request) -> JobListResponse:
        return JobListResponse(jobs=_runtime_from_request(request).list_jobs())

    @router.get("/{job_name}/runs", response_model=JobRunsResponse)
    async def list_job_runs(
        request: Request,
        job_name: str,
        limit: int = Query(default=50, gt=0, le=500),
    ) -> JobRunsResponse:
        runtime = _runtime_from_request(request)
        if job_name not in runtime.definitions:
            raise APIException(
                status_code=404,
                code="job_not_found",
                message=f"Unknown job: {job_name}",
            )
        runs = await runtime.list_runs(job_name, limit=limit)
        return JobRunsResponse(runs=[_serialize_run(run) for run in runs])

    @router.post("/{job_name}/run", response_model=ManualJobRunResponse)
    async def run_job(request: Request, job_name: str, payload: RunJobRequest | None = None) -> ManualJobRunResponse:
        runtime = _runtime_from_request(request)
        try:
            run = await runtime.run_job(job_name, source=(payload.source if payload else "manual"))
        except KeyError:
            raise APIException(
                status_code=404,
                code="job_not_found",
                message=f"Unknown job: {job_name}",
            )
        return ManualJobRunResponse(run=_serialize_run(run))

    return router


def _runtime_from_request(request: Request) -> JobRuntime:
    runtime = getattr(request.app.state, "job_runtime", None)
    if runtime is None:
        raise APIException(
            status_code=503,
            code="job_runtime_unavailable",
            message="Job runtime is not available",
        )
    return runtime


def _serialize_run(run: JobRunRecord) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "job_name": run.job_name,
        "status": run.status.value,
        "source": run.source,
        "attempt": run.attempt,
        "max_attempts": run.max_attempts,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_ms": run.duration_ms,
        "error": run.error,
    }
