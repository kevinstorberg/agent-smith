import http.client
import json
import os
from pathlib import Path
import random
import socket
import subprocess
import sys
import time

import pytest

SERVER = """
from http import HTTPStatus
import sys

from starlette.responses import JSONResponse
import uvicorn

from services.api.access_logging import MCPProbeContextMiddleware, configure_mcp_access_logging

mounts = {"/mcp/graphs": False, "/mcp/private": True}
configure_mcp_access_logging(mounts)

async def respond(scope, receive, send):
    path = scope["path"]
    status = HTTPStatus.OK if path == "/health" else (
        HTTPStatus.INTERNAL_SERVER_ERROR if path == "/api/failure" else (
            HTTPStatus.NOT_FOUND if ".well-known" in path else HTTPStatus.NOT_ACCEPTABLE
        )
    )
    await JSONResponse({"status_type": type(status).__name__, "path": path}, status_code=status)(scope, receive, send)

uvicorn.run(MCPProbeContextMiddleware(respond, mounts), fd=int(sys.argv[1]),
            http=sys.argv[2], log_level=sys.argv[3], lifespan="off", use_colors=False)
"""


def _request(port, path, *, method="GET", accept="application/json", timeout=1):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request(method, path, headers={"Accept": accept})
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


@pytest.fixture
def server(request, tmp_path):
    protocol, level = request.param
    output = tmp_path / "uvicorn.log"
    with socket.socket() as listener, output.open("w") as log:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        env = {key: os.environ[key] for key in ("PATH", "TMPDIR", "TMP", "TEMP") if key in os.environ}
        env.update(AGENT_SMITH_AUTOMATED_TESTS="1", PYTHONUNBUFFERED="1", APP_ENV="test")
        process = subprocess.Popen(
            [sys.executable, "-c", SERVER, str(listener.fileno()), protocol, level],
            cwd=Path(__file__).resolve().parents[1], env=env, pass_fds=(listener.fileno(),),
            stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            deadline, delay, last_error = time.monotonic() + 8, 0.02, "not started"
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    pytest.fail(f"Owned Uvicorn exited with {process.returncode}: {output.read_text()}")
                try:
                    status, _ = _request(port, "/health", timeout=0.2)
                    if status == 200:
                        break
                    last_error = f"health returned {status}"
                except (OSError, http.client.HTTPException) as error:
                    last_error = type(error).__name__
                time.sleep(delay * random.uniform(0.8, 1.2))
                delay = min(delay * 2, 0.2)
            else:
                pytest.fail(f"Owned Uvicorn did not become ready within 8 seconds ({last_error}): {output.read_text()}")
            yield port, output, level
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)


@pytest.mark.parametrize("server", [(protocol, level) for protocol in ("h11", "httptools") for level in ("info", "debug")], indirect=True)
def test_real_uvicorn_classifies_enum_status_probes_and_preserves_other_failures(server):
    port, output, level = server
    status, body = _request(port, "/mcp/graphs/")
    assert status == 406 and body == {"status_type": "HTTPStatus", "path": "/mcp/graphs/"}
    status, body = _request(port, "/.well-known/oauth-protected-resource/mcp/graphs")
    assert status == 404 and body["status_type"] == "HTTPStatus"

    for path, method, accept, expected in [
        ("/mcp/graphs/", "GET", "text/event-stream", 406),
        ("/mcp/graphs/", "POST", "application/json", 406),
        ("/mcp/graphs/?unexpected=value", "GET", "application/json", 406),
        ("/mcp/private/", "GET", "application/json", 406),
        ("/mcp/unknown/", "GET", "application/json", 406),
        ("/.well-known/oauth-protected-resource/mcp/private", "GET", "application/json", 404),
        ("/api/failure", "GET", "application/json", 500),
    ]:
        status, body = _request(port, path, method=method, accept=accept)
        assert status == expected and body["status_type"] == "HTTPStatus"

    lines = output.read_text().splitlines()
    endpoint_lines = [line for line in lines if '"GET /mcp/graphs/ HTTP/1.1" 406' in line]
    assert len(endpoint_lines) == (2 if level == "debug" else 1)
    assert sum(line.startswith("INFO:") for line in endpoint_lines) == 1
    assert sum(line.startswith("DEBUG:") for line in endpoint_lines) == (1 if level == "debug" else 0)
    discovery_lines = [line for line in lines if '"GET /.well-known/oauth-protected-resource/mcp/graphs HTTP/1.1" 404' in line]
    assert len(discovery_lines) == (1 if level == "debug" else 0)
    assert all(line.startswith("DEBUG:") for line in discovery_lines)
    for marker in (
        '"POST /mcp/graphs/ HTTP/1.1" 406',
        '"GET /mcp/graphs/?unexpected=value HTTP/1.1" 406',
        '"GET /mcp/private/ HTTP/1.1" 406',
        '"GET /mcp/unknown/ HTTP/1.1" 406',
        '"GET /.well-known/oauth-protected-resource/mcp/private HTTP/1.1" 404',
        '"GET /api/failure HTTP/1.1" 500',
    ):
        assert any(line.startswith("INFO:") and marker in line for line in lines), marker
