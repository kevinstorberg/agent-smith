import json
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from psycopg2.extras import Json

from services.db import get_connection
from services.graphs.runtime import dispatch
from services.meetings import analysis, digestion_db
from services.memory import db, server
from services.memory.backends import get_backend
from tests.test_meeting_memory_agent import call, model as model
from tests.test_meeting_memory_flow import feed as feed, ready as ready
from tests.test_meeting_sync import source as source
from tests.test_meeting_transcript_capture import transcript_page
from tests.test_memory_publication import CREATED, isolated_store as isolated_store


@pytest.mark.asyncio
async def test_real_react_to_publication_preserves_topic_tags_and_action_details(source, feed, model):
    action = "Sam will deliver the Paralign MFA security review by 2026-11-02; the audit is blocked until it is ready."
    feed.segments = transcript_page(action).segments
    items = [{
        "content": "Sam committed to deliver Paralign's MFA security review by 2026-11-02. The audit depends on that review and remains blocked.",
        "kind": "commitment", "tags": ["Paralign", " Security ", "security", "Multi Factor Authentication"],
        "evidence": [{"segment_id": "segment-0", "quote": action}],
    }]
    instance, _ = model([
        call("search_previous_memories", query="Paralign MFA security review"),
        call("stage_memories", items=items), AIMessage(content="Done"),
    ])
    result = json.loads(await dispatch("meeting_ingest", {"source": source.name}))
    assert result["memories"]["outcome"] == "done"
    saved = db.list_memories(meeting_only=True)
    assert len(saved) == 1
    assert saved[0]["tags"] == ["paralign", "security", "multi-factor-authentication"]
    assert saved[0]["from_meeting"] and saved[0]["source_type"] == "meeting"
    assert items[0]["content"] in saved[0]["content"]
    assert len(instance.seen) == 3
    count = len(instance.seen)
    await dispatch("meeting_ingest", {"source": source.name})
    assert len(instance.seen) == count and len(db.list_memories(meeting_only=True)) == 1
    db._retriever = None
    persisted = db.get(saved[0]["id"])
    assert persisted["tags"] == saved[0]["tags"] and persisted["from_meeting"]


@pytest.mark.asyncio
async def test_legacy_checkpoint_replays_raw_tags_after_lost_receipt_without_another_agent(source, ready, monkeypatch):
    memory_id = str(uuid4())
    record = digestion_db.get_record(ready)
    text = record["transcript"]["segments"][0]["text"]
    item = {"id": memory_id, "content": "An earlier decision", "kind": "decision",
            "evidence": [{"segment_id": "segment-0", "quote": text}]}
    tags = ["meeting-memory", f"meeting:{ready}", "decision"]
    from services.meetings.enrichment import memory_content

    content = memory_content(record["snapshot"], item)
    db.publish(memory_id, content, repo=record["snapshot"].get("project"), tags=tags,
               created_at=CREATED, source_type="meeting", source_id=ready)
    artifact = {"version": 1, "prompt_version": 1, "model": "legacy", "offset": len(record["transcript"]["segments"]),
                "items": [item], "published_ids": [], "created_at": CREATED, "reason": ""}
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE meeting_digestions SET memory_artifact = %s WHERE meeting_id = %s", (Json(artifact), ready))

    async def forbidden(*args, **kwargs):
        raise AssertionError("A saved window must not invoke an agent again")

    monkeypatch.setattr(analysis, "analyze_memories", forbidden)
    result = json.loads(await dispatch("meeting_ingest", {"source": source.name}))
    assert result["memories"]["outcome"] == "done"
    assert digestion_db.get_record(ready)["memory_artifact"]["published_ids"] == [memory_id]
    assert db.get(memory_id)["tags"] == ["decision"]
    assert json.loads(get_backend().get_row(memory_id)["metadata"]["tags"]) == tags
    with pytest.raises(db.MemoryConflictError):
        db.publish(memory_id, content, repo=record["snapshot"].get("project"), tags=["decision"],
                   created_at=CREATED, source_type="meeting", source_id=ready)


@pytest.mark.asyncio
async def test_mcp_discovery_exposes_topic_and_boolean_filters_with_real_store_round_trip():
    meeting_id, memory_id = str(uuid4()), str(uuid4())
    db.publish(memory_id, "Paralign security action item", repo="paralign", tags=["paralign", "security"],
               created_at=CREATED, source_type="meeting", source_id=meeting_id)
    db.add("General Paralign security context", repo="paralign", tags=["paralign", "security"])
    tools = {tool.name: tool.inputSchema for tool in await server.mcp.list_tools()}
    for name in ("memory_search", "memory_list"):
        assert tools[name]["properties"]["meeting_only"]["type"] == "boolean"
        assert "tags" in tools[name]["properties"]
    listed = server.memory_list("paralign", 1, tags=["security"], meeting_only=True)
    searched = server.memory_search("security", "paralign", 1, tags=["security"], meeting_only=True)
    assert [row["id"] for row in listed] == [memory_id]
    assert [row["id"] for row in searched] == [memory_id]
    assert server.memory_list(tags=["hiring"], meeting_only=True) == []
