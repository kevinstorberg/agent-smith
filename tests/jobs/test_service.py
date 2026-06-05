"""Tests for the jobs service layer (atomic create-with-default-config)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from services.jobs.models.job import list_jobs
from services.jobs.service import create_job_with_default_config
from tests.conftest import jobs_cleanup

_clean = jobs_cleanup("JOBTEST %")


def test_create_attaches_one_default_config():
    job_id = create_job_with_default_config(
        name="JOBTEST Svc Create",
        schedule_config={"minutes": 5},
        input_params={"command": "echo x"},
    )
    from services.jobs.models.config import list_configs
    configs = list_configs(job_id)
    assert len(configs) == 1
    assert configs[0]["device"] == "*" and configs[0]["enabled"] is True


def test_create_is_atomic_when_config_insert_fails():
    """If the default-config insert fails, the job must not be left behind."""
    with patch(
        "services.jobs.service.JobConfigModel.create",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(RuntimeError):
            create_job_with_default_config(
                name="JOBTEST Svc Atomic",
                schedule_config={"minutes": 5},
                input_params={"command": "echo x"},
            )

    jobs, _ = list_jobs(limit=100, offset=0)
    assert not any(j["name"] == "JOBTEST Svc Atomic" for j in jobs)
