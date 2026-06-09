import pytest

from src.jobs.base import BaseJob
from src.jobs.definitions import JobDefinition, LockPolicy, RetryPolicy, import_path_for
from src.jobs.registry import clear_registered_jobs, register_job, registered_jobs


class RegisteredTestJob(BaseJob):
    name = "registered_test_job"

    async def execute(self):
        return None


def build_registered_test_job() -> BaseJob:
    return RegisteredTestJob()


@pytest.fixture(autouse=True)
def clear_registry():
    clear_registered_jobs()
    yield
    clear_registered_jobs()


def test_register_job_records_importable_factory_definition():
    register_job(
        name="registered",
        trigger="interval",
        trigger_kwargs={"seconds": 60},
        retry_policy=RetryPolicy(max_attempts=2),
        lock_policy=LockPolicy(key="custom-key"),
    )(build_registered_test_job)

    definition = registered_jobs()["registered"]
    assert definition.factory == import_path_for(build_registered_test_job)
    assert definition.trigger_kwargs == {"seconds": 60}
    assert definition.retry_policy.max_attempts == 2
    assert definition.lock_key == "custom-key"
    assert isinstance(definition.create_job(), RegisteredTestJob)


def test_register_job_rejects_non_importable_local_factory():
    def build_local_job() -> BaseJob:
        return RegisteredTestJob()

    with pytest.raises(ValueError, match="importable"):
        register_job(name="local")(build_local_job)


def test_job_definition_validates_persistent_factory_path():
    definition = JobDefinition(name="registered", factory=import_path_for(build_registered_test_job))

    definition.validate_for_persistent_store()


def test_job_definition_requires_factory_for_persistent_store():
    definition = JobDefinition(name="registered")

    with pytest.raises(ValueError, match="persistent scheduling"):
        definition.validate_for_persistent_store()
