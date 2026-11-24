from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from services.db import get_connection
from services.meetings import action_item_db
from tests.conftest import action_item_owner
from tests.test_meeting_action_item_proposals import saved as saved
from tests.test_meeting_sync import source as source


def identities(source):
    return [(source.provider, source.account_key)]


def execute(sql, params=()):
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall() if cursor.description else None


def test_action_item_enrollment_recovery_repairs_only_after_persisted_activation(
    source, saved
):
    old, new = saved("old"), saved("new")
    execute(
        "DELETE FROM meeting_action_item_runs WHERE meeting_id IN %s",
        ((old["id"], new["id"]),),
    )
    execute(
        "UPDATE meeting_sync_state SET action_items_activated_at='2026-11-20T00:00:00Z' WHERE provider=%s AND account_key=%s",
        (source.provider, source.account_key),
    )
    execute(
        "UPDATE meeting_summaries SET first_seen_at='2026-11-19T23:59:59Z' WHERE id=%s",
        (old["id"],),
    )
    execute(
        "UPDATE meeting_summaries SET first_seen_at='2026-11-20T00:00:00Z' WHERE id=%s",
        (new["id"],),
    )
    assert action_item_db.reconcile(identities(source)) == {
        "enrolled": 1,
        "refreshed": 0,
    }
    assert action_item_db.get_record(old["id"]) is None
    assert action_item_db.get_record(new["id"])["source_hash"] == new["content_hash"]
    assert action_item_db.reconcile(identities(source)) == {
        "enrolled": 0,
        "refreshed": 0,
    }


@pytest.mark.parametrize("state", ["done", "failed", "pending", "claimed"])
def test_action_item_enrollment_recovery_does_not_reset_unchanged_work(
    source, saved, state
):
    meeting = saved()
    if state == "claimed":
        action_item_db.claim(identities(source), action_item_owner("reconciliation"))
    else:
        execute(
            "UPDATE meeting_action_item_runs SET action_items_status=%s,action_items_attempts=2,action_items_error='Retained' WHERE meeting_id=%s",
            (state, meeting["id"]),
        )
    before = action_item_db.get_record(meeting["id"])
    assert action_item_db.reconcile(identities(source)) == {
        "enrolled": 0,
        "refreshed": 0,
    }
    assert action_item_db.get_record(meeting["id"]) == before


def test_action_item_enrollment_recovery_refreshes_explicit_old_enrollment_only_on_source_drift(
    source, saved
):
    meeting = saved()
    execute(
        "UPDATE meeting_summaries SET first_seen_at='2000-01-01T00:00:00Z',revision=revision+1,content_hash=%s WHERE id=%s",
        ("b" * 64, meeting["id"]),
    )
    execute(
        "UPDATE meeting_action_item_runs SET action_items_status='done' WHERE meeting_id=%s",
        (meeting["id"],),
    )
    assert action_item_db.reconcile(identities(source)) == {
        "enrolled": 0,
        "refreshed": 1,
    }
    state = action_item_db.get_record(meeting["id"])
    assert state["source_revision"] == 2 and state["source_hash"] == "b" * 64
    assert (
        state["action_items_status"] == "pending"
        and state["action_items_attempts"] == 0
    )


def test_action_item_enrollment_recovery_concurrent_repair_is_idempotent_and_preserves_activation(
    source, saved
):
    meeting = saved()
    execute(
        "DELETE FROM meeting_action_item_runs WHERE meeting_id=%s", (meeting["id"],)
    )
    before = execute(
        "SELECT action_items_activated_at FROM meeting_sync_state WHERE account_key=%s",
        (source.account_key,),
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(
            pool.map(lambda _: action_item_db.reconcile(identities(source)), range(2))
        )
    assert sum(row["enrolled"] for row in result) == 1
    execute(
        "UPDATE meeting_sync_state SET source_name='Renamed' WHERE account_key=%s",
        (source.account_key,),
    )
    assert (
        execute(
            "SELECT action_items_activated_at FROM meeting_sync_state WHERE account_key=%s",
            (source.account_key,),
        )
        == before
    )
    assert action_item_db.reconcile([("test", "unrelated")]) == {
        "enrolled": 0,
        "refreshed": 0,
    }
    assert action_item_db.reconcile([]) == {"enrolled": 0, "refreshed": 0}


def test_action_item_enrollment_recovery_excludes_unavailable_and_keeps_first_seen_immutable(
    source, saved
):
    meeting = saved()
    execute(
        "DELETE FROM meeting_action_item_runs WHERE meeting_id=%s", (meeting["id"],)
    )
    execute(
        "UPDATE meeting_summaries SET available=false WHERE id=%s", (meeting["id"],)
    )
    assert action_item_db.reconcile(identities(source)) == {
        "enrolled": 0,
        "refreshed": 0,
    }
    assert action_item_db.get_record(meeting["id"]) is None
    from tests.test_meeting_sync import STAMP
    from datetime import timedelta

    first = execute(
        "SELECT first_seen_at FROM meeting_summaries WHERE id=%s", (meeting["id"],)
    )
    saved(
        text=meeting["summary_text"] + " Updated.",
        updated_at=STAMP + timedelta(hours=1),
    )
    assert (
        execute(
            "SELECT first_seen_at FROM meeting_summaries WHERE id=%s", (meeting["id"],)
        )
        == first
    )
