import asyncio

import pytest
from fastapi import HTTPException

from services.api.routers import jobs
from services.config import DEVICE_NAME
from services.db import get_connection
from services.jobs.models.config import create_config, update_config
from services.jobs.models.job import create_job
from tests.conftest import jobs_cleanup

_clean = jobs_cleanup("JOBTEST DISCOVERY %")


def persona_job(suffix):
    return jobs.create(jobs.JobCreateRequest(
        name="JOBTEST DISCOVERY " + suffix, schedule_config={"minutes": 15},
        input_params={"graph_type": "persona", "graph_inputs": {}, "timeout": 600},
    ))


def test_graph_discovery_filters_before_pagination_and_uses_real_device_scopes():
    active = persona_job("enabled")
    disabled = persona_job("disabled")
    update_config(disabled["configs"][0]["id"], enabled=False)
    excluded = persona_job("excluded")
    create_config(excluded["id"], device=DEVICE_NAME, repo="*", exclude=True)
    elsewhere = persona_job("elsewhere")
    update_config(elsewhere["configs"][0]["id"], device=DEVICE_NAME + "-other")
    proposed = persona_job("proposed")
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE background_jobs SET state = 'proposed' WHERE id = %s", (proposed["id"],))
    for index in range(101):
        create_job("JOBTEST DISCOVERY unrelated " + str(index), {"minutes": 15}, {"command": "echo persona"})
    result = jobs.for_graph("persona")
    found = {job["id"]: job for job in result["items"]}
    assert result["total"] == 4
    assert set(found) == {active["id"], disabled["id"], excluded["id"], elsewhere["id"]}
    assert found[active["id"]]["runs_on_device"]
    assert all(not found[job["id"]]["runs_on_device"] for job in (disabled, excluded, elsewhere))
    assert all(job["configs"] for job in found.values())
    assert jobs.for_graph("unknown")["items"] == []
    assert jobs.for_graph("persona' OR true --")["items"] == []


@pytest.mark.asyncio
async def test_parallel_manual_runs_return_their_exact_execution_ids():
    first = jobs.create(jobs.JobCreateRequest(name="JOBTEST DISCOVERY first", schedule_config={"minutes": 15}, input_params={"command": "echo first"}))
    second = jobs.create(jobs.JobCreateRequest(name="JOBTEST DISCOVERY second", schedule_config={"minutes": 15}, input_params={"command": "echo second"}))
    results = await asyncio.gather(jobs.run_now(first["id"]), jobs.run_now(second["id"]))
    assert results[0]["execution_id"] != results[1]["execution_id"]
    for job, result, text in zip((first, second), results, ("first", "second"), strict=True):
        execution = jobs.execution_one(job["id"], result["execution_id"])
        assert execution["job_id"] == job["id"] and execution["status"] == "success"
        assert text in execution["result"]["output"]
        assert {key: value for key, value in result.items() if key != "execution_id"} == execution["result"]
    with pytest.raises(HTTPException) as caught:
        jobs.execution_one(first["id"], results[1]["execution_id"])
    assert caught.value.status_code == 404
