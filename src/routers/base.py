"""Shared router factory for Agent Smith API modules.

Use this to create routers with consistent configuration, or use FastAPI's
APIRouter directly when a module needs custom setup.

Example usage:
    from src.routers.base import create_router

    router = create_router(prefix="/api/v1/users", tags=["users"])

    @router.get("/")
    async def list_users():
        return {"users": []}
"""

from fastapi import APIRouter


def create_router(*, prefix: str = "", tags: list[str] | None = None) -> APIRouter:
    """Create a FastAPI router with consistent configuration.

    You can extend this with common middleware, dependencies, or configuration.

    Args:
        prefix: URL prefix for all routes in this router (e.g., "/api/v1/users")
        tags: OpenAPI tags for documentation grouping

    Returns:
        Configured APIRouter instance
    """
    return APIRouter(prefix=prefix, tags=tags or [])
