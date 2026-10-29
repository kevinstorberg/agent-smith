from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from scripts.shared.paths import bootstrap
bootstrap()

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from scripts.shared.validation import empty_to_none

mcp = FastMCP("meetings - read imported meeting summaries and synchronization status")
_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False)


def _read_summaries(source: str, project: str, after: str, before: str, limit: int, offset: int, query: str | None = None, labels: list[str] | None = None) -> dict:
    from services.meetings.db import list_summaries

    return list_summaries(
        source=empty_to_none(source), project=empty_to_none(project), query=query,
        after=empty_to_none(after), before=empty_to_none(before), limit=limit, offset=offset, labels=labels,
    )


@mcp.tool(annotations=_READ_ONLY)
def meeting_list(source: str = "", project: str = "", after: str = "", before: str = "", limit: int = 20, offset: int = 0, labels: list[str] | None = None) -> dict:
    """List available imported summaries with metadata and provenance.

    Filter by source name, project, and timezone-aware ISO 8601 meeting dates.
    Dates use the calendar start when present, otherwise the source creation time.
    Limit must be 1-100; offset must be nonnegative.
    Labels require all supplied purpose/subject topics, such as security or roadmapping.
    """
    return _read_summaries(source, project, after, before, limit, offset, labels=labels)


@mcp.tool(annotations=_READ_ONLY)
def meeting_get(summary_id: str) -> dict | None:
    """Read an available imported summary by its stable UUID, including revision and provenance."""
    from services.meetings.db import get_summary

    return get_summary(summary_id)


@mcp.tool(annotations=_READ_ONLY)
def meeting_search(query: str, source: str = "", project: str = "", after: str = "", before: str = "", limit: int = 20, offset: int = 0, labels: list[str] | None = None) -> dict:
    """Search imported titles and summary text, ignoring case.

    Query must contain 1-1000 characters. Source, project, date, and paging
    filters follow meeting_list. Returns available summaries and total matches.
    """
    return _read_summaries(source, project, after, before, limit, offset, query=query, labels=labels)


@mcp.tool(annotations=_READ_ONLY)
def meeting_sync_status(source: str = "") -> list[dict]:
    """Read synchronization outcomes, progress counts, completion times, and degraded scan status."""
    from services.meetings.db import source_status

    if source and not source.strip():
        raise ValueError("Meeting source filter must be nonblank")
    return source_status(empty_to_none(source))


if __name__ == "__main__":
    mcp.run()
