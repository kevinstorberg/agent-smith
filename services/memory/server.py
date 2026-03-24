"""FastMCP HTTP server exposing long-term memory tools to agents."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.shared.paths import bootstrap  # noqa: E402
bootstrap()

from mcp.server.fastmcp import FastMCP  # noqa: E402

import services.memory.db as db

DEFAULT_PORT = 7367

mcp = FastMCP("memory")


@mcp.tool()
def memory_add(content: str, repo: str = "", tags: list[str] | None = None) -> str:
    """
    Store a new memory with optional project scope and tags.

    Args:
        content: The text to remember.
        repo:    Project or repo name to scope this memory (e.g. "agent-smith").
        tags:    Short classification labels (e.g. ["auth", "architecture"]).

    Returns:
        The ID of the newly created memory.
    """
    id = db.add(content=content, repo=repo or None, tags=tags or [])
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
    return db.search(query=query, repo=repo or None, limit=limit)


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
    return db.list_memories(repo=repo or None, limit=limit)


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
        repo=repo or None,
        tags=tags,
    )
    return f"Updated: {id}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    # host/port are set on the FastMCP instance, not passed to run()
    mcp.settings.host = "127.0.0.1"
    mcp.settings.port = args.port

    mcp.run(transport="streamable-http")
