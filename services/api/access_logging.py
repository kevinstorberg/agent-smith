from __future__ import annotations

import logging
from collections.abc import Mapping
from contextvars import ContextVar

from starlette.types import ASGIApp, Receive, Scope, Send

_DISCOVERY_DOCUMENTS = ("oauth-protected-resource", "oauth-authorization-server", "openid-configuration")
_missing_sse_path: ContextVar[str | None] = ContextVar("mcp_missing_sse_path", default=None)


def _unauthenticated_endpoints(authenticated_mounts: Mapping[str, bool]) -> set[str]:
    return {path for mount, authenticated in authenticated_mounts.items() if not authenticated for path in (mount, mount + "/")}


class MCPProbeContextMiddleware:
    def __init__(self, app: ASGIApp, authenticated_mounts: Mapping[str, bool]) -> None:
        self.app = app
        self.endpoints = _unauthenticated_endpoints(authenticated_mounts)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # A header mentioning SSE stays visible even if the SDK rejects its syntax.
        mentions_sse = any(b"text/event-stream" in value.lower() for key, value in scope["headers"] if key.lower() == b"accept")
        expected = scope["method"] == "GET" and scope["path"] in self.endpoints and not scope["query_string"] and not mentions_sse
        token = _missing_sse_path.set(scope["path"] if expected else None)
        try:
            await self.app(scope, receive, send)
        finally:
            _missing_sse_path.reset(token)


class ExpectedMCPProbeFilter(logging.Filter):
    def __init__(self, authenticated_mounts: Mapping[str, bool]) -> None:
        super().__init__()
        self.endpoints = _unauthenticated_endpoints(authenticated_mounts)
        self.paths = {
            path
            for mount, authenticated in authenticated_mounts.items() if not authenticated
            for document in _DISCOVERY_DOCUMENTS
            for path in (f"{mount}/.well-known/{document}", f"/.well-known/{document}{mount}")
        }
        if authenticated_mounts and not any(authenticated_mounts.values()):
            self.paths.update(f"/.well-known/{document}" for document in _DISCOVERY_DOCUMENTS)
        self.debug_logger = logging.getLogger("uvicorn.access.expected_probe")

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "uvicorn.access" or record.levelno != logging.INFO or not isinstance(record.args, tuple) or len(record.args) != 5:
            return True
        _, method, path, _, status = record.args
        if method != "GET" or not isinstance(path, str) or not isinstance(status, int) or isinstance(status, bool):
            return True
        discovery = status == 404 and path in self.paths
        missing_sse = status == 406 and path in self.endpoints and _missing_sse_path.get() == path
        if not discovery and not missing_sse:
            return True
        # Preserve Uvicorn's five access fields for its formatter and structured handlers.
        self.debug_logger.debug("[expected_probe] " + str(record.msg), *record.args, extra={"expected_probe": True})
        return False


def configure_mcp_access_logging(authenticated_mounts: Mapping[str, bool]) -> None:
    logger = logging.getLogger("uvicorn.access")
    for current in tuple(logger.filters):
        if isinstance(current, ExpectedMCPProbeFilter):
            logger.removeFilter(current)
    logger.addFilter(ExpectedMCPProbeFilter(authenticated_mounts))
