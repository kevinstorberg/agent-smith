"""MCP endpoints keep serving connected agents across a dashboard restart.

Agents hold the Mcp-Session-Id they were issued and keep sending it after the
server restarts; ./run.sh replacing a running instance makes that routine.
"""
from __future__ import annotations

import json
import logging
from contextlib import AsyncExitStack

import httpx
import pytest
import pytest_asyncio
from starlette.routing import Mount

from services.api.app import MCP_SERVERS, app

SESSION_ID_FROM_PREVIOUS_PROCESS = "0123456789abcdef0123456789abcdef"
MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "Mcp-Session-Id": SESSION_ID_FROM_PREVIOUS_PROCESS,
}


@pytest_asyncio.fixture
async def dashboard_client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


def _mcp_mount_paths() -> list[str]:
    paths = [route.path for route in app.routes if isinstance(route, Mount) and route.path.startswith("/mcp/")]
    assert len(paths) == len(MCP_SERVERS), f"expected one mount per MCP server, found {paths}"
    return paths


def _json_rpc_payload(response: httpx.Response) -> dict:
    if response.headers["content-type"].startswith("application/json"):
        return response.json()
    data_lines = [line.removeprefix("data:").strip() for line in response.text.splitlines() if line.startswith("data:")]
    assert len(data_lines) == 1, f"expected one SSE data event, got {response.text!r}"
    return json.loads(data_lines[0])


@pytest.mark.asyncio
async def test_every_mcp_endpoint_serves_a_session_id_from_before_a_restart(caplog):
    caplog.set_level(logging.INFO)
    async with AsyncExitStack() as stack:
        for server in MCP_SERVERS:
            await stack.enter_async_context(server.session_manager.run())
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:7654") as client:
            for path in _mcp_mount_paths():
                response = await client.post(
                    f"{path}/",
                    headers=MCP_HEADERS,
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                )

                assert response.status_code == 200, f"{path} answered {response.status_code}: {response.text}"
                assert _json_rpc_payload(response)["result"]["tools"], f"{path} listed no tools"

            response = await client.get(f"{path}/", headers={"Accept": "application/json"})
            assert response.status_code == 406
            assert "text/event-stream" in response.json()["error"]["message"]

            response = await client.get(f"{path}/.well-known/openid-configuration")
            assert response.status_code == 404

    logger = logging.getLogger("mcp.server.streamable_http")
    logger.warning("transport warning remains visible")
    logger.error("transport error remains visible")
    messages = [record.getMessage() for record in caplog.records if record.name == logger.name]
    assert not any(message.startswith("Terminating session:") for message in messages)
    assert "transport warning remains visible" in messages
    assert "transport error remains visible" in messages


@pytest.mark.asyncio
@pytest.mark.parametrize("built", [False, True])
@pytest.mark.parametrize("path", [
    "/.well-known",
    "/.well-known/",
    "/.well-known/oauth-protected-resource/mcp/memory",
    "/.well-known/oauth-authorization-server",
    "/.well-known/oauth-authorization-server/mcp/jobs",
    "/.well-known/openid-configuration/mcp/jobs",
    "/%2Ewell-known/oauth-authorization-server",
])
async def test_unknown_discovery_paths_never_return_dashboard_html(tmp_path, monkeypatch, built, path, dashboard_client):
    dist = tmp_path / "dist"
    if built:
        dist.mkdir()
        (dist / "index.html").write_text("<!doctype html><title>Dashboard</title>")
    monkeypatch.setattr("services.api.app.dist_dir", dist)
    response = await dashboard_client.get(path)
    assert response.status_code == 404
    assert not response.headers["content-type"].startswith("text/html")


@pytest.mark.asyncio
async def test_static_discovery_files_and_dashboard_deep_links_still_work(tmp_path, monkeypatch, dashboard_client):
    index = "<!doctype html><title>Dashboard</title>"
    (tmp_path / "index.html").write_text(index)
    (tmp_path / ".well-known").mkdir()
    (tmp_path / ".well-known/security.txt").write_text("Contact: mailto:security@example.test")
    monkeypatch.setattr("services.api.app.dist_dir", tmp_path)
    response = await dashboard_client.get("/.well-known/security.txt")
    assert response.status_code == 200
    assert response.text == "Contact: mailto:security@example.test"
    response = await dashboard_client.get("/jobs/new")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text == index


@pytest.mark.asyncio
async def test_fallback_cannot_serve_files_outside_the_frontend_build(tmp_path, monkeypatch, dashboard_client):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>Dashboard</title>")
    (tmp_path / "outside.txt").write_text("outside build directory")
    monkeypatch.setattr("services.api.app.dist_dir", dist)
    response = await dashboard_client.get("/%2e%2e/outside.txt")
    assert response.status_code == 404
    assert "outside build directory" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/", "/jobs/new", "/index.html"])
async def test_fallback_cannot_follow_an_index_symlink_outside_the_build(tmp_path, monkeypatch, path, dashboard_client):
    dist = tmp_path / "dist"
    dist.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside build directory")
    (dist / "index.html").symlink_to(outside)
    monkeypatch.setattr("services.api.app.dist_dir", dist)
    response = await dashboard_client.get(path)
    assert response.status_code == 404
    assert "outside build directory" not in response.text


@pytest.mark.asyncio
async def test_missing_frontend_build_returns_404(tmp_path, monkeypatch, dashboard_client):
    monkeypatch.setattr("services.api.app.dist_dir", tmp_path / "missing-build")
    response = await dashboard_client.get("/jobs/new")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_invalid_file_path_returns_404(tmp_path, monkeypatch, dashboard_client):
    (tmp_path / "index.html").write_text("<!doctype html><title>Dashboard</title>")
    monkeypatch.setattr("services.api.app.dist_dir", tmp_path)
    response = await dashboard_client.get("/%00.txt")
    assert response.status_code == 404
