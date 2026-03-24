"""Web UI routes for the memory browser."""

from __future__ import annotations

from pathlib import Path

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

import services.memory.db as db

_HTML = (Path(__file__).parent / "ui.html").read_text()


def register(mcp) -> None:
    """Attach all web UI routes to the given FastMCP instance."""

    @mcp.custom_route("/ui/", methods=["GET"])
    async def ui_index(request: Request) -> HTMLResponse:
        return HTMLResponse(_HTML)

    @mcp.custom_route("/api/memories", methods=["GET"])
    async def api_list(request: Request) -> JSONResponse:
        repo = request.query_params.get("repo") or None
        limit = int(request.query_params.get("limit", db.DEFAULT_LIMIT))
        return JSONResponse(db.list_memories(repo=repo, limit=limit))

    @mcp.custom_route("/api/memories/search", methods=["GET"])
    async def api_search(request: Request) -> JSONResponse:
        query = request.query_params.get("q", "").strip()
        if not query:
            return JSONResponse({"error": "Missing ?q= parameter"}, status_code=400)
        repo = request.query_params.get("repo") or None
        limit = int(request.query_params.get("limit", db.DEFAULT_LIMIT))
        return JSONResponse(db.search(query=query, repo=repo, limit=limit))

    @mcp.custom_route("/api/memories/{id}", methods=["GET"])
    async def api_get(request: Request) -> JSONResponse:
        memory_id = request.path_params["id"]
        mem = db.get(memory_id)
        if not mem:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return JSONResponse(mem)

    @mcp.custom_route("/api/repos", methods=["GET"])
    async def api_repos(request: Request) -> JSONResponse:
        all_memories = db.list_memories(limit=10000)
        repos = sorted({m["repo"] for m in all_memories if m.get("repo")})
        return JSONResponse(repos)
