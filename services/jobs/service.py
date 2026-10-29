"""Service-layer helpers for background jobs (the management boundary).

Creating a job here also creates one deployment config, defaulting to '*'/'*'
so the job runs everywhere. Callers can select the initial device scope without
exposing a globally scheduled job between separate requests. The
underlying model (``services.jobs.models.job.create_job``) stays pure and does
not create configs on its own.

Both inserts run in a single transaction so a job can never be committed without
its default config (which would leave it unschedulable forever).
"""
from __future__ import annotations

import math

from services.db import get_connection
from services.jobs.models.config import JobConfigModel
from services.jobs.models.job import BackgroundJobModel


def validate_input_params(input_params: dict | None) -> None:
    """A job runs exactly one of: a shell command or an in-process graph.

    Shapes:
      - ``{"command": "<shell>", ...}``
      - ``{"graph_type": "<graph>", "graph_inputs": {...}}``

    Graph inputs are checked against the graph's INPUT_SCHEMA here so a bad
    graph job fails at creation time, never at its first scheduled run.
    Raises ValueError (which the REST layer surfaces as 422).
    """
    params = input_params or {}
    command = params.get("command")
    graph_type = params.get("graph_type")

    if bool(command) == bool(graph_type):
        raise ValueError("input_params requires exactly one of 'command' or 'graph_type'")
    if command:
        if not isinstance(command, str):
            raise ValueError("input_params.command must be a string")
        return

    if not isinstance(graph_type, str):
        raise ValueError("input_params.graph_type must be a string")
    graph_inputs = params.get("graph_inputs", {})
    if not isinstance(graph_inputs, dict):
        raise ValueError("input_params.graph_inputs must be an object")

    # Lazy import: services.jobs must stay importable without the graphs stack.
    from services.graphs.runtime import validate_inputs

    try:
        validate_inputs(graph_type, graph_inputs)
    except KeyError as exc:
        raise ValueError(exc.args[0]) from exc
    if graph_type == "persona" or (graph_type == "meeting_ingest" and graph_inputs.get("digest", True)):
        from services.config import JOB_DEFAULT_TIMEOUT
        from services.meetings.enrichment import JOB_TIMEOUT_SECONDS

        timeout = params.get("timeout", JOB_DEFAULT_TIMEOUT)
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or timeout < JOB_TIMEOUT_SECONDS):
            raise ValueError(f"Meeting digestion and persona jobs require a timeout of at least {JOB_TIMEOUT_SECONDS} seconds")


def execution_timeout(graph_type: str, params: dict) -> float:
    from services.config import JOB_DEFAULT_TIMEOUT
    from services.meetings.processing import JOB_TIMEOUT_SECONDS

    timeout = float(params.get("timeout", JOB_DEFAULT_TIMEOUT))
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Job timeout must be a finite positive number")
    if graph_type == "persona" or (graph_type == "meeting_ingest" and (params.get("graph_inputs") or {}).get("digest", True)):
        return max(timeout, JOB_TIMEOUT_SECONDS)
    return timeout


def has_requested_work(job: dict) -> bool:
    params = job.get("input_params") or {}
    graph_type, inputs = params.get("graph_type"), params.get("graph_inputs") or {}
    from services.meetings import digestion_db

    if graph_type == "persona":
        from services.personas.factory import build_context_provider

        return build_context_provider().has_requested_work(source=inputs.get("source"))
    if graph_type == "meeting_ingest":
        from services.meetings.digestion import configured_sources

        return digestion_db.has_requested_work(list(configured_sources(inputs.get("source"))), digest=inputs.get("digest", True))
    return False


def create_job_with_default_config(
    name: str,
    schedule_config: dict,
    input_params: dict | None = None,
    description: str | None = None,
    *,
    device: str = "*",
) -> int:
    if not isinstance(device, str) or not 1 <= len(device.strip()) <= 100:
        raise ValueError("Job device must be a nonblank string of at most 100 characters")
    device = device.strip()
    with get_connection() as conn:
        job_id = BackgroundJobModel.create(
            name=name,
            schedule_config=schedule_config,
            input_params=input_params or {},
            description=description,
            conn=conn,
        )
        JobConfigModel.create(job_id=job_id, device=device, repo="*", enabled=True, exclude=False, conn=conn)
    return job_id
