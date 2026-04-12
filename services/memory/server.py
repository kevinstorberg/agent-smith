from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.shared.paths import bootstrap  # noqa: E402
bootstrap()

from mcp.server.fastmcp import FastMCP  # noqa: E402
from scripts.shared.validation import empty_to_none  # noqa: E402

import services.memory.db as db

mcp = FastMCP("memory - store and search observations, learnings, and context")


@mcp.tool()
def memory_add(content: str, repo: str = "", tags: list[str] | None = None) -> str:
    """
    Store an observation, learning, or context note.
    NOT for implementation plans or strategies — use the plans server's save tool instead.

    Args:
        content: The text to remember.
        repo:    Project or repo name to scope this memory (e.g. "agent-smith").
        tags:    Short classification labels (e.g. ["auth", "architecture"]).

    Returns:
        The ID of the newly created memory.
    """
    id = db.add(content=content, repo=empty_to_none(repo), tags=tags or [])
    return id


@mcp.tool()
def memory_search(query: str, repo: str = "", limit: int = db.DEFAULT_LIMIT) -> list[dict]:
    """
    Semantically search memories using vector similarity.

    Args:
        query:  Natural language search query.
        repo:   Restrict results to this project/repo (optional).
        limit:  Maximum number of results to return.

    Returns:
        List of matching memories ordered by relevance, each with id, content,
        repo, tags, score, created_at, updated_at.
    """
    return db.search(query=query, repo=empty_to_none(repo), limit=limit)


@mcp.tool()
def memory_list(repo: str = "", limit: int = db.DEFAULT_LIMIT) -> list[dict]:
    """
    List recent memories, newest first.

    Args:
        repo:   Filter to this project/repo (optional).
        limit:  Maximum number of memories to return.

    Returns:
        List of memories with id, content, repo, tags, created_at, updated_at.
    """
    return db.list_memories(repo=empty_to_none(repo), limit=limit)


@mcp.tool()
def memory_delete(id: str) -> str:
    """
    Delete a memory by its ID.

    Args:
        id: The memory ID to delete.

    Returns:
        Confirmation message.
    """
    db.delete(id)
    return f"Deleted: {id}"


@mcp.tool()
def memory_update(
    id: str,
    content: str = "",
    repo: str = "",
    tags: list[str] | None = None,
) -> str:
    """
    Update an existing memory's content, repo, or tags.
    Only the fields you provide will be changed.

    Args:
        id:      The memory ID to update.
        content: New content (re-embeds if changed).
        repo:    New project/repo scope.
        tags:    New tag list.

    Returns:
        Confirmation message.
    """
    db.update(
        id=id,
        content=content or None,
        repo=empty_to_none(repo),
        tags=tags,
    )
    return f"Updated: {id}"
