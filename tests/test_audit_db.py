"""Audit-trail model: start/complete/list/count/prune (tracer bullet 2).

Everything runs against the real DB; rows are namespaced by session_id and
cleaned up after each test.
"""
from __future__ import annotations

import pytest

from services.api.models.audit import (
    complete_event,
    count_by_agent,
    get_event,
    list_events,
    prune,
    start_event,
)
from tests.conftest import audit_cleanup

SID = "audittest-sid"

_clean_events = audit_cleanup("audittest-%")


def test_start_inserts_pending_with_full_payload():
    row_id = start_event(
        agent="claude",
        session_id=SID,
        tool_name="Bash",
        correlation_key="toolu_1",
        tool_input={"command": "ls -la"},
        cwd="/repo",
        project="agent-smith",
    )

    event = get_event(row_id)
    assert event["status"] == "pending"
    assert event["tool_name"] == "Bash"
    assert event["tool_input"] == {"command": "ls -la"}
    assert event["completed_at"] is None
    assert event["duration_ms"] is None


def test_complete_updates_open_row_in_place():
    row_id = start_event("claude", SID, "Bash", "toolu_2", {"command": "ls"})

    completed_id = complete_event("toolu_2", status="success", result={"stdout": "ok"}, duration_ms=42)

    assert completed_id == row_id  # same row, not a new one
    event = get_event(row_id)
    assert event["status"] == "success"
    assert event["result"] == {"stdout": "ok"}
    assert event["duration_ms"] == 42
    assert event["completed_at"] is not None
    assert event["tool_input"] == {"command": "ls"}  # untouched


def test_complete_computes_duration_when_not_native():
    row_id = start_event("codex", SID, "Read", "tc_3", {"path": "x"})

    complete_event("tc_3", status="success")

    event = get_event(row_id)
    assert event["duration_ms"] is not None
    assert event["duration_ms"] >= 0


def test_complete_without_pre_inserts_standalone_row():
    new_id = complete_event(
        "tc_orphan",
        status="error",
        result={"error": "boom"},
        agent="gemini",
        session_id=SID,
        tool_name="Write",
    )

    event = get_event(new_id)
    assert event["status"] == "error"
    assert event["agent"] == "gemini"
    assert event["completed_at"] is not None


def test_duplicate_correlation_key_completes_most_recent_open_first():
    first = start_event("claude", SID, "Bash", "dup", {"command": "1"})
    second = start_event("claude", SID, "Bash", "dup", {"command": "2"})

    complete_event("dup", status="success")
    complete_event("dup", status="error")

    # Newest open row completes first (LIFO), then the older one.
    assert get_event(second)["status"] == "success"
    assert get_event(first)["status"] == "error"


def test_list_filters_and_paginates():
    start_event("claude", SID, "Bash", "k1", {"command": "a"})
    start_event("codex", SID, "Read", "k2", {"path": "b"})
    start_event("claude", SID, "Edit", "k3", {"path": "c"})

    claude_rows, claude_total = list_events(session_id=SID, agent="claude")
    assert claude_total == 2
    assert {r["tool_name"] for r in claude_rows} == {"Bash", "Edit"}
    # List view omits the heavy payload columns.
    assert "tool_input" not in claude_rows[0]

    bash_rows, bash_total = list_events(session_id=SID, tool_name="Bash")
    assert bash_total == 1 and bash_rows[0]["tool_name"] == "Bash"

    page, total = list_events(session_id=SID, limit=2, offset=0)
    assert total == 3 and len(page) == 2


def test_count_by_agent_returns_all_agents():
    start_event("claude", SID, "Bash", "c1", {})
    start_event("claude", SID, "Read", "c2", {})

    counts = count_by_agent()
    assert counts["claude"] >= 2
    assert set(counts) == {"claude", "codex", "gemini"}


def test_prune_deletes_old_rows():
    start_event("claude", SID, "Bash", "p1", {})
    deleted = prune("2999-01-01T00:00:00+00:00")  # everything is older than the far future
    assert deleted >= 1
    rows, total = list_events(session_id=SID)
    assert total == 0


def test_invalid_agent_and_status_are_rejected():
    with pytest.raises(AssertionError):
        start_event("rogue", SID, "Bash", "bad", {})
    with pytest.raises(AssertionError):
        complete_event("whatever", status="pending")
