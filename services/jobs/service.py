"""Service-layer helpers for background jobs (the management boundary).

Creating a job here also creates a default '*'/'*' config so the job runs
everywhere by default — mirroring the harness convention where creating an item
also creates a default deployment config. Callers narrow scope afterward. The
underlying model (``services.jobs.models.job.create_job``) stays pure and does
not create configs on its own.

Both inserts run in a single transaction so a job can never be committed without
its default config (which would leave it unschedulable forever).
"""
from __future__ import annotations

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


def create_job_with_default_config(
    name: str,
    schedule_config: dict,
    input_params: dict | None = None,
    description: str | None = None,
) -> int:
    with get_connection() as conn:
        job_id = BackgroundJobModel.create(
            name=name,
            schedule_config=schedule_config,
            input_params=input_params or {},
            description=description,
            conn=conn,
        )
        JobConfigModel.create(job_id=job_id, device="*", repo="*", enabled=True, exclude=False, conn=conn)
    return job_id
