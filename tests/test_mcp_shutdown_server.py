from __future__ import annotations

import http.client
import json
import signal
import time

import pytest

from tests.native_uvicorn import owned_uvicorn


SERVER = """
import sys
import uvicorn

def factory():
    import signal
    from contextlib import asynccontextmanager
    import anyio
    from mcp.server.fastmcp import FastMCP
    from sse_starlette.sse import AppStatus
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Mount, Route

    assert signal.getsignal(signal.SIGTERM).__self__.__class__ is uvicorn.Server
    assert signal.getsignal(signal.SIGTERM).__func__ is not AppStatus.handle_exit
    assert not AppStatus.should_exit
    server = FastMCP("shutdown-canary", stateless_http=True, streamable_http_path="/")
    state = {"tool_started": False}

    @server.tool()
    async def pending() -> str:
        state["tool_started"] = True
        await anyio.sleep_forever()
        return "unreachable"

    async def health(request):
        return JSONResponse(state)

    @asynccontextmanager
    async def lifespan(app):
        async with server.session_manager.run():
            yield
        print("CANARY_GLOBAL_EXIT_FLAG=" + str(AppStatus.should_exit), flush=True)
        print("CANARY_LIFESPAN_STOPPED", flush=True)

    mounted = server.streamable_http_app()
    from services.api.mcp_transport import MCPSSECompletionMiddleware
    mounted.add_middleware(MCPSSECompletionMiddleware)
    return Starlette(routes=[Route("/health", health), Mount("/mcp/canary", app=mounted)], lifespan=lifespan)

uvicorn.run("__main__:factory", factory=True, fd=int(sys.argv[1]), http=sys.argv[2],
            log_level=sys.argv[3], use_colors=False, timeout_graceful_shutdown=5)
"""


def _wait_for_tool(port: int) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=0.2)
        try:
            connection.request("GET", "/health")
            response = connection.getresponse()
            if json.loads(response.read())["tool_started"]:
                return
        finally:
            connection.close()
        time.sleep(0.02)
    pytest.fail("Owned canary did not enter its synthetic pending tool within 5 seconds")


@pytest.mark.parametrize("protocol", ["h11", "httptools"])
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_real_mcp_stream_completes_http_framing_on_sigterm(tmp_path, protocol, method):
    output = tmp_path / f"shutdown-{protocol}-{method}.log"
    with owned_uvicorn(SERVER, output, protocol) as server:
        connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=8)
        try:
            headers = {"Accept": "application/json, text/event-stream", "Mcp-Protocol-Version": "2025-11-25"}
            body = None
            if method == "POST":
                headers["Content-Type"] = "application/json"
                body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "pending", "arguments": {}}})
            connection.request(method, "/mcp/canary/", body=body, headers=headers)
            response = connection.getresponse()
            assert response.status == 200
            assert response.getheader("Content-Type").startswith("text/event-stream")
            assert response.chunked
            if method == "POST":
                _wait_for_tool(server.port)
            assert connection.sock is not None and connection.sock.fileno() >= 0
            assert server.process.poll() is None
            server.stop()
            log = output.read_text()
            try:
                response.read()
            except http.client.IncompleteRead as error:
                pytest.fail(f"MCP stream lacked its terminal HTTP chunk: {error}; server log: {log}")
            assert server.process.returncode == -signal.SIGTERM
            assert "CANARY_GLOBAL_EXIT_FLAG=False" in log
            assert "CANARY_LIFESPAN_STOPPED" in log
            assert "ERROR:" not in log
            assert "ASGI callable returned without completing response" not in log
        finally:
            connection.close()
