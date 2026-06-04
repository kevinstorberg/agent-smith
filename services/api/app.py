from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from scripts.shared.paths import bootstrap  # noqa: E402
bootstrap()

import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from services.db import init_db
from services.db.seed import seed_all
from services.api.routers import harness_router
from services.api.routers import memory, evals, plans, jobs, eval_suites as eval_configs
from services.memory.server import mcp as memory_mcp
from services.plans.server import mcp as plans_mcp
from services.harness.server import mcp as harness_mcp
from services.evals.server import mcp as evals_mcp
from services.graphs.server import mcp as graphs_mcp
from services.jobs.server import mcp as jobs_mcp
from services.jobs.scheduler import JobScheduler

MCP_SERVERS = [memory_mcp, plans_mcp, harness_mcp, evals_mcp, graphs_mcp, jobs_mcp]


@asynccontextmanager
async def lifespan(app):
    init_db()
    seed_all()
    scheduler = JobScheduler()
    async with contextlib.AsyncExitStack() as stack:
        for srv in MCP_SERVERS:
            await stack.enter_async_context(srv.session_manager.run())
        await scheduler.start()
        stack.push_async_callback(scheduler.stop)
        yield


app = FastAPI(title="Agent Smith Dashboard", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(harness_router, prefix="/api/harness", tags=["harness"])
app.include_router(memory.router, prefix="/api/memory", tags=["memory"])
app.include_router(evals.router, prefix="/api/evals", tags=["evals"])
app.include_router(plans.router, prefix="/api/plans", tags=["plans"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(eval_configs.router, prefix="/api/eval-configs", tags=["eval-configs"])

for _srv in MCP_SERVERS:
    _srv.settings.streamable_http_path = "/"
    _app = _srv.streamable_http_app()
    _app.router.lifespan_context = None
    app.mount(f"/mcp/{_srv.name.split(' - ')[0]}", _app)

dist_dir = Path(__file__).resolve().parent.parent / "client" / "dist"
if dist_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(dist_dir / "assets")), name="assets")


@app.api_route("/{path:path}", methods=["GET"], include_in_schema=False)
async def spa_fallback(request: Request, path: str):
    if dist_dir.exists():
        file_path = dist_dir / path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(dist_dir / "index.html")
    return FileResponse(dist_dir / "index.html", status_code=404)


if __name__ == "__main__":
    import uvicorn
    from services.config import DASHBOARD_PORT
    port = int(DASHBOARD_PORT)
    uvicorn.run("services.api.app:app", host="0.0.0.0", port=port, reload=True)
