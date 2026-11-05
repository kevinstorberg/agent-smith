from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import Request

from services.observability import trigger_context


async def request_trigger(request: Request) -> AsyncIterator[None]:
    route = request.scope.get("route")
    path = getattr(route, "path", "unknown")
    with trigger_context(
        trigger=f"http.{request.method}", source=path, request_id=str(uuid4())
    ):
        yield
