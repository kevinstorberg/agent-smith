from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.shared.paths import bootstrap  # noqa: E402
bootstrap()

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from services.db import init_db
from services.db.seed import seed_all
from services.dashboard.routers import harness, memory, evals, plans, eval_configs
from services.memory.server import mcp as mcp_server


@asynccontextmanager
async def lifespan(app):
    init_db()
    seed_all()
    async with mcp_server.session_manager.run():
        yield


app = FastAPI(title="Agent Smith Dashboard", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(harness.router, prefix="/api/harness", tags=["harness"])
app.include_router(memory.router, prefix="/api/memory", tags=["memory"])
app.include_router(evals.router, prefix="/api/evals", tags=["evals"])
app.include_router(plans.router, prefix="/api/plans", tags=["plans"])
app.include_router(eval_configs.router, prefix="/api/eval-configs", tags=["eval-configs"])

mcp_server.settings.streamable_http_path = "/"
mcp_starlette = mcp_server.streamable_http_app()
mcp_starlette.router.lifespan_context = None  # managed by FastAPI lifespan above
app.mount("/mcp", mcp_starlette)

dist_dir = Path(__file__).parent / "ui" / "dist"
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
    uvicorn.run("services.dashboard.app:app", host="0.0.0.0", port=port, reload=True)
