"""MCP endpoints keep serving connected agents across a dashboard restart.

Agents hold the Mcp-Session-Id they were issued and keep sending it after the
server restarts; ./run.sh replacing a running instance makes that routine.
"""
from __future__ import annotations

import json
from contextlib import AsyncExitStack

import httpx
import pytest
from starlette.routing import Mount

from services.api.app import MCP_SERVERS, app

SESSION_ID_FROM_PREVIOUS_PROCESS = "0123456789abcdef0123456789abcdef"
MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "Mcp-Session-Id": SESSION_ID_FROM_PREVIOUS_PROCESS,
}


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
async def test_every_mcp_endpoint_serves_a_session_id_from_before_a_restart():
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
