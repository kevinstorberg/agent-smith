from starlette.types import ASGIApp, Message, Receive, Scope, Send


class MCPSSECompletionMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        streaming_sse = False
        complete = False
        disconnected = False

        async def tracked_receive() -> Message:
            nonlocal disconnected
            message = await receive()
            if message["type"] == "http.disconnect":
                disconnected = True
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal streaming_sse, complete
            await send(message)
            if message["type"] == "http.response.start":
                streaming_sse = 200 <= message["status"] < 300 and any(
                    name.lower() == b"content-type" and value.partition(b";")[0].strip().lower() == b"text/event-stream"
                    for name, value in message.get("headers", [])
                )
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                complete = True

        await self.app(scope, tracked_receive, tracked_send)
        # The SDK's SSE shutdown cancels its stream task before its final body.
        # Finish HTTP framing only after the mounted handler returns normally.
        if streaming_sse and not complete and not disconnected:
            await send({"type": "http.response.body", "body": b"", "more_body": False})
