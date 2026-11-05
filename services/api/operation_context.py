from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import Request

from services.observability import action_operation, trigger_context


def _request_action(path: str, method: str) -> tuple[str, str]:
    parts = path.strip("/").split("/")
    if len(parts) < 2 or parts[0] != "api":
        return "http", method
    resource, remainder = parts[1], parts[2:]
    if resource == "profiles" and "topics" in remainder:
        resource, remainder = (
            "profile_topic",
            remainder[remainder.index("topics") + 1 :],
        )
    if not remainder or all(
        part.startswith("{") and part.endswith("}") for part in remainder
    ):
        verb = {
            "GET": "read" if remainder else "list",
            "POST": "create",
            "PATCH": "update",
            "PUT": "update",
            "DELETE": "delete",
        }.get(method, method)
    else:
        verb = remainder[-1]
        if verb.startswith("{"):
            verb = "call"
    return resource, verb


async def request_trigger(request: Request) -> AsyncIterator[None]:
    framework_scope = request.scope.get("fastapi", {})
    route = (
        framework_scope.get("effective_route_context")
        if isinstance(framework_scope, dict)
        else None
    )
    route = route or request.scope.get("route")
    path = (
        getattr(route, "path_format", None) or getattr(route, "path", None) or "unknown"
    )
    resource, action = _request_action(path, request.method)
    with (
        trigger_context(
            trigger=f"http.{request.method}", source=path, request_id=str(uuid4())
        ),
        action_operation(resource, action, owner="http"),
    ):
        yield
