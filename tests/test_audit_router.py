"""REST router tests for the audit trail (tracer bullet 3).

Calls route handlers directly, per repo convention.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from services.api.models.audit import get_event
from services.api.routers.audit import (
    EventIn,
    counts,
    get_one,
    ingest,
    list_all,
    prune_events,
)
from tests.conftest import audit_cleanup

SID = "audittest-router"

_clean_events = audit_cleanup("audittest-%")


def _pre(correlation_key="toolu_r1", tool_input=None, **over):
    fields = dict(
        phase="pre", agent="claude", session_id=SID, tool_name="Bash",
        correlation_key=correlation_key, tool_input=tool_input or {"command": "ls"},
    )
    fields.update(over)
    return ingest(EventIn(**fields))


def _list(**over):
    # Direct handler calls don't resolve FastAPI Query() defaults, so pass them explicitly.
    params = dict(agent=None, tool_name=None, session_id=SID, project=None, status=None, limit=50, offset=0)
    params.update(over)
    return list_all(**params)


def test_ingest_pre_then_post_updates_same_row():
    pre_id = _pre()["id"]
    post_id = ingest(EventIn(
        phase="post", agent="claude", session_id=SID, tool_name="Bash",
        correlation_key="toolu_r1", status="success", result={"stdout": "ok"}, duration_ms=12,
    ))["id"]

    assert post_id == pre_id
    event = get_event(pre_id)
    assert event["status"] == "success"
    assert event["result"] == {"stdout": "ok"}
    assert event["duration_ms"] == 12


def test_ingest_caps_oversized_string_fields():
    huge = "x" * 20000
    row_id = _pre(correlation_key="toolu_cap", tool_input={"command": huge})["id"]
    stored = get_event(row_id)["tool_input"]["command"]
    assert len(stored) < 9000
    assert stored.endswith("chars]")


def test_ingest_rejects_bad_enums_and_phase():
    with pytest.raises(HTTPException) as e1:
        ingest(EventIn(phase="pre", agent="rogue", session_id=SID, tool_name="Bash", correlation_key="x"))
    assert e1.value.status_code == 422

    with pytest.raises(HTTPException) as e2:
        ingest(EventIn(phase="post", agent="claude", session_id=SID, tool_name="Bash",
                       correlation_key="x", status="pending"))
    assert e2.value.status_code == 422

    with pytest.raises(HTTPException) as e3:
        ingest(EventIn(phase="sideways", agent="claude", session_id=SID, tool_name="Bash", correlation_key="x"))
    assert e3.value.status_code == 422


def test_list_filters_counts_and_detail():
    _pre(correlation_key="a", tool_name="Bash")
    _pre(correlation_key="b", tool_name="Read", agent="codex")

    resp = _list()
    assert resp["total"] == 2

    filtered = _list(agent="codex")
    assert filtered["total"] == 1 and filtered["items"][0]["tool_name"] == "Read"

    all_counts = counts()
    assert all_counts["claude"] >= 1 and set(all_counts) == {"claude", "codex", "gemini"}

    detail = get_one(filtered["items"][0]["id"])
    assert detail["tool_name"] == "Read"


def test_get_one_missing_raises_404():
    with pytest.raises(HTTPException) as e:
        get_one(99999999)
    assert e.value.status_code == 404


def test_prune_endpoint_deletes():
    _pre(correlation_key="prune1")
    result = prune_events(before="2999-01-01T00:00:00+00:00")
    assert result["deleted"] >= 1
    assert _list()["total"] == 0
