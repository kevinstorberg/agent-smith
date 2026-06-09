import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from config.models import DefaultConfig
from src.diagnostics.inspectors import inspect_backends, inspect_config, inspect_migrations, inspect_registries
from src.diagnostics.models import DiagnosticReport, DiagnosticResult
from src.policies.base import Permission
from src.policies.dependencies import require_permission
from src.settings import Settings

CommandRunner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]


def create_diagnostics_router(
    *,
    config: DefaultConfig,
    settings: Settings,
    command_runner: CommandRunner | None = None,
) -> APIRouter:
    dependencies = []
    if config.admin_debug.require_admin:
        dependencies.append(Depends(require_permission(Permission.ADMIN)))

    router = APIRouter(prefix="/admin/debug", tags=["admin-debug"], dependencies=dependencies)

    @router.get("/config", response_model=DiagnosticResult)
    async def config_endpoint() -> DiagnosticResult:
        return inspect_config(
            config=config,
            settings=settings,
            expose_values=config.admin_debug.expose_config_values,
        )

    @router.get("/registries", response_model=DiagnosticResult)
    async def registries_endpoint(request: Request) -> DiagnosticResult:
        return inspect_registries(request.app)

    @router.get("/migrations", response_model=DiagnosticResult)
    async def migrations_endpoint() -> DiagnosticResult:
        return inspect_migrations(command_runner=command_runner or _run_command)

    @router.get("/backends", response_model=DiagnosticReport)
    async def backends_endpoint(request: Request) -> DiagnosticReport:
        return await inspect_backends(request.app)

    @router.get("/health", response_model=DiagnosticReport)
    async def health_endpoint(request: Request) -> DiagnosticReport:
        return DiagnosticReport(
            results=[
                inspect_config(
                    config=config,
                    settings=settings,
                    expose_values=config.admin_debug.expose_config_values,
                ),
                inspect_registries(request.app),
                inspect_migrations(command_runner=command_runner or _run_command),
                *(await inspect_backends(request.app)).results,
            ]
        )

    return router


def _run_command(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, check=False, text=True)
