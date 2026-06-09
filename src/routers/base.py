"""Router factory for template users.

NOTE: This utility is intentionally unused by the template's example routes.
When building your application, you can use this to create routers with
consistent configuration, or just use FastAPI's APIRouter directly.

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

    Template utility: Simple wrapper around APIRouter for consistency.
    You can extend this with common middleware, dependencies, or configuration.

    Args:
        prefix: URL prefix for all routes in this router (e.g., "/api/v1/users")
        tags: OpenAPI tags for documentation grouping

    Returns:
        Configured APIRouter instance
    """
    return APIRouter(prefix=prefix, tags=tags or [])
