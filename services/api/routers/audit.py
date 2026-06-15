"""REST API for the coding-agent tool-call audit trail.

``POST /events`` is the trust boundary: it is the only writer, called by the
PreToolUse/PostToolUse hooks. It validates enums, coerces types, and caps oversized
payload fields before anything reaches the DB. The GET endpoints power the read-only
dashboard.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from services.api.models.audit import (
    AUDIT_AGENTS,
    COMPLETION_STATUSES,
    complete_event,
    count_by_agent,
    get_event,
    list_events,
    prune,
    start_event,
)
from services.api.routers.base import list_response, require_found

router = APIRouter()

# Cap any single string leaf so a giant file body / command can't bloat a row.
# Mirrors scripts/audit_hook.py:_cap / MAX_FIELD_CHARS (host/server boundary — the
# host hook can't import services.*); behavioral parity is pinned by
# tests/test_audit_consistency.py.
MAX_FIELD_CHARS = 8192


class EventIn(BaseModel):
    phase: str
    agent: str
    session_id: str
    tool_name: str
    correlation_key: str
    tool_input: dict = {}
    cwd: str | None = None
    project: str | None = None
    status: str | None = None
    result: object | None = None
    duration_ms: int | None = None


def _cap(value):
    """Truncate oversized string leaves in a JSON-serializable payload."""
    if isinstance(value, dict):
        return {k: _cap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_cap(v) for v in value]
    if isinstance(value, str) and len(value) > MAX_FIELD_CHARS:
        return value[:MAX_FIELD_CHARS] + f"...[truncated {len(value) - MAX_FIELD_CHARS} chars]"
    return value


def _check_token(token: str | None) -> None:
    """Optional shared-secret gate. No-op unless AUDIT_INGEST_TOKEN is configured."""
    expected = os.environ.get("AUDIT_INGEST_TOKEN")
    if expected and token != expected:
        raise HTTPException(status_code=401, detail="invalid audit ingest token")


@router.post("/events", status_code=201)
def ingest(body: EventIn, x_audit_token: str | None = Header(default=None)):
    _check_token(x_audit_token)
    if body.agent not in AUDIT_AGENTS:
        raise HTTPException(status_code=422, detail=f"agent must be one of {AUDIT_AGENTS}")

    tool_input = _cap(body.tool_input or {})
    if body.phase == "pre":
        event_id = start_event(
            agent=body.agent,
            session_id=body.session_id,
            tool_name=body.tool_name,
            correlation_key=body.correlation_key,
            tool_input=tool_input,
            cwd=body.cwd,
            project=body.project,
        )
    elif body.phase == "post":
        if body.status not in COMPLETION_STATUSES:
            raise HTTPException(status_code=422, detail=f"status must be one of {COMPLETION_STATUSES}")
        event_id = complete_event(
            body.correlation_key,
            status=body.status,
            result=_cap(body.result) if body.result is not None else None,
            duration_ms=body.duration_ms,
            agent=body.agent,
            session_id=body.session_id,
            tool_name=body.tool_name,
            tool_input=tool_input,
            cwd=body.cwd,
            project=body.project,
        )
    else:
        raise HTTPException(status_code=422, detail="phase must be 'pre' or 'post'")

    return {"id": event_id}


@router.get("/events")
def list_all(
    agent: str | None = Query(None),
    tool_name: str | None = Query(None),
    session_id: str | None = Query(None),
    project: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    items, total = list_events(
        agent=agent,
        tool_name=tool_name,
        session_id=session_id,
        project=project,
        status=status,
        limit=limit,
        offset=offset,
    )
    return list_response(items, total)


@router.get("/counts")
def counts():
    return count_by_agent()


@router.get("/events/{event_id}")
def get_one(event_id: int):
    return require_found(get_event(event_id), "Event", event_id)


@router.delete("/events")
def prune_events(before: str = Query(..., description="ISO timestamp; delete events created before it")):
    deleted = prune(before)
    return {"deleted": deleted}
