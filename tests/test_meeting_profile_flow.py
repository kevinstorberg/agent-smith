import asyncio
import copy
import json
from dataclasses import replace

import pytest

from services.db import get_connection
from services.graphs.runtime import dispatch
from services.meetings import db, digestion_db, enrichment, profile_db
from services.meetings.types import TranscriptSegment
from tests.test_meeting_memory_flow import agents as agents, feed as feed, job
from tests.test_meeting_sync import note, source as source


@pytest.fixture
def people(source, feed):
    feed.summaries = {"one": replace(note(), metadata={"attendees": [
        {"name": "Alice", "email": f"alice-{source.account_key}@example.invalid"},
        {"name": "Bob", "email": f"bob-{source.account_key}@example.invalid"},
    ]})}
    feed.segments = (
        TranscriptSegment("I value reliability over shipping dates.", {"name": "Alice"}),
        TranscriptSegment("I rely on Alice for careful reviews.", {"name": "Bob"}),
    )
    yield feed
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM participant_profiles WHERE email LIKE %s", (f"%{source.account_key}@example.invalid",))


@pytest.fixture
def profiler(agents, monkeypatch):
    from services.meetings import profile_analysis

    calls = []

    async def analyze(snapshot, window, previous, *, participants, profiles, memories, deadline):
        calls.append(copy.deepcopy({"previous": previous, "profiles": profiles, "memories": memories, "window": window}))
        items = []
        for segment in window:
            subject = next(person for person in participants if segment["id"] in person["segment_ids"])
            target = next(person for person in participants if person["id"] != subject["id"])
            is_bob = subject["display_name"] == "Bob"
            items.append({
                "subject_id": subject["id"], "target_id": target["id"] if is_bob else None,
                "category": "perception" if is_bob else "priority", "epistemic": "self_report", "confidence": "high",
                "content": "Bob values Alice's careful reviews." if is_bob else "Alice prioritizes reliability.",
                "rationale": "Explicitly stated in this meeting.",
                "evidence": [{"segment_id": segment["id"], "quote": segment["text"]}],
            })
        return {"items": items, "reason": ""}

    monkeypatch.setattr(profile_analysis, "analyze_profiles", analyze)
    return calls, analyze


def meeting(source):
    return db.list_summaries(source=source.name)["items"][0]["id"]


def profile_due(meeting_id):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_digestions SET profile_next_attempt_at = clock_timestamp() WHERE meeting_id = %s", (meeting_id,))


@pytest.mark.asyncio
async def test_graph_runs_both_agents_once_with_direct_memory_handoff_and_directed_evidence(source, people, agents, profiler):
    result = json.loads(await dispatch("meeting_ingest", {"source": source.name}))
    meeting_id = meeting(source)
    assert result["memories"]["outcome"] == result["profiles"]["outcome"] == "done"
    calls, _ = profiler
    assert len(calls) == len(agents.analyses) == 1
    assert calls[0]["memories"][0]["id"] == agents.publications[0]
    profiles = [profile_db.get_profile(item["id"]) for item in profile_db.meeting_profiles(meeting_id)["items"]]
    alice, bob = sorted(profiles, key=lambda person: person["display_name"])
    assert bob["claims"][0]["target_id"] == alice["id"]
    assert bob["claims"][0]["target_name"] == "Alice"
    assert alice["claims"][0]["evidence"][0]["segment_id"] == "segment-0"
    await dispatch("meeting_ingest", {"source": source.name})
    assert len(calls) == len(agents.analyses) == len(agents.publications) == 1
    assert "careful reviews" not in json.dumps(result)


@pytest.mark.asyncio
async def test_profile_failure_retries_only_profiles_and_keeps_completed_memories(source, people, agents, profiler, monkeypatch):
    from services.jobs.scheduler import execute_job
    from services.meetings import profile_analysis

    calls, original = profiler

    async def failed(*args, **kwargs):
        raise RuntimeError("Private profile content")

    monkeypatch.setattr(profile_analysis, "analyze_profiles", failed)
    first = await execute_job(job(source))
    meeting_id = meeting(source)
    row = digestion_db.get_record(meeting_id)
    assert not first["success"] and "Private profile content" not in first["error"]
    assert row["memory_status"] == "done" and row["profile_attempts"] == 1 and row["claim_owner"] is None
    monkeypatch.setattr(profile_analysis, "analyze_profiles", original)
    profile_due(meeting_id)
    await dispatch("meeting_ingest", {"source": source.name})
    assert len(agents.analyses) == len(agents.publications) == len(calls) == 1
    assert digestion_db.get_record(meeting_id)["profile_status"] == "done"


@pytest.mark.asyncio
async def test_cancellation_between_nodes_keeps_memory_done_and_releases_lease(source, people, agents, profiler, monkeypatch):
    from services.graphs.library import meeting_ingest

    original = meeting_ingest._generate_memories
    reached_edge = asyncio.Event()

    async def cancel_after_memory(state):
        await original(state)
        reached_edge.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(meeting_ingest, "_generate_memories", cancel_after_memory)
    task = asyncio.create_task(dispatch("meeting_ingest", {"source": source.name}))
    try:
        await asyncio.wait_for(reached_edge.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    row = digestion_db.get_record(meeting(source))
    assert row["memory_status"] == "done" and row["profile_status"] == "pending" and row["claim_owner"] is None
    assert profiler[0] == []
    monkeypatch.setattr(meeting_ingest, "_generate_memories", original)
    await dispatch("meeting_ingest", {"source": source.name})
    assert len(profiler[0]) == len(agents.analyses) == 1


@pytest.mark.asyncio
async def test_profile_windows_resume_without_repeating_memory_stage(source, people, agents, profiler, monkeypatch):
    from services.meetings import profile_analysis

    monkeypatch.setattr(enrichment, "WINDOW_CHARS", 45)
    monkeypatch.setattr(enrichment, "AGENT_SECONDS", 0.15)
    calls, original = profiler

    async def pause_second(snapshot, window, previous, **kwargs):
        if previous:
            await asyncio.Event().wait()
        return await original(snapshot, window, previous, **kwargs)

    monkeypatch.setattr(profile_analysis, "analyze_profiles", pause_second)
    first = json.loads(await dispatch("meeting_ingest", {"source": source.name}))
    row = digestion_db.get_record(meeting(source))
    assert first["profiles"]["outcome"] == "continued"
    assert row["profile_artifact"]["offset"] == 1 and row["profile_attempts"] == 0
    assert len(agents.analyses) == 2
    monkeypatch.setattr(enrichment, "AGENT_SECONDS", 10)
    monkeypatch.setattr(profile_analysis, "analyze_profiles", original)
    await dispatch("meeting_ingest", {"source": source.name})
    assert len(agents.analyses) == 2 and len(calls) == 2
    assert [call["window"][0]["id"] for call in calls] == ["segment-0", "segment-1"]
    assert digestion_db.get_record(meeting(source))["profile_status"] == "done"


@pytest.mark.asyncio
async def test_human_correction_conflict_discards_only_uncommitted_profile_candidates(source, people, agents, profiler, monkeypatch):
    from services.meetings import profile_analysis
    from services.meetings.service import MeetingSyncError

    await dispatch("meeting_ingest", {"source": source.name})
    initial = profile_db.meeting_profiles(meeting(source))["items"][0]
    profile = profile_db.get_profile(initial["id"])
    original = profiler[1]

    async def concurrent_correction(*args, **kwargs):
        candidate = await original(*args, **kwargs)
        profile_db.correct_claim(profile["id"], profile["claims"][0]["id"], profile["revision"], "reject", None, "Human correction wins")
        return candidate

    people.summaries["two"] = replace(people.summaries["one"], external_id="two", source_url="https://example.invalid/two")
    monkeypatch.setattr(profile_analysis, "analyze_profiles", concurrent_correction)
    with pytest.raises(MeetingSyncError, match="ProfileRevisionConflict"):
        await dispatch("meeting_ingest", {"source": source.name})
    rows = db.list_summaries(source=source.name)["items"]
    second_id = next(row["id"] for row in rows if row["external_id"] == "two")
    second = digestion_db.get_record(second_id)
    assert second["memory_status"] == "done" and second["profile_artifact"] == {}
    assert profile_db.get_profile(profile["id"])["claims"][0]["status"] == "rejected"
    assert len(agents.analyses) == 2
    async def respect_correction(*args, **kwargs):
        return {"items": [], "reason": "Existing human correction is authoritative"}
    monkeypatch.setattr(profile_analysis, "analyze_profiles", respect_correction)
    profile_due(second_id)
    await dispatch("meeting_ingest", {"source": source.name})
    assert len(agents.analyses) == 2 and digestion_db.get_record(second_id)["profile_status"] == "done"
