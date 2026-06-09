from fastapi import FastAPI
from fastapi.testclient import TestClient

from config.models import DefaultConfig, JobsConfig
from src.api.errors import RequestIDMiddleware, register_error_handlers
from src.jobs.base import BaseJob
from src.jobs.definitions import JobDefinition, LockPolicy, import_path_for
from src.jobs.router import create_jobs_router
from src.jobs.runtime import create_job_runtime
from src.security.auth import create_token
from src.settings import Settings


class RouterJob(BaseJob):
    name = "router_job"

    async def execute(self):
        return None


def build_router_job() -> BaseJob:
    return RouterJob()


def _client() -> TestClient:
    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(RequestIDMiddleware)
    definition = JobDefinition(
        name="router_job",
        factory=import_path_for(build_router_job),
        lock_policy=LockPolicy(enabled=False),
    )
    app.state.job_runtime = create_job_runtime(
        DefaultConfig(jobs=JobsConfig(auto_discover=False)),
        Settings(_env_file=None),
        definitions={definition.name: definition},
    )
    app.include_router(create_jobs_router())
    return TestClient(app)


def _admin_headers() -> dict[str, str]:
    token = create_token("admin-user", {"role": "admin"})
    return {"Authorization": f"Bearer {token}"}


def test_jobs_router_requires_authentication():
    response = _client().get("/jobs/health")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_jobs_health_and_list_endpoints_return_runtime_state():
    client = _client()

    health = client.get("/jobs/health", headers=_admin_headers())
    jobs = client.get("/jobs", headers=_admin_headers())

    assert health.status_code == 200
    assert health.json()["health"]["job_count"] == 1
    assert jobs.status_code == 200
    assert jobs.json()["jobs"][0]["name"] == "router_job"


def test_jobs_manual_run_and_runs_endpoint():
    client = _client()

    run_response = client.post("/jobs/router_job/run", headers=_admin_headers())
    runs_response = client.get("/jobs/router_job/runs", headers=_admin_headers())

    assert run_response.status_code == 200
    assert run_response.json()["run"]["status"] == "success"
    assert runs_response.status_code == 200
    assert runs_response.json()["runs"][0]["status"] == "success"


def test_jobs_unknown_job_uses_error_envelope():
    response = _client().post("/jobs/missing/run", headers=_admin_headers())

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "job_not_found"


def test_jobs_runs_limit_validation_uses_error_envelope():
    response = _client().get("/jobs/router_job/runs?limit=0", headers=_admin_headers())

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
