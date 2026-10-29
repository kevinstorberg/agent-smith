import asyncio
import logging

import pytest
from uvicorn.protocols.utils import get_path_with_query_string

from services.api.access_logging import MCPProbeContextMiddleware, configure_mcp_access_logging
from tests.test_mcp_access_logging import access_logger as access_logger, emit

ENDPOINT = "/mcp/memory/"
BODY = b'{"error":"synthetic negotiation error"}'


def scope(path=ENDPOINT, *, method="GET", accept=None, query=b""):
    return {
        "type": "http", "method": method, "path": path, "raw_path": path.encode(),
        "query_string": query, "headers": [(b"accept", accept)] if accept is not None else [],
    }


async def respond(scope, receive, send, status=406):
    await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": BODY})


async def request(app, scope, logger, *, level=logging.INFO):
    messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            emit(logger, get_path_with_query_string(scope), method=scope["method"], status=message["status"], level=level)
        messages.append(message)

    await app(scope, receive, send)
    return messages


@pytest.mark.asyncio
@pytest.mark.parametrize("accept", [None, b"*/*", b"application/json"])
@pytest.mark.parametrize("debug", [False, True])
async def test_missing_sse_probe_keeps_response_and_is_only_logged_at_debug(access_logger, caplog, accept, debug):
    if debug:
        caplog.set_level(logging.DEBUG, logger="uvicorn.access")
    app = MCPProbeContextMiddleware(respond, {"/mcp/memory": False})
    messages = await request(app, scope(accept=accept), access_logger)
    assert messages == [
        {"type": "http.response.start", "status": 406, "headers": [(b"content-type", b"application/json")]},
        {"type": "http.response.body", "body": BODY},
    ]
    if debug:
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.name == "uvicorn.access.expected_probe" and record.levelno == logging.DEBUG
        assert record.expected_probe is True
        assert record.args == ("127.0.0.1:1234", "GET", ENDPOINT, "1.1", 406)
    else:
        assert not caplog.records
    caplog.clear()
    emit(access_logger, ENDPOINT, status=406)
    assert len(caplog.records) == 1 and caplog.records[0].name == "uvicorn.access"


@pytest.mark.asyncio
@pytest.mark.parametrize("path,method,accept,query,authenticated", [
    (ENDPOINT, "GET", b"text/event-stream", b"", False),
    (ENDPOINT, "GET", b"application/json, text/event-stream", b"", False),
    (ENDPOINT, "GET", b"TEXT/EVENT-STREAM", b"", False),
    (ENDPOINT, "GET", b"text/event-stream;q=0", b"", False),
    (ENDPOINT, "GET", b"text/event-stream-invalid", b"", False),
    (ENDPOINT, "POST", b"application/json", b"", False),
    (ENDPOINT, "HEAD", b"application/json", b"", False),
    (ENDPOINT, "GET", b"application/json", b"unexpected=value", False),
    (ENDPOINT, "GET", b"application/json", b"", True),
    ("/mcp/unknown/", "GET", b"application/json", b"", False),
    (ENDPOINT + "nested", "GET", b"application/json", b"", False),
    ("/api/profiles", "GET", b"application/json", b"", False),
])
async def test_other_negotiation_failures_stay_visible(access_logger, caplog, path, method, accept, query, authenticated):
    app = MCPProbeContextMiddleware(respond, {"/mcp/memory": authenticated})
    await request(app, scope(path, method=method, accept=accept, query=query), access_logger)
    assert len(caplog.records) == 1 and caplog.records[0].name == "uvicorn.access"
    assert not hasattr(caplog.records[0], "expected_probe")


@pytest.mark.asyncio
@pytest.mark.parametrize("status,level", [(200, logging.INFO), (400, logging.INFO), (401, logging.INFO), (403, logging.INFO), (404, logging.INFO), (500, logging.INFO), (406, logging.WARNING), (406, logging.ERROR)])
async def test_marked_request_keeps_other_statuses_and_severities_visible(access_logger, caplog, status, level):
    async def app(scope, receive, send):
        await respond(scope, receive, send, status)

    await request(MCPProbeContextMiddleware(app, {"/mcp/memory": False}), scope(), access_logger, level=level)
    assert len(caplog.records) == 1
    assert caplog.records[0].name == "uvicorn.access" and caplog.records[0].levelno == level


@pytest.mark.asyncio
async def test_logging_configuration_cannot_quiet_a_now_authenticated_endpoint(access_logger, caplog):
    configure_mcp_access_logging({"/mcp/memory": True})
    await request(MCPProbeContextMiddleware(respond, {"/mcp/memory": False}), scope(), access_logger)
    assert len(caplog.records) == 1 and caplog.records[0].name == "uvicorn.access"


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RuntimeError, asyncio.CancelledError])
async def test_request_context_resets_after_failure_and_cancellation(access_logger, caplog, error):
    async def failed(scope, receive, send):
        raise error("synthetic interruption")

    with pytest.raises(error):
        await request(MCPProbeContextMiddleware(failed, {"/mcp/memory": False}), scope(), access_logger)
    emit(access_logger, ENDPOINT, status=406)
    assert len(caplog.records) == 1 and caplog.records[0].name == "uvicorn.access"


@pytest.mark.asyncio
async def test_concurrent_requests_do_not_share_probe_classification(access_logger, caplog):
    caplog.set_level(logging.DEBUG, logger="uvicorn.access")
    marked_entered, sse_entered, release_sse = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def overlapped(scope, receive, send):
        if not scope["headers"]:
            marked_entered.set()
            await asyncio.wait_for(sse_entered.wait(), 2)
        else:
            sse_entered.set()
            await asyncio.wait_for(release_sse.wait(), 2)
        await respond(scope, receive, send)

    app = MCPProbeContextMiddleware(overlapped, {"/mcp/memory": False})
    marked = asyncio.create_task(request(app, scope(), access_logger))
    await asyncio.wait_for(marked_entered.wait(), 2)
    proper_sse = asyncio.create_task(request(app, scope(accept=b"text/event-stream"), access_logger))
    try:
        await marked
    finally:
        release_sse.set()
        await proper_sse
    assert [(record.name, record.levelno) for record in caplog.records] == [
        ("uvicorn.access.expected_probe", logging.DEBUG), ("uvicorn.access", logging.INFO),
    ]
    emit(access_logger, ENDPOINT, status=406)
    assert caplog.records[-1].name == "uvicorn.access"
