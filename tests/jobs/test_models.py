"""Test database models for background jobs."""
from __future__ import annotations

import pytest
from services.jobs.models.job import create_job, get_job, list_jobs, update_job, delete_job
from services.jobs.models.config import create_config, list_configs, update_config, delete_config
from services.jobs.models.execution import (
    create_execution, get_execution, complete_execution, list_executions_for_job
)
from tests.conftest import jobs_cleanup

_clean = jobs_cleanup("JOBTEST %")


def test_create_job():
    """Test creating a background job."""
    job_id = create_job(
        name="JOBTEST Create",
        schedule_config={"minutes": 5},
        input_params={"command": "echo test"}
    )
    assert job_id > 0

    job = get_job(job_id)
    assert job["name"] == "JOBTEST Create"
    assert job["schedule_config"] == {"minutes": 5}
    assert job["input_params"] == {"command": "echo test"}
    assert job["version"] == 1


def test_create_job_rejects_empty_schedule():
    """An empty schedule_config is invalid — interval scheduling is required."""
    with pytest.raises(AssertionError):
        create_job(
            name="JOBTEST Empty Schedule",
            schedule_config={},
            input_params={"command": "echo nope"},
        )


def test_update_job():
    """Test updating a job."""
    job_id = create_job(
        name="JOBTEST Update",
        schedule_config={"hours": 1},
        input_params={"command": "date"}
    )

    update_job(job_id, description="Updated description", schedule_config={"minutes": 30})

    job = get_job(job_id)
    assert job["description"] == "Updated description"
    assert job["schedule_config"] == {"minutes": 30}


def test_list_jobs():
    """Test listing jobs."""
    create_job(name="JOBTEST List 1", schedule_config={"minutes": 5}, input_params={"command": "echo 1"})
    create_job(name="JOBTEST List 2", schedule_config={"minutes": 5}, input_params={"command": "echo 2"})

    jobs, total = list_jobs(limit=10, offset=0)
    assert total >= 2
    assert any(j["name"] == "JOBTEST List 1" for j in jobs)


def test_delete_job():
    """Test deleting a job."""
    job_id = create_job(
        name="JOBTEST Delete",
        schedule_config={"minutes": 5},
        input_params={"command": "echo delete"}
    )

    delete_job(job_id)

    job = get_job(job_id)
    assert job is None


def test_create_config():
    """Test creating a job config."""
    job_id = create_job(
        name="JOBTEST Config",
        schedule_config={"minutes": 5},
        input_params={"command": "echo config"}
    )

    config_id = create_config(
        job_id=job_id,
        device="*",
        repo="*",
        enabled=True,
        exclude=False
    )

    assert config_id > 0


def test_list_configs():
    """Test listing configs for a job."""
    job_id = create_job(
        name="JOBTEST Multi Config",
        schedule_config={"minutes": 5},
        input_params={"command": "echo multi"}
    )

    create_config(job_id=job_id, device="laptop", repo="*", enabled=True)
    create_config(job_id=job_id, device="*", repo="/home/user/project", enabled=True)

    configs = list_configs(job_id)
    assert len(configs) == 2
    assert any(c["device"] == "laptop" for c in configs)


def test_update_config():
    """Test updating a config."""
    job_id = create_job(
        name="JOBTEST Update Config",
        schedule_config={"minutes": 5},
        input_params={"command": "echo update"}
    )

    config_id = create_config(job_id=job_id, device="*", repo="*", enabled=True)

    update_config(config_id, enabled=False)

    configs = list_configs(job_id)
    assert configs[0]["enabled"] is False


def test_delete_config():
    """Test deleting a config."""
    job_id = create_job(
        name="JOBTEST Delete Config",
        schedule_config={"minutes": 5},
        input_params={"command": "echo delete"}
    )

    config_id = create_config(job_id=job_id, device="*", repo="*", enabled=True)

    delete_config(config_id)

    configs = list_configs(job_id)
    assert len(configs) == 0


def test_create_execution():
    """Test creating a job execution."""
    job_id = create_job(
        name="JOBTEST Execution",
        schedule_config={"minutes": 5},
        input_params={"command": "echo exec"}
    )

    exec_id = create_execution(job_id=job_id, status="running")
    assert exec_id > 0

    execution = get_execution(exec_id)
    assert execution["job_id"] == job_id
    assert execution["status"] == "running"


def test_complete_execution():
    """Test completing an execution."""
    job_id = create_job(
        name="JOBTEST Complete",
        schedule_config={"minutes": 5},
        input_params={"command": "echo complete"}
    )

    exec_id = create_execution(job_id=job_id, status="running")

    result = {
        "success": True,
        "output": "Hello World",
        "error": "",
        "duration_seconds": 1.23,
        "exit_code": 0
    }

    complete_execution(exec_id, status="success", result=result)

    execution = get_execution(exec_id)
    assert execution["status"] == "success"
    assert execution["result"]["success"] is True
    assert execution["result"]["output"] == "Hello World"
    assert execution["completed_at"] is not None


def test_list_executions_for_job():
    """Test listing executions for a job."""
    job_id = create_job(
        name="JOBTEST Multi Execution",
        schedule_config={"minutes": 5},
        input_params={"command": "echo multi"}
    )

    exec_id1 = create_execution(job_id=job_id, status="running")
    exec_id2 = create_execution(job_id=job_id, status="running")

    complete_execution(exec_id1, status="success", result={"success": True})
    complete_execution(exec_id2, status="failed", result={"success": False})

    executions, total = list_executions_for_job(job_id, limit=10, offset=0)

    assert total == 2
    assert len(executions) == 2
