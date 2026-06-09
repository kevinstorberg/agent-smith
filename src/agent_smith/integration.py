from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from lib.agent_smith_core.paths import get_repo_root

logger = logging.getLogger(__name__)
AGENT_SMITH_FRONTEND_ROUTES = ("harness", "memory", "evals", "eval-configs", "plans", "jobs")


def include_agent_smith_routes(app: FastAPI) -> None:
    from src.agent_smith.routers import evals, harness, jobs, memory, plans, sync

    app.include_router(harness.router, prefix="/api/harness", tags=["agent-smith:harness"])
    app.include_router(memory.router, prefix="/api/memory", tags=["agent-smith:memory"])
    app.include_router(evals.evals_router, prefix="/api/evals", tags=["agent-smith:evals"])
    app.include_router(plans.router, prefix="/api/plans", tags=["agent-smith:plans"])
    app.include_router(jobs.router, prefix="/api/jobs", tags=["agent-smith:jobs"])
    app.include_router(sync.router, prefix="/api/harness", tags=["agent-smith:sync"])
    app.include_router(evals.eval_configs_router, prefix="/api/eval-configs", tags=["agent-smith:eval-configs"])
    _mount_mcp_servers(app)


async def start_agent_smith_runtime(app: FastAPI) -> None:
    settings = app.state.settings
    local_runtime_default = settings.APP_ENV != "production"
    if _runtime_flag(settings, "AGENT_SMITH_AUTO_SEED", default=local_runtime_default):
        from src.agent_smith.services.seed import seed_all

        await seed_all()
    else:
        logger.info("Agent Smith seed disabled")

    stack = contextlib.AsyncExitStack()
    for server in _mcp_servers():
        await stack.enter_async_context(server.session_manager.run())
    app.state.agent_smith_mcp_stack = stack

    if _runtime_flag(
        settings,
        "AGENT_SMITH_JOBS_ENABLED",
        default=local_runtime_default,
        legacy_name="AGENT_SMITH_LEGACY_SCHEDULER_ENABLED",
    ):
        from src.agent_smith.job_runtime import AgentSmithJobRuntimeAdapter

        adapter = AgentSmithJobRuntimeAdapter(app.state.job_runtime)
        await adapter.start()
        app.state.agent_smith_job_adapter = adapter
    else:
        logger.info("Agent Smith job adapter disabled")


async def stop_agent_smith_runtime(app: FastAPI) -> None:
    adapter = getattr(app.state, "agent_smith_job_adapter", None)
    if adapter is not None:
        await adapter.stop()
        app.state.agent_smith_job_adapter = None

    stack = getattr(app.state, "agent_smith_mcp_stack", None)
    if stack is not None:
        await stack.aclose()
        app.state.agent_smith_mcp_stack = None


def mount_agent_smith_frontend(app: FastAPI, *, repo_root: Path | None = None) -> None:
    root = repo_root or get_repo_root(__file__)
    dist_dir = root / "frontend" / "dist"
    if not dist_dir.exists():
        logger.info("Agent Smith frontend build not found; skipping static mount", extra={"dist_dir": str(dist_dir)})
        return

    assets_dir = dist_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="agent-smith-assets")

    async def agent_smith_spa_fallback(request: Request):
        path = request.path_params.get("path", "")
        file_path = _safe_frontend_file(dist_dir, path)
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(dist_dir / "index.html")

    app.add_api_route("/", agent_smith_spa_fallback, methods=["GET"], include_in_schema=False)
    for route in AGENT_SMITH_FRONTEND_ROUTES:
        app.add_api_route(f"/{route}", agent_smith_spa_fallback, methods=["GET"], include_in_schema=False)
        app.add_api_route(f"/{route}/{{path:path}}", agent_smith_spa_fallback, methods=["GET"], include_in_schema=False)


def _mount_mcp_servers(app: FastAPI) -> None:
    for server in _mcp_servers():
        server.settings.streamable_http_path = "/"
        mounted = server.streamable_http_app()
        mounted.router.lifespan_context = None
        app.mount(f"/mcp/{server.name.split(' - ')[0]}", mounted)


def _mcp_servers():
    from src.agent_smith.mcp_servers import all_mcp_servers

    return all_mcp_servers()


def _safe_frontend_file(dist_dir: Path, path: str) -> Path:
    root = dist_dir.resolve()
    candidate = (root / path).resolve()
    if candidate.is_relative_to(root):
        return candidate
    return root / "index.html"


def _runtime_flag(settings, name: str, *, default: bool, legacy_name: str | None = None) -> bool:
    value = getattr(settings, name, None)
    if value is not None:
        return bool(value)
    if legacy_name is not None and (legacy_value := os.environ.get(legacy_name)) is not None:
        logger.warning("%s is deprecated; use %s instead", legacy_name, name)
        return _parse_bool(legacy_name, legacy_value)
    return default


def _parse_bool(name: str, value: str | None) -> bool:
    if value is None:
        raise ValueError(f"{name} is missing")
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value, got {value!r}")
