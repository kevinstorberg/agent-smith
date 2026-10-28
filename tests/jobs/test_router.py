"""REST router tests for background jobs (Tracer Bullet 4).

Follows the repo convention of calling route handlers directly rather than
booting the app through a TestClient.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from services.config import DEVICE_NAME
from services.api.routers.jobs import (
    ConfigCreateRequest,
    ConfigUpdateRequest,
    JobCreateRequest,
    JobUpdateRequest,
    add_config,
    create,
    delete,
    executions,
    get_one,
    list_all,
    patch_config,
    remove_config,
    run_now,
    update,
)
from tests.conftest import jobs_cleanup

_clean = jobs_cleanup("JOBTEST %")


def _create(name: str, command: str = "echo hi", schedule=None) -> dict:
    return create(
        JobCreateRequest(
            name=name,
            schedule_config=schedule or {"minutes": 5},
            input_params={"command": command},
        )
    )


def test_create_attaches_default_config():
    job = _create("JOBTEST R Create")
    assert job["name"] == "JOBTEST R Create"
    assert len(job["configs"]) == 1
    assert job["configs"][0]["device"] == "*"
    assert job["configs"][0]["enabled"] is True


def test_create_graph_scoped_to_this_device_attaches_one_server_device_config():
    params = {"graph_type": "echo", "graph_inputs": {"text": "scheduled graph"}, "timeout": 300}
    job = create(JobCreateRequest(
        name="JOBTEST R Device Graph", schedule_config={"minutes": 15},
        input_params=params, device_scope="this_device",
    ))
    assert job["input_params"] == params
    assert len(job["configs"]) == 1
    config = job["configs"][0]
    assert config["device"] == DEVICE_NAME
    assert config["repo"] == "*" and config["enabled"] and not config["exclude"]


def test_create_rejects_unknown_device_scope():
    with pytest.raises(ValidationError):
        JobCreateRequest(
            name="JOBTEST R Bad Device", schedule_config={"minutes": 5},
            input_params={"command": "echo x"}, device_scope="client-supplied-device",
        )


def test_create_rejects_empty_schedule():
    with pytest.raises(ValidationError):
        JobCreateRequest(name="JOBTEST R Bad", schedule_config={}, input_params={"command": "echo x"})


def test_create_requires_command():
    with pytest.raises(ValidationError):
        JobCreateRequest(name="JOBTEST R NoCmd", schedule_config={"minutes": 5}, input_params={})


def test_create_duplicate_name_conflicts():
    _create("JOBTEST R Dup")
    with pytest.raises(HTTPException) as exc:
        _create("JOBTEST R Dup")
    assert exc.value.status_code == 409


def test_patch_config_foreign_is_404():
    job_a = _create("JOBTEST R Owner A")
    job_b = _create("JOBTEST R Owner B")
    foreign_config_id = job_b["configs"][0]["id"]
    with pytest.raises(HTTPException) as exc:
        patch_config(job_a["id"], foreign_config_id, ConfigUpdateRequest(enabled=False))
    assert exc.value.status_code == 404


def test_remove_config_missing_is_404():
    job = _create("JOBTEST R Owner C")
    with pytest.raises(HTTPException) as exc:
        remove_config(job["id"], 99_999_999)
    assert exc.value.status_code == 404


def test_list_returns_total():
    _create("JOBTEST R List 1")
    _create("JOBTEST R List 2")
    result = list_all(limit=10, offset=0)
    assert result["total"] >= 2
    assert any(j["name"] == "JOBTEST R List 1" for j in result["items"])


def test_get_one_missing_raises_404():
    with pytest.raises(HTTPException) as exc:
        get_one(999_999)
    assert exc.value.status_code == 404


def test_update_changes_fields():
    job = _create("JOBTEST R Update")
    updated = update(
        job["id"],
        JobUpdateRequest(description="new desc", schedule_config={"minutes": 10}),
    )
    assert updated["description"] == "new desc"
    assert updated["schedule_config"] == {"minutes": 10}


def test_update_replaces_command_and_graph_execution_payloads():
    job = _create("JOBTEST R Execution Mode")
    graph = {"graph_type": "echo", "graph_inputs": {"text": "updated graph"}, "timeout": 300}
    updated = update(job["id"], JobUpdateRequest(input_params=graph))
    assert updated["input_params"] == graph
    command = {"command": "echo command again", "timeout": 300}
    updated = update(job["id"], JobUpdateRequest(input_params=command))
    assert updated["input_params"] == command


def test_delete_removes_job():
    job = _create("JOBTEST R Delete")
    result = delete(job["id"])
    assert result["deleted"] is True
    with pytest.raises(HTTPException):
        get_one(job["id"])


@pytest.mark.asyncio
async def test_run_now_records_execution():
    job = _create("JOBTEST R RunNow", command="echo run-now-test")
    result = await run_now(job["id"])
    assert result["success"] is True
    assert "run-now-test" in result["output"]

    listed = executions(job["id"], limit=10, offset=0)
    assert listed["total"] == 1
    assert listed["items"][0]["status"] == "success"


def test_add_and_patch_and_remove_config():
    job = _create("JOBTEST R Config")
    default_config_id = job["configs"][0]["id"]

    configs = add_config(job["id"], ConfigCreateRequest(device="laptop", repo="*"))
    assert len(configs) == 2

    patched = patch_config(job["id"], default_config_id, ConfigUpdateRequest(enabled=False))
    disabled = next(c for c in patched if c["id"] == default_config_id)
    assert disabled["enabled"] is False

    removed = remove_config(job["id"], default_config_id)
    assert removed["deleted"] is True
