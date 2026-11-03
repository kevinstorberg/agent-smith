import asyncio

import pytest

from services.api.mcp_transport import MCPSSECompletionMiddleware


SSE_START = {
    "type": "http.response.start",
    "status": 200,
    "headers": [(b"content-type", b"text/event-stream; charset=utf-8")],
}
CHUNK = {"type": "http.response.body", "body": b"data: fixture\r\n\r\n", "more_body": True}
END = {"type": "http.response.body", "body": b"", "more_body": False}


async def receive_request():
    return {"type": "http.request", "body": b"", "more_body": False}


async def run_app(app, *, scope=None, receive=receive_request):
    messages = []

    async def send(message):
        messages.append(message)

    await MCPSSECompletionMiddleware(app)(scope or {"type": "http", "method": "GET"}, receive, send)
    return messages


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("content_type", [b"text/event-stream", b"Text/Event-Stream; charset=utf-8"])
async def test_normal_return_finishes_an_open_sse_response_once(method, content_type):
    start = {**SSE_START, "headers": [(b"Content-Type", content_type)]}

    async def app(scope, receive, send):
        await send(start)
        await send(CHUNK)

    messages = await run_app(app, scope={"type": "http", "method": method})
    assert messages == [start, CHUNK, END]
    assert messages[0] is start and messages[1] is CHUNK


@pytest.mark.asyncio
@pytest.mark.parametrize("end", [END, {"type": "http.response.body", "body": b"last"}])
async def test_already_complete_sse_is_passed_through_without_another_final_body(end):
    async def app(scope, receive, send):
        await send(SSE_START)
        await send(CHUNK)
        await send(end)

    assert await run_app(app) == [SSE_START, CHUNK, end]


@pytest.mark.asyncio
async def test_observed_client_disconnect_does_not_send_a_final_body():
    disconnected = {"type": "http.disconnect"}

    async def receive():
        return disconnected

    async def app(scope, receive, send):
        await send(SSE_START)
        await send(CHUNK)
        assert await receive() is disconnected

    assert await run_app(app, receive=receive) == [SSE_START, CHUNK]


@pytest.mark.asyncio
async def test_request_body_is_forwarded_without_changes():
    request = {"type": "http.request", "body": b'{"method":"tools/list"}', "more_body": False}

    async def receive():
        return request

    async def app(scope, receive, send):
        assert await receive() is request
        await send(SSE_START)

    assert await run_app(app, receive=receive) == [SSE_START, END]


@pytest.mark.asyncio
@pytest.mark.parametrize("start", [
    {**SSE_START, "headers": [(b"content-type", b"application/json")]},
    {**SSE_START, "headers": [(b"content-type", b"text/event-streaming")]},
    {**SSE_START, "headers": []},
    {**SSE_START, "status": 500},
])
async def test_non_sse_or_unsuccessful_responses_are_not_completed(start):
    async def app(scope, receive, send):
        await send(start)
        await send(CHUNK)

    assert await run_app(app) == [start, CHUNK]


@pytest.mark.asyncio
async def test_app_returning_without_start_is_not_given_a_response():
    async def app(scope, receive, send):
        return

    assert await run_app(app) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RuntimeError("fixture failure"), asyncio.CancelledError("fixture cancellation")])
async def test_application_errors_and_cancellation_propagate_without_completion(error):
    messages = []

    async def send(message):
        messages.append(message)

    async def app(scope, receive, send):
        await send(SSE_START)
        await send(CHUNK)
        raise error

    with pytest.raises(type(error)) as raised:
        await MCPSSECompletionMiddleware(app)({"type": "http", "method": "GET"}, receive_request, send)
    assert raised.value is error
    assert messages == [SSE_START, CHUNK]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_message", [SSE_START, CHUNK, END])
async def test_send_errors_propagate_without_a_second_send(failure_message):
    error = OSError("fixture socket failure")
    messages = []

    async def send(message):
        messages.append(message)
        if message == failure_message:
            raise error

    async def app(scope, receive, send):
        await send(SSE_START)
        await send(CHUNK)

    with pytest.raises(OSError) as raised:
        await MCPSSECompletionMiddleware(app)({"type": "http", "method": "GET"}, receive_request, send)
    assert raised.value is error
    assert messages == [SSE_START, CHUNK, END][:messages.index(failure_message) + 1]


@pytest.mark.asyncio
async def test_a_rejected_start_does_not_mark_the_response_as_started():
    attempts = []

    async def send(message):
        attempts.append(message)
        raise OSError("start rejected")

    async def app(scope, receive, send):
        with pytest.raises(OSError):
            await send(SSE_START)

    await MCPSSECompletionMiddleware(app)({"type": "http", "method": "GET"}, receive_request, send)
    assert attempts == [SSE_START]


@pytest.mark.asyncio
async def test_a_rejected_final_body_does_not_mark_the_response_as_complete():
    attempts, successful = [], []

    async def send(message):
        attempts.append(message)
        if message == END and attempts.count(END) == 1:
            raise OSError("first final body rejected")
        successful.append(message)

    async def app(scope, receive, send):
        await send(SSE_START)
        with pytest.raises(OSError):
            await send(END)

    await MCPSSECompletionMiddleware(app)({"type": "http", "method": "GET"}, receive_request, send)
    assert attempts == [SSE_START, END, END]
    assert successful == [SSE_START, END]


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["lifespan", "websocket"])
async def test_other_asgi_protocols_keep_their_original_call_arguments(protocol):
    scope = {"type": protocol}

    async def send(message):
        pytest.fail("the fixture does not send messages")

    async def app(actual_scope, actual_receive, actual_send):
        assert actual_scope is scope
        assert actual_receive is receive_request
        assert actual_send is send

    await MCPSSECompletionMiddleware(app)(scope, receive_request, send)


@pytest.mark.asyncio
async def test_concurrent_requests_keep_completion_and_disconnect_state_separate():
    ready = asyncio.Event()
    arrived = 0

    async def app(scope, receive, send):
        nonlocal arrived
        start = SSE_START if scope["path"] != "/json" else {**SSE_START, "headers": []}
        await send(start)
        await send(CHUNK)
        if scope["path"] == "/disconnected":
            await receive()
        elif scope["path"] == "/complete":
            await send(END)
        arrived += 1
        if arrived == 4:
            ready.set()
        await ready.wait()

    middleware = MCPSSECompletionMiddleware(app)

    async def request(path):
        messages = []

        async def receive():
            return {"type": "http.disconnect"}

        async def send(message):
            messages.append(message)

        await middleware({"type": "http", "method": "GET", "path": path}, receive, send)
        return messages

    async with asyncio.timeout(1):
        incomplete, complete, disconnected, non_sse = await asyncio.gather(
            *(request(path) for path in ("/open", "/complete", "/disconnected", "/json")),
        )
    assert incomplete == complete == [SSE_START, CHUNK, END]
    assert disconnected == [SSE_START, CHUNK]
    assert non_sse == [{**SSE_START, "headers": []}, CHUNK]
