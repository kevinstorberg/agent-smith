from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.shared.paths import bootstrap  # noqa: E402
bootstrap()

from mcp.server.fastmcp import FastMCP  # noqa: E402
from scripts.shared.validation import empty_to_none  # noqa: E402

mcp = FastMCP("jobs - manage background jobs, scheduling, and execution history")


@mcp.tool()
def job_create(
    name: str,
    schedule_config: dict,
    input_params: dict | None = None,
    description: str = "",
) -> dict:
    """Create a background job that runs a shell command or an in-process graph on a fixed interval.

    The job runs everywhere by default (a '*'/'*' config is created); narrow
    scope with job_add_config.

    Args:
        name: Unique job name.
        schedule_config: Interval dict, e.g. {"minutes": 5} or {"hours": 1}.
            Keys: seconds/minutes/hours/days, each a positive number.
        input_params: Execution params; exactly one of
            {"command": "<shell command>"} or
            {"graph_type": "<graph>", "graph_inputs": {...}} (runs a LangGraph
            workflow in-process; inputs are validated against the graph's schema).
        description: Optional human description.

    Returns:
        The created job record.
    """
    from services.jobs.models.job import get_job
    from services.jobs.service import create_job_with_default_config, validate_input_params

    validate_input_params(input_params)
    job_id = create_job_with_default_config(
        name, schedule_config, input_params or {}, empty_to_none(description)
    )
    return get_job(job_id)


@mcp.tool()
def job_list(limit: int = 50, offset: int = 0) -> dict:
    """List background jobs, newest-updated first.

    Returns:
        {"items": [...jobs...], "total": <int>}
    """
    from services.jobs.models.job import list_jobs

    items, total = list_jobs(limit=limit, offset=offset)
    return {"items": items, "total": total}


@mcp.tool()
def job_get(job_id: int) -> dict | None:
    """Get a single job with its device/repo configs attached."""
    from services.jobs.models.config import list_configs
    from services.jobs.models.job import get_job

    job = get_job(job_id)
    if job:
        job["configs"] = list_configs(job_id)
    return job


@mcp.tool()
def job_update(
    job_id: int,
    name: str = "",
    schedule_config: dict | None = None,
    input_params: dict | None = None,
    description: str = "",
) -> dict | None:
    """Update a job's name, schedule_config, input_params, or description.

    Only non-empty / provided fields are changed.
    """
    from services.jobs.models.job import update_job
    from services.jobs.service import validate_input_params

    if input_params is not None:
        validate_input_params(input_params)
    update_job(
        job_id,
        name=empty_to_none(name),
        schedule_config=schedule_config,
        input_params=input_params,
        description=empty_to_none(description),
    )
    return job_get(job_id)


@mcp.tool()
def job_delete(job_id: int) -> str:
    """Delete a job and (via cascade) all its configs and execution history."""
    from services.jobs.models.job import delete_job

    delete_job(job_id)
    return f"Job {job_id} deleted"


@mcp.tool()
async def job_run_now(job_id: int) -> dict:
    """Run a job immediately, ignoring its schedule and scoping.

    Returns the execution result {success, output, error, duration_seconds, exit_code}.
    """
    from services.jobs.models.job import get_job
    from services.jobs.scheduler import execute_job

    job = get_job(job_id)
    if not job:
        return {"error": f"job {job_id} not found"}
    return await execute_job(job)


@mcp.tool()
def job_list_executions(job_id: int, limit: int = 50, offset: int = 0) -> dict:
    """List a job's execution history, newest first."""
    from services.jobs.models.execution import list_executions_for_job

    items, total = list_executions_for_job(job_id, limit=limit, offset=offset)
    return {"items": items, "total": total}


@mcp.tool()
def job_add_config(
    job_id: int,
    device: str = "*",
    repo: str = "*",
    enabled: bool = True,
    exclude: bool = False,
) -> list[dict]:
    """Add a device/repo scoping config to a job. Returns all configs for the job."""
    from services.jobs.models.config import create_config, list_configs

    create_config(job_id=job_id, device=device, repo=repo, enabled=enabled, exclude=exclude)
    return list_configs(job_id)


@mcp.tool()
def job_update_config(
    config_id: int,
    device: str = "",
    repo: str = "",
    enabled: bool | None = None,
    exclude: bool | None = None,
) -> str:
    """Update a job config. Only provided / non-empty fields change."""
    from services.jobs.models.config import update_config

    update_config(
        config_id,
        device=empty_to_none(device),
        repo=empty_to_none(repo),
        enabled=enabled,
        exclude=exclude,
    )
    return f"Config {config_id} updated"


@mcp.tool()
def job_delete_config(config_id: int) -> str:
    """Delete a job config."""
    from services.jobs.models.config import delete_config

    delete_config(config_id)
    return f"Config {config_id} deleted"
