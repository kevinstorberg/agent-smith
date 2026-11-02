from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from services.db import get_connection
from services.jobs.models.config import create_config, list_configs
from services.jobs.models.execution import complete_execution, create_execution, list_executions_for_job
from services.jobs.models.job import JobNotFoundError, create_job, get_job, list_jobs, set_schedule_enabled, update_job
from tests.conftest import jobs_cleanup

_clean = jobs_cleanup("JOBSTATE %")


def job(name):
    return create_job(f"JOBSTATE {name}", {"minutes": 5}, {"command": "echo synthetic"}, "Keep definition")


def test_schedule_state_defaults_true_and_remains_visible_when_paused():
    job_id = job("visible")
    assert get_job(job_id)["schedule_enabled"] is True
    paused = set_schedule_enabled(job_id, False)
    assert paused["schedule_enabled"] is False and paused["state"] == "active"
    assert any(row["id"] == job_id and row["schedule_enabled"] is False for row in list_jobs(limit=None)[0])


def test_schedule_state_changes_only_selected_flag_version_timestamp_and_repeats_are_idempotent():
    job_id, other_id = job("selected"), job("other")
    create_config(job_id, device="*", repo="*", enabled=True)
    create_config(job_id, device="device-a", repo="repo-a", enabled=False)
    create_config(job_id, device="device-b", repo="repo-b", enabled=True, exclude=True)
    execution_id = create_execution(job_id)
    complete_execution(execution_id, "success", {"output": "Preserve history"})
    before, other = get_job(job_id), get_job(other_id)
    configs, history = list_configs(job_id), list_executions_for_job(job_id)
    assert set_schedule_enabled(job_id, True) == before
    paused = set_schedule_enabled(job_id, False)
    assert paused["version"] == before["version"] + 1
    assert paused["updated_at"] != before["updated_at"]
    unchanged = set(before) - {"schedule_enabled", "version", "updated_at"}
    assert {key: paused[key] for key in unchanged} == {key: before[key] for key in unchanged}
    assert set_schedule_enabled(job_id, False) == paused == get_job(job_id)
    resumed = set_schedule_enabled(job_id, True)
    assert resumed["schedule_enabled"] is True and resumed["version"] == paused["version"] + 1
    assert set_schedule_enabled(job_id, True) == resumed
    assert get_job(other_id) == other
    assert list_configs(job_id) == configs and list_executions_for_job(job_id) == history


def test_schedule_state_concurrent_repeated_set_is_one_change():
    job_id = job("concurrent")
    barrier = Barrier(2)
    def pause():
        barrier.wait(timeout=3)
        return set_schedule_enabled(job_id, False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(pause), pool.submit(pause)
        rows = [first.result(timeout=5), second.result(timeout=5)]
    assert rows[0] == rows[1] == get_job(job_id)
    assert rows[0]["schedule_enabled"] is False and rows[0]["version"] == 2


def test_schedule_state_survives_ordinary_definition_updates():
    job_id = job("definition")
    set_schedule_enabled(job_id, False)
    update_job(job_id, description="New description", schedule_config={"hours": 1})
    assert get_job(job_id)["schedule_enabled"] is False


@pytest.mark.parametrize("state", ["proposed", "rejected"])
def test_schedule_state_rejects_nonactive_rows_without_changing_them(state):
    job_id = job(state)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE background_jobs SET state=%s WHERE id=%s", (state, job_id))
    before = get_job(job_id)
    with pytest.raises(JobNotFoundError):
        set_schedule_enabled(job_id, False)
    assert get_job(job_id) == before


def test_schedule_state_rejects_missing_jobs():
    with pytest.raises(JobNotFoundError):
        set_schedule_enabled(2_147_483_647, False)


@pytest.mark.parametrize("job_id", [None, True, False, 0, -1, 1.5, "1"])
def test_schedule_state_requires_positive_integer_job_id(job_id):
    with pytest.raises(ValueError, match="positive integer"):
        set_schedule_enabled(job_id, False)


@pytest.mark.parametrize("enabled", [None, 0, 1, "true", "false", [], {}])
def test_schedule_state_requires_actual_boolean_without_mutating_row(enabled):
    job_id = job("invalid boolean")
    before = get_job(job_id)
    with pytest.raises(ValueError, match="must be a boolean"):
        set_schedule_enabled(job_id, enabled)
    assert get_job(job_id) == before
