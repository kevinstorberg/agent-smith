import copy
import json
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from psycopg2.extras import Json

from services.db import get_connection
from services.meetings import db, digestion_db, enrichment
from services.memory import db as memory_db
from tests.test_meeting_memory_agent import backend as backend, call, model as model
from tests.test_meeting_memory_flow import feed as feed, ready as ready
from tests.test_meeting_sync import source as source
from tests.test_meetings_router import client as client


@pytest.mark.asyncio
async def test_http_retry_runs_real_summary_agent_from_zero_without_old_source_context(
    client, source, feed, ready, backend, model, monkeypatch,
):
    meeting_id = ready
    summary = "The approved launch date is Monday."
    previous_id = str(uuid4())
    original = digestion_db.get_record(meeting_id)
    old_memory = {
        "id": previous_id, "content": "A previously saved decision.", "kind": "decision",
        "tags": ["releases"],
        "evidence": [{"segment_id": "segment-0", "quote": "HISTORICAL_QUOTE_CANARY"}],
    }
    artifact = {
        "version": 1, "prompt_version": 3, "offset": 100,
        "items": [old_memory], "published_ids": [previous_id],
        "created_at": "2026-10-30T15:54:44+00:00", "reason": "",
        "attribution_snapshot": {"raw": "ATTRIBUTION_CANARY"},
    }
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE meeting_summaries SET summary_text=%s, metadata=%s, revision=revision+1 WHERE id=%s",
            (summary, Json({"transcript": "METADATA_TRANSCRIPT_CANARY"}), meeting_id),
        )
        cur.execute(
            """UPDATE meeting_digestions SET memory_status='failed', memory_attempts=3,
               memory_error='ModelCallTimeoutError', memory_artifact=%s WHERE meeting_id=%s""",
            (Json(artifact), meeting_id),
        )
    response = client.post(f"/api/meetings/{meeting_id}/memories/retry")
    assert response.status_code == 200, response.text
    queued = digestion_db.get_record(meeting_id)
    assert queued["memory_artifact"]["offset"] == 0
    assert queued["memory_artifact"]["input_source"] == "summary"
    assert queued["memory_artifact"]["input_snapshot"]["summary_text"] == summary
    assert queued["memory_artifact"]["items"] == [old_memory]
    assert queued["memory_artifact"]["published_ids"] == [previous_id]
    assert queued["profile_status"] == original["profile_status"]

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE meeting_summaries SET summary_text='LATER_SUMMARY_CANARY', revision=revision+1 WHERE id=%s",
            (meeting_id,),
        )
    item = {
        "content": "The approved launch date is Monday.", "kind": "decision", "tags": ["releases"],
        "evidence": [{"segment_id": "summary-0", "quote": summary}],
    }
    instance, _ = model([
        call("search_previous_memories", query="launch date"),
        call("stage_memories", items=[item], reason="Saved summary decision"),
        AIMessage(content="Analysis complete."),
    ])
    publications = []

    def publish(memory_id, content, repo=None, tags=None, **metadata):
        publications.append(copy.deepcopy((memory_id, content, repo, tags, metadata)))
        return memory_id

    monkeypatch.setattr(memory_db, "publish", publish)
    async with enrichment.DigestionRun(source.name) as run:
        await run.prepare()
        assert run.record["meeting_id"] == meeting_id
        await run.generate_memories()
        assert run.memory_report["outcome"] == "done", run.memory_report

    messages = json.dumps([[message.model_dump() for message in turn] for turn in instance.seen], default=str)
    assert summary in messages
    for canary in ("HISTORICAL_QUOTE_CANARY", "ATTRIBUTION_CANARY", "METADATA_TRANSCRIPT_CANARY", "LATER_SUMMARY_CANARY"):
        assert canary not in messages
    for segment in original["transcript"]["segments"]:
        assert segment["text"] not in messages
    assert "transcript_window" not in messages
    completed = digestion_db.get_record(meeting_id)
    assert completed["memory_status"] == "done"
    assert completed["memory_artifact"]["items"][0] == old_memory
    assert len(publications) == 1 and publications[0][0] != previous_id
    assert "Granola summary (summary-0)" in publications[0][1]
    assert client.get(f"/api/meetings/{meeting_id}/memories").json()["status"] == "done"
    assert db.get_summary(meeting_id)["summary_text"] == "LATER_SUMMARY_CANARY"
