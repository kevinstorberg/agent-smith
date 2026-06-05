"""Tests for the jobs MCP server tools (services/jobs/server.py)."""
from __future__ import annotations

import pytest

from services.jobs.server import (
    job_add_config,
    job_create,
    job_delete,
    job_delete_config,
    job_get,
    job_list,
    job_list_executions,
    job_run_now,
    job_update,
    job_update_config,
)
from tests.conftest import jobs_cleanup

_clean = jobs_cleanup("JOBTEST %")


def test_job_create_attaches_default_config():
    job = job_create(
        name="JOBTEST MCP Create",
        schedule_config={"minutes": 5},
        input_params={"command": "echo hi"},
    )
    full = job_get(job["id"])
    assert full["name"] == "JOBTEST MCP Create"
    assert len(full["configs"]) == 1
    assert full["configs"][0]["device"] == "*"


def test_job_create_requires_command():
    with pytest.raises(ValueError):
        job_create(name="JOBTEST MCP NoCmd", schedule_config={"minutes": 5}, input_params={})


def test_job_list_and_update_and_delete():
    job = job_create(
        name="JOBTEST MCP Lifecycle",
        schedule_config={"minutes": 5},
        input_params={"command": "echo x"},
    )
    listed = job_list(limit=50, offset=0)
    assert any(j["name"] == "JOBTEST MCP Lifecycle" for j in listed["items"])

    updated = job_update(job["id"], description="changed", schedule_config={"hours": 1})
    assert updated["description"] == "changed"
    assert updated["schedule_config"] == {"hours": 1}

    job_delete(job["id"])
    assert job_get(job["id"]) is None


@pytest.mark.asyncio
async def test_job_run_now_records_execution():
    job = job_create(
        name="JOBTEST MCP Run",
        schedule_config={"minutes": 5},
        input_params={"command": "echo mcp-run"},
    )
    result = await job_run_now(job["id"])
    assert result["success"] is True
    assert "mcp-run" in result["output"]

    executions = job_list_executions(job["id"], limit=5)
    assert executions["total"] == 1


def test_job_config_tools():
    job = job_create(
        name="JOBTEST MCP Config",
        schedule_config={"minutes": 5},
        input_params={"command": "echo x"},
    )
    configs = job_add_config(job["id"], device="laptop", repo="*")
    assert len(configs) == 2  # default + added

    added = next(c for c in configs if c["device"] == "laptop")
    job_update_config(added["id"], enabled=False)
    after = job_get(job["id"])["configs"]
    assert any(c["id"] == added["id"] and c["enabled"] is False for c in after)

    job_delete_config(added["id"])
    final = job_get(job["id"])["configs"]
    assert all(c["id"] != added["id"] for c in final)
