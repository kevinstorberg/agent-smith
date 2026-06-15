"""Audit trail of coding-agent tool calls.

A PreToolUse hook calls ``start_event`` to insert a 'pending' row. The matching
PostToolUse hook calls ``complete_event`` to fill in status/result/completed_at on
the latest still-open row for that ``correlation_key``. If no open row matches (a
post that arrived without its pre), a completed row is inserted so nothing is lost.
Append-only: tool_input/created_at are never rewritten.
"""
from __future__ import annotations

from psycopg2.extras import Json

from services.api.models.base import BaseModel
from services.db import get_connection

# Server-side home for the coding-agent list. The host hook derives its own list
# from scripts/audit_hook.py:FIELD_KEYS (it can't import services.*), and the
# tool_call_events CHECK constraint is a frozen snapshot of the same values;
# tests/test_audit_consistency.py pins them together.
AUDIT_AGENTS = ("claude", "codex", "gemini")
COMPLETION_STATUSES = ("success", "error")
LIST_COLUMNS = (
    "id, correlation_key, agent, session_id, tool_name, cwd, project, "
    "status, created_at, completed_at, duration_ms"
)


class ToolCallEventModel(BaseModel):
    table = "tool_call_events"
    json_fields = {"tool_input", "result"}


def start_event(
    agent: str,
    session_id: str,
    tool_name: str,
    correlation_key: str,
    tool_input: dict | None = None,
    cwd: str | None = None,
    project: str | None = None,
) -> int:
    """Insert a 'pending' tool-call row for a PreToolUse event. Returns its id."""
    _validate_agent(agent)
    ToolCallEventModel._validate_required(
        {"session_id": session_id, "tool_name": tool_name, "correlation_key": correlation_key},
        ["session_id", "tool_name", "correlation_key"],
    )
    return ToolCallEventModel.create(
        correlation_key=correlation_key,
        agent=agent,
        session_id=session_id,
        tool_name=tool_name,
        tool_input=tool_input or {},
        cwd=cwd,
        project=project,
        status="pending",
    )


def complete_event(
    correlation_key: str,
    status: str,
    result: object = None,
    duration_ms: int | None = None,
    *,
    agent: str | None = None,
    session_id: str | None = None,
    tool_name: str | None = None,
    tool_input: dict | None = None,
    cwd: str | None = None,
    project: str | None = None,
) -> int:
    """Complete the latest open row for ``correlation_key`` (PostToolUse). Falls back
    to inserting a completed row when no open pre-row exists. Returns the row id.

    ``duration_ms`` is used verbatim when provided (native), otherwise computed from
    ``now() - created_at`` of the matched row.
    """
    assert status in COMPLETION_STATUSES, f"status must be one of {COMPLETION_STATUSES}, got {status!r}"
    assert correlation_key, "correlation_key must not be empty."

    result_json = Json(result) if result is not None else None
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE tool_call_events
                SET status = %s,
                    result = %s,
                    completed_at = now(),
                    duration_ms = COALESCE(%s, (EXTRACT(EPOCH FROM (now() - created_at)) * 1000)::int)
                WHERE id = (
                    SELECT id FROM tool_call_events
                    WHERE correlation_key = %s AND completed_at IS NULL
                    ORDER BY created_at DESC
                    LIMIT 1
                )
                RETURNING id
                """,
                (status, result_json, duration_ms, correlation_key),
            )
            row = cur.fetchone()
            if row:
                return row[0]

            # No open pre-row: record the post as a standalone completed row.
            _validate_agent(agent or "")
            ToolCallEventModel._validate_required(
                {"session_id": session_id, "tool_name": tool_name},
                ["session_id", "tool_name"],
            )
            cur.execute(
                """
                INSERT INTO tool_call_events
                    (correlation_key, agent, session_id, tool_name, tool_input,
                     cwd, project, status, result, completed_at, duration_ms)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s)
                RETURNING id
                """,
                (
                    correlation_key, agent, session_id, tool_name, Json(tool_input or {}),
                    cwd, project, status, result_json, duration_ms,
                ),
            )
            return cur.fetchone()[0]


def list_events(
    agent: str | None = None,
    tool_name: str | None = None,
    session_id: str | None = None,
    project: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """List audit events with optional filters, newest first. Returns (rows, total).

    Omits the large tool_input/result blobs; fetch a single event for full payloads.
    """
    clauses, params = [], []
    for col, val in (
        ("agent", agent),
        ("tool_name", tool_name),
        ("session_id", session_id),
        ("project", project),
        ("status", status),
    ):
        if val:
            clauses.append(f"{col} = %s")
            params.append(val)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return ToolCallEventModel.list(
        columns=LIST_COLUMNS,
        where=where,
        params=tuple(params),
        order_by="created_at DESC",
        limit=limit,
        offset=offset,
    )


def count_by_agent() -> dict[str, int]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT agent, COUNT(*) FROM tool_call_events GROUP BY agent")
            counts = dict(cur.fetchall())
    return {agent: counts.get(agent, 0) for agent in AUDIT_AGENTS}


def prune(before_iso: str) -> int:
    """Delete events created strictly before ``before_iso``. Returns rows deleted."""
    assert before_iso, "before timestamp must not be empty."
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tool_call_events WHERE created_at < %s", (before_iso,))
            return cur.rowcount


def _validate_agent(agent: str) -> None:
    assert agent in AUDIT_AGENTS, f"agent must be one of {AUDIT_AGENTS}, got {agent!r}"


get_event = ToolCallEventModel.read
