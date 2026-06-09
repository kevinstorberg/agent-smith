from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from lib.cairn.paths import get_repo_root
from src.settings import get_settings

logger = logging.getLogger(__name__)


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
    if _enabled("AGENT_SMITH_AUTO_SEED", default=settings.APP_ENV != "production"):
        from src.agent_smith.services.seed import seed_all

        await seed_all()
    else:
        logger.info("Agent Smith seed disabled")

    stack = contextlib.AsyncExitStack()
    for server in _mcp_servers():
        await stack.enter_async_context(server.session_manager.run())
    app.state.agent_smith_mcp_stack = stack

    if _enabled("AGENT_SMITH_LEGACY_SCHEDULER_ENABLED", default=settings.APP_ENV != "production"):
        from src.agent_smith.services.jobs import AgentSmithJobScheduler

        scheduler = AgentSmithJobScheduler()
        await scheduler.start()
        app.state.agent_smith_scheduler = scheduler
    else:
        logger.info("Agent Smith legacy scheduler disabled")


async def stop_agent_smith_runtime(app: FastAPI) -> None:
    scheduler = getattr(app.state, "agent_smith_scheduler", None)
    if scheduler is not None:
        await scheduler.stop()
        app.state.agent_smith_scheduler = None

    stack = getattr(app.state, "agent_smith_mcp_stack", None)
    if stack is not None:
        await stack.aclose()
        app.state.agent_smith_mcp_stack = None


def mount_agent_smith_frontend(app: FastAPI, *, repo_root: Path | None = None) -> None:
    root = repo_root or get_repo_root(__file__)
    dist_dir = root / "frontend" / "dist"
    assets_dir = dist_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="agent-smith-assets")

    @app.api_route("/{path:path}", methods=["GET"], include_in_schema=False)
    async def agent_smith_spa_fallback(request: Request, path: str):
        if not dist_dir.exists():
            raise HTTPException(status_code=404, detail="Frontend build not found")

        file_path = dist_dir / path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(dist_dir / "index.html")


def _mount_mcp_servers(app: FastAPI) -> None:
    for server in _mcp_servers():
        server.settings.streamable_http_path = "/"
        mounted = server.streamable_http_app()
        mounted.router.lifespan_context = None
        app.mount(f"/mcp/{server.name.split(' - ')[0]}", mounted)


def _mcp_servers():
    from src.agent_smith.mcp_servers import all_mcp_servers

    return all_mcp_servers()


def _enabled(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None and hasattr(get_settings(), name):
        return bool(getattr(get_settings(), name))
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
