"""Graph job kind: validate_input_params + in-process graph execution (tracer bullet 4)."""
from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from services.api.routers.jobs import JobCreateRequest, create
from services.jobs.models.execution import list_executions_for_job
from services.jobs.models.job import create_job
from services.jobs.scheduler import execute_job
from services.jobs.service import validate_input_params
from tests.conftest import jobs_cleanup

_clean = jobs_cleanup("JOBTEST %")

ECHO_PARAMS = {"graph_type": "echo", "graph_inputs": {"text": "graph-job-hello"}}


def test_validate_accepts_command_only():
    validate_input_params({"command": "echo hi"})


def test_validate_accepts_known_graph_with_valid_inputs():
    validate_input_params(ECHO_PARAMS)


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {},
        {"command": "echo hi", "graph_type": "echo"},
        {"graph_type": "echo", "graph_inputs": "not-a-dict"},
        {"graph_type": "echo", "graph_inputs": {}},  # missing required 'text'
        {"graph_type": "echo", "graph_inputs": {"text": 42}},  # wrong type
        {"graph_type": "no_such_graph", "graph_inputs": {}},
        {"command": 42},
    ],
)
def test_validate_rejects_bad_shapes(bad):
    with pytest.raises(ValueError):
        validate_input_params(bad)


def test_rest_create_accepts_graph_job():
    job = create(
        JobCreateRequest(
            name="JOBTEST Graph Create",
            schedule_config={"hours": 4},
            input_params=ECHO_PARAMS,
        )
    )
    assert job["input_params"]["graph_type"] == "echo"


def test_rest_create_rejects_unknown_graph():
    with pytest.raises(ValidationError):
        JobCreateRequest(
            name="JOBTEST Graph Bad",
            schedule_config={"hours": 4},
            input_params={"graph_type": "no_such_graph", "graph_inputs": {}},
        )


@pytest.mark.asyncio
async def test_execute_graph_job_records_success():
    job_id = create_job(
        name="JOBTEST Graph Success",
        schedule_config={"hours": 1},
        input_params=ECHO_PARAMS,
    )

    result = await execute_job({"id": job_id, "input_params": ECHO_PARAMS})

    assert result["success"] is True
    assert result["output"] == "graph-job-hello"
    assert result["exit_code"] is None

    items, total = list_executions_for_job(job_id, limit=5)
    assert total == 1
    assert items[0]["status"] == "success"


@pytest.mark.asyncio
async def test_execute_graph_job_records_failure_for_unknown_graph():
    job_id = create_job(
        name="JOBTEST Graph Unknown",
        schedule_config={"hours": 1},
        input_params={"command": "echo placeholder"},
    )

    params = {"graph_type": "no_such_graph", "graph_inputs": {}}
    result = await execute_job({"id": job_id, "input_params": params})

    assert result["success"] is False
    assert "KeyError" in result["error"]
    items, _ = list_executions_for_job(job_id, limit=5)
    assert items[0]["status"] == "failed"


@pytest.mark.asyncio
async def test_execute_graph_job_times_out(monkeypatch):
    async def slow_dispatch(graph_type, inputs):
        await asyncio.sleep(5)

    import services.graphs.runtime as runtime

    monkeypatch.setattr(runtime, "dispatch", slow_dispatch)

    job_id = create_job(
        name="JOBTEST Graph Timeout",
        schedule_config={"hours": 1},
        input_params={"command": "echo placeholder"},
    )

    params = {**ECHO_PARAMS, "timeout": 0.05}
    result = await execute_job({"id": job_id, "input_params": params})

    assert result["success"] is False
    assert "timed out" in result["error"]
    items, _ = list_executions_for_job(job_id, limit=5)
    assert items[0]["status"] == "timeout"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [{}, {"command": "echo hi", "graph_type": "echo"}],
)
async def test_execute_job_fails_legacy_malformed_params(params):
    job_id = create_job(
        name=f"JOBTEST Graph Malformed {len(params)}",
        schedule_config={"hours": 1},
        input_params={"command": "echo placeholder"},
    )

    result = await execute_job({"id": job_id, "input_params": params})

    assert result["success"] is False
    assert "exactly one of" in result["error"]
    items, _ = list_executions_for_job(job_id, limit=5)
    assert items[0]["status"] == "failed"


def test_dispatch_validate_inputs_extraction_round_trips():
    """validate_inputs is shared with dispatch; the echo graph still round-trips."""
    from services.graphs.runtime import dispatch

    out = asyncio.run(dispatch("echo", {"text": "still-works"}))
    assert out == "still-works"
