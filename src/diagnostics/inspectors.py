import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from assets.backends import get_storage_backend
from cache.backends import get_cache_backend
from config.loader import load_default_config
from config.models import DefaultConfig
from lib.cairn.paths import get_repo_root
from memory.backends import get_backend
from src.diagnostics.models import DiagnosticReport, DiagnosticResult
from src.diagnostics.redaction import redact_mapping
from src.settings import Settings, get_settings

CommandRunner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]


def inspect_config(
    *,
    config: DefaultConfig | None = None,
    settings: Settings | None = None,
    expose_values: bool = False,
) -> DiagnosticResult:
    resolved_config = config or load_default_config()
    resolved_settings = settings or get_settings()
    return DiagnosticResult(
        name="config",
        status="pass",
        details={
            "config": redact_mapping(resolved_config.model_dump(mode="json"), expose_values=expose_values),
            "settings": redact_mapping(resolved_settings.model_dump(mode="json"), expose_values=expose_values),
        },
    )


def inspect_registries(app: Any | None = None, *, discover: bool = True) -> DiagnosticResult:
    import src.services  # noqa: F401
    from src.jobs.registry import discover_jobs, registered_jobs
    from src.routers.registry import discover_routers, registered_routers
    from src.services.base import SERVICE_REGISTRY
    from src.tools import TOOL_FACTORY, discover_tools

    if discover:
        discover_tools()
        discover_jobs()
        discover_routers()

    details: dict[str, Any] = {
        "services": sorted(SERVICE_REGISTRY),
        "tools": sorted(TOOL_FACTORY),
        "jobs": sorted(registered_jobs()),
    }
    runtime = getattr(getattr(app, "state", None), "job_runtime", None)
    if runtime is not None:
        details["runtime_jobs"] = [job["name"] for job in runtime.list_jobs()]
    details["routers"] = sorted(registered_routers())
    return DiagnosticResult(name="registries", status="pass", details=details)


def inspect_migrations(
    *,
    repo_root: Path | None = None,
    command_runner: CommandRunner | None = None,
) -> DiagnosticResult:
    root = repo_root or get_repo_root(__file__)
    runner = command_runner or _run_command
    current = runner(["poetry", "run", "alembic", "current"], root)
    heads = runner(["poetry", "run", "alembic", "heads"], root)
    status = "pass" if current.returncode == 0 and heads.returncode == 0 else "fail"
    return DiagnosticResult(
        name="migrations",
        status=status,
        details={
            "current": _command_details(current),
            "heads": _command_details(heads),
        },
    )


async def inspect_backends(app: Any | None = None) -> DiagnosticReport:
    state = getattr(app, "state", None)
    results = [
        await _inspect_cache(getattr(state, "cache_backend", None)),
        await _inspect_memory(getattr(state, "memory_backend", None)),
        await _inspect_storage(),
    ]
    return DiagnosticReport(results=results)


async def inspect_health(app: Any | None = None) -> DiagnosticReport:
    results = [
        inspect_config(),
        inspect_registries(app),
        inspect_migrations(),
        *(await inspect_backends(app)).results,
    ]
    return DiagnosticReport(results=results)


async def _inspect_cache(cache_backend: Any | None) -> DiagnosticResult:
    try:
        backend = cache_backend or get_cache_backend()
        key = "cairn:diagnostics:cache"
        await backend.set(key, "ok", ttl=5)
        value = await backend.get(key)
        await backend.delete(key)
        if value != "ok":
            return DiagnosticResult(name="cache", status="fail", details={"message": "cache roundtrip mismatch"})
        return DiagnosticResult(name="cache", status="pass", details={"backend": backend.__class__.__name__})
    except Exception as e:
        return DiagnosticResult(name="cache", status="fail", details={"error": str(e)})


async def _inspect_memory(memory_backend: Any | None) -> DiagnosticResult:
    try:
        backend = memory_backend or get_backend()
        return DiagnosticResult(name="memory", status="pass", details={"backend": backend.__class__.__name__})
    except Exception as e:
        return DiagnosticResult(name="memory", status="fail", details={"error": str(e)})


async def _inspect_storage() -> DiagnosticResult:
    try:
        backend = get_storage_backend()
        return DiagnosticResult(name="storage", status="pass", details={"backend": backend.__class__.__name__})
    except Exception as e:
        return DiagnosticResult(name="storage", status="fail", details={"error": str(e)})


def _run_command(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, check=False, text=True)


def _command_details(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return {
        "returncode": result.returncode,
        "stdout": " ".join((result.stdout or "").split()),
        "stderr": " ".join((result.stderr or "").split()),
    }
