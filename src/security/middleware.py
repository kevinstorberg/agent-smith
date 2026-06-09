import json
import math
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from config.models import SecurityHeadersConfig
from src.api.errors import REQUEST_ID_HEADER, ErrorBody, ErrorEnvelope, normalize_request_id
from src.security.headers import apply_security_headers


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int
    remaining: int


class RateLimitBackend(Protocol):
    def check(self, *, identity: str, limit: int, window_seconds: int) -> RateLimitDecision: ...


class InMemoryRateLimitBackend:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    def check(self, *, identity: str, limit: int, window_seconds: int) -> RateLimitDecision:
        now = self._clock()
        window_start = now - window_seconds
        requests = self._requests[identity]

        while requests and requests[0] <= window_start:
            requests.popleft()

        if len(requests) >= limit:
            retry_after = max(1, math.ceil(window_seconds - (now - requests[0])))
            return RateLimitDecision(allowed=False, retry_after_seconds=retry_after, remaining=0)

        requests.append(now)
        return RateLimitDecision(allowed=True, retry_after_seconds=0, remaining=max(0, limit - len(requests)))


class SecurityHeadersMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        headers_config: SecurityHeadersConfig,
        hsts_enabled: bool = False,
    ) -> None:
        self.app = app
        self.headers_config = headers_config
        self.hsts_enabled = hsts_enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.headers_config.enabled:
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                apply_security_headers(
                    MutableHeaders(scope=message),
                    headers_config=self.headers_config,
                    hsts_enabled=self.hsts_enabled,
                )
            await send(message)

        await self.app(scope, receive, send_with_security_headers)


class RequestBodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, *, max_body_bytes: int) -> None:
        if max_body_bytes < 1:
            raise ValueError("max_body_bytes must be positive")
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in {"POST", "PUT", "PATCH", "DELETE"}:
            await self.app(scope, receive, send)
            return

        content_length = _content_length(scope)
        if content_length is not None and content_length > self.max_body_bytes:
            await send_error_response(
                scope,
                send,
                status_code=413,
                code="request_body_too_large",
                message=f"Request body exceeds {self.max_body_bytes} bytes",
            )
            return

        buffered_messages: list[Message] = []
        total_bytes = 0
        while True:
            message = await receive()
            buffered_messages.append(message)
            if message["type"] != "http.request":
                break

            total_bytes += len(message.get("body", b""))
            if total_bytes > self.max_body_bytes:
                await send_error_response(
                    scope,
                    send,
                    status_code=413,
                    code="request_body_too_large",
                    message=f"Request body exceeds {self.max_body_bytes} bytes",
                )
                return

            if not message.get("more_body", False):
                break

        async def replay_receive() -> Message:
            if buffered_messages:
                return buffered_messages.pop(0)
            return await receive()

        await self.app(scope, replay_receive, send)


class RateLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        limit: int,
        window_seconds: int,
        backend: RateLimitBackend | None = None,
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be positive")
        if window_seconds < 1:
            raise ValueError("window_seconds must be positive")
        self.app = app
        self.limit = limit
        self.window_seconds = window_seconds
        self.backend = backend or InMemoryRateLimitBackend()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        decision = self.backend.check(
            identity=_client_identity(scope),
            limit=self.limit,
            window_seconds=self.window_seconds,
        )
        if not decision.allowed:
            await send_error_response(
                scope,
                send,
                status_code=429,
                code="rate_limit_exceeded",
                message="Rate limit exceeded",
                headers={"Retry-After": str(decision.retry_after_seconds)},
            )
            return

        await self.app(scope, receive, send)


async def send_error_response(
    scope: Scope,
    send: Send,
    *,
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
) -> None:
    request_id = _request_id_from_scope(scope)
    content = ErrorEnvelope(error=ErrorBody(code=code, message=message, details=[], request_id=request_id)).model_dump(
        exclude_none=True
    )
    body = json.dumps(content).encode("utf-8")
    response_headers = [
        (b"content-type", b"application/json"),
        (REQUEST_ID_HEADER.lower().encode("latin-1"), request_id.encode("latin-1")),
    ]
    for name, value in (headers or {}).items():
        response_headers.append((name.encode("latin-1"), value.encode("latin-1")))

    await send({"type": "http.response.start", "status": status_code, "headers": response_headers})
    await send({"type": "http.response.body", "body": body})


def _request_id_from_scope(scope: Scope) -> str:
    state = scope.setdefault("state", {})
    request_id = state.get("request_id") if isinstance(state, dict) else None
    if request_id:
        return str(request_id)

    request_id = normalize_request_id(Headers(scope=scope).get(REQUEST_ID_HEADER))
    if isinstance(state, dict):
        state["request_id"] = request_id
    return request_id


def _client_identity(scope: Scope) -> str:
    client = scope.get("client")
    if client:
        return str(client[0])
    return "unknown"


def _content_length(scope: Scope) -> int | None:
    value = Headers(scope=scope).get("content-length")
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None
