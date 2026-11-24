from __future__ import annotations

from datetime import timedelta

import pytest

from services.db import get_connection
from services.meetings import action_item_db
from tests.test_meeting_action_item_proposals import (
    SUMMARY,
    generate,
    install_analysis,
    saved as saved,
)
from tests.test_meeting_sync import STAMP, source as source


def execute(sql, params=()):
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall() if cursor.description else None


@pytest.mark.asyncio
@pytest.mark.parametrize("first_seen", ["2026-11-19T23:59:59Z", "2026-11-20T00:00:00Z"])
async def test_missing_action_item_run_is_not_automatically_recovered(
    source, saved, monkeypatch, first_seen
):
    meeting = saved()
    execute(
        "DELETE FROM meeting_action_item_runs WHERE meeting_id=%s", (meeting["id"],)
    )
    execute(
        "UPDATE meeting_sync_state SET action_items_activated_at='2026-11-20T00:00:00Z' WHERE provider=%s AND account_key=%s",
        (source.provider, source.account_key),
    )
    execute(
        "UPDATE meeting_summaries SET first_seen_at=%s WHERE id=%s",
        (first_seen, meeting["id"]),
    )
    calls = install_analysis(monkeypatch, items=[])

    assert (await generate(source))["outcome"] == "idle"
    saved(text=SUMMARY + " Corrected context.", updated_at=STAMP + timedelta(hours=1))
    assert (await generate(source))["outcome"] == "idle"
    assert action_item_db.get_record(meeting["id"]) is None
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["done", "failed"])
async def test_editing_terminal_action_item_run_does_not_repeat_analysis(
    source, saved, monkeypatch, status
):
    meeting = saved()
    calls = install_analysis(monkeypatch, items=[])
    if status == "done":
        assert (await generate(source))["outcome"] == "done"
    else:
        execute(
            """UPDATE meeting_action_item_runs SET action_items_status='failed',
            action_items_attempts=3,action_items_error='SyntheticFailure' WHERE meeting_id=%s""",
            (meeting["id"],),
        )
    before = action_item_db.get_record(meeting["id"])

    changed = saved(
        text=SUMMARY + " Corrected context.", updated_at=STAMP + timedelta(hours=1)
    )
    assert changed["revision"] == 2
    assert (await generate(source))["outcome"] == "idle"
    assert (await generate(source))["outcome"] == "idle"
    after = action_item_db.get_record(meeting["id"])
    assert after["action_items_status"] == status
    for field in (
        "source_revision",
        "source_hash",
        "action_items_artifact",
        "action_items_attempts",
        "action_items_error",
        "updated_at",
    ):
        assert after[field] == before[field]
    assert len(calls) == (1 if status == "done" else 0)


@pytest.mark.asyncio
async def test_new_import_runs_action_item_analysis_once(source, saved, monkeypatch):
    meeting = saved()
    calls = install_analysis(monkeypatch, items=[])
    assert (await generate(source))["outcome"] == "done"

    for _ in range(2):
        unchanged = saved()
        assert unchanged["revision"] == meeting["revision"]
        assert (await generate(source))["outcome"] == "idle"

    assert len(calls) == 1
    record = action_item_db.get_record(meeting["id"])
    assert record["action_items_status"] == "done"
    assert record["source_revision"] == meeting["revision"]
    assert record["source_hash"] == meeting["content_hash"]
