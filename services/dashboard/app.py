from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.shared.paths import bootstrap  # noqa: E402
bootstrap()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from services.db import init_db
from services.dashboard.routers import harness, memory, evals, plans

app = FastAPI(title="Agent Smith Dashboard")

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

dist_dir = Path(__file__).parent / "ui" / "dist"
if dist_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(dist_dir / "assets")), name="assets")

    @app.get("/{path:path}")
    async def spa_fallback(request: Request, path: str):
        file_path = dist_dir / path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(dist_dir / "index.html")


@app.on_event("startup")
def startup():
    init_db()


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("DASHBOARD_PORT", "7654"))
    uvicorn.run("services.dashboard.app:app", host="0.0.0.0", port=port, reload=True)
