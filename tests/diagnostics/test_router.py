import subprocess

from fastapi import FastAPI
from fastapi.testclient import TestClient

from config.models import AdminDebugConfig, DefaultConfig
from src.api.errors import RequestIDMiddleware, register_error_handlers
from src.app import create_app
from src.diagnostics.router import create_diagnostics_router
from src.security.auth import create_token
from src.settings import Settings


def test_admin_debug_routes_are_disabled_by_default():
    client = TestClient(create_app())

    response = client.get("/admin/debug/config")

    assert response.status_code == 404


def test_admin_debug_routes_require_admin_token():
    client = _debug_client()

    missing = client.get("/admin/debug/config")
    user = client.get("/admin/debug/config", headers=_headers("user"))
    admin = client.get("/admin/debug/config", headers=_headers("admin"))

    assert missing.status_code == 401
    assert user.status_code == 403
    assert admin.status_code == 200
    assert admin.json()["name"] == "config"


def test_admin_debug_migrations_endpoint_uses_injected_command_runner():
    client = _debug_client(command_runner=_passing_migration_runner)

    response = client.get("/admin/debug/migrations", headers=_headers("admin"))

    assert response.status_code == 200
    assert response.json()["details"]["current"]["stdout"] == "current"


def test_admin_debug_health_returns_report():
    client = _debug_client(command_runner=_passing_migration_runner)

    response = client.get("/admin/debug/health", headers=_headers("admin"))

    assert response.status_code == 200
    result_names = {result["name"] for result in response.json()["results"]}
    assert {"config", "registries", "migrations", "cache", "memory", "storage"} <= result_names


def _debug_client(command_runner=None) -> TestClient:
    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(RequestIDMiddleware)
    config = DefaultConfig(admin_debug=AdminDebugConfig(enabled=True, require_admin=True))
    settings = Settings(_env_file=None)
    app.include_router(
        create_diagnostics_router(
            config=config,
            settings=settings,
            command_runner=command_runner or _passing_migration_runner,
        )
    )
    return TestClient(app)


def _headers(role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token('subject', {'role': role})}"}


def _passing_migration_runner(command, cwd):
    target = command[-1]
    output = "current" if target == "current" else "heads"
    return subprocess.CompletedProcess(command, returncode=0, stdout=output, stderr="")
