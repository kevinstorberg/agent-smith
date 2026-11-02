from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.shared.paths import bootstrap  # noqa: E402
bootstrap()

from mcp.server.fastmcp import FastMCP  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402
from pydantic import Field  # noqa: E402
from scripts.shared.validation import empty_to_none  # noqa: E402
from services.api.models.plan import SEARCH_MAX_LIMIT, SEARCH_MAX_OFFSET, SEARCH_MAX_PROJECT_CHARS  # noqa: E402

mcp = FastMCP("plans - save, search, and retrieve Planning Docs")
_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


@mcp.tool()
def save(title: str, body: str, project: str = "") -> str:
    """Save an implementation plan or strategy to the database.
    Use this whenever the agent creates a plan, architectural decision, or multi-step approach.
    Always set project to the current repo/project name.

    Args:
        title: Short descriptive title for the plan.
        body: Full plan content (markdown).
        project: The current project/repo name. Always provide this.

    Returns:
        Confirmation with the plan ID.
    """
    from services.api.models.plan import create_plan
    plan_id = create_plan(title, body, project=empty_to_none(project))
    return f"Plan saved (id={plan_id})"


@mcp.tool(annotations=_READ_ONLY)
def get(plan_id: int = 0, query: str = "") -> dict | list[dict]:
    """Retrieve a full Planning Doc by ID, including its complete markdown body.
    Use after search to inspect relevant plans, decisions, and implementation details.
    The legacy query option searches titles only and returns up to five full documents.

    Args:
        plan_id: Exact plan ID (takes priority over query if > 0).
        query: Fuzzy search term for title (returns up to 5 matches).

    Returns:
        Single plan dict (if plan_id given) or list of matching plans (if query given).
    """
    from services.api.models.plan import get_plan, search_plans
    if plan_id > 0:
        return get_plan(plan_id)
    if query:
        return search_plans(query, limit=5)
    return []


@mcp.tool(annotations=_READ_ONLY)
def search(
    query: Annotated[str, Field(strict=True)],
    project: Annotated[str, Field(strict=True, max_length=SEARCH_MAX_PROJECT_CHARS)] = "",
    status: Annotated[str, Field(strict=True)] = "",
    limit: Annotated[int, Field(strict=True, ge=1, le=SEARCH_MAX_LIMIT)] = 10,
    offset: Annotated[int, Field(strict=True, ge=0, le=SEARCH_MAX_OFFSET)] = 0,
) -> dict[str, Any]:
    """Search saved Planning Docs for context relevant to the agent's current work.
    Matches every whitespace-separated keyword in the title or markdown body, ignoring case.
    This is literal keyword search, not semantic search; %, _ and backslash are literal.
    Results contain metadata and a bounded matching excerpt. Use get(plan_id=...) for the full doc.

    Args:
        query: Nonblank search text, at most 500 characters after trimming and 10 keywords.
        project: Optional exact, case-sensitive project/repo name, at most 200 characters.
        status: Optional draft or final; omitted searches both.
        limit: Maximum documents per page, 1-20; defaults to 10.
        offset: Pagination offset, 0-10000; use next_offset from the previous response.

    Returns:
        items with id, title, project, status, timestamps and an excerpt of at most 600 characters;
        has_more, next_offset and pagination_capped. Ordered by updated_at then id, newest first.
        If pagination_capped is true, narrow the query or project to find more matches.
        Each page reads current saved data; edits between pages can change result positions.
    """
    from services.api.models.plan import search_documents

    return search_documents(query, project=project, status=status, limit=limit, offset=offset)
