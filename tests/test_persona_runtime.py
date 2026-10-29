import asyncio
import copy
import json

import pytest

from services.db import get_connection
from services.graphs.runtime import dispatch
from services.jobs.scheduler import JobScheduler
from services.jobs.service import execution_timeout
from services.meetings import analysis, digestion_db, enrichment, management_db, profile_db
from services.meetings.participants import speaker_key
from services.meetings.types import TranscriptSegment
from tests.test_meeting_memory_flow import agents as agents, feed as feed, make_due, ready as ready
from tests.test_meeting_sync import source as source


@pytest.mark.asyncio
async def test_persona_uses_saved_context_without_granola_or_completed_memories(source, ready, agents, monkeypatch):
    monkeypatch.setenv("MEETING_SOURCES_JSON", "{}")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_digestions SET memory_status = 'failed' WHERE meeting_id = %s", (ready,))
    result = json.loads(await dispatch("persona", {"source": source.name}))
    row = digestion_db.get_record(ready)
    assert result["profiles"]["outcome"] == "done"
    assert row["memory_status"] == "failed" and row["profile_status"] == "done"
    assert row["profile_claim_owner"] is None and agents.analyses == agents.publications == []


@pytest.mark.asyncio
async def test_memory_completes_while_independent_persona_lease_is_held(source, ready, agents):
    owner = "independent-persona-owner"
    assert digestion_db.claim_profile(source.name, owner)["meeting_id"] == ready
    try:
        result = json.loads(await dispatch("meeting_ingest", {"source": source.name}))
        row = digestion_db.get_record(ready)
        assert result["memories"]["outcome"] == "done" and "profiles" not in result
        assert row["profile_claim_owner"] == owner and row["claim_owner"] is None
        assert len(agents.analyses) == len(agents.publications) == 1
    finally:
        digestion_db.release_profile_owner(owner)


def test_process_preserves_completed_persona_receipt_when_memories_are_missing(ready):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_digestions SET profile_status = 'done', profile_artifact = '{\"reviewed\":true}'::jsonb WHERE meeting_id = %s", (ready,))
    assert management_db.request_processing(ready) == {"status": "queued"}
    record = digestion_db.get_record(ready)
    assert record["profile_status"] == "done" and record["profile_artifact"] == {"reviewed": True}


@pytest.mark.asyncio
async def test_requested_jobs_run_on_next_tick_and_keep_separate_eligibility(source, ready):
    management_db.request_processing(ready)
    jobs = [{"id": index, "schedule_config": {"minutes": 15}, "input_params": {
        "graph_type": graph, "graph_inputs": {"source": source.name}, "timeout": 300,
    }} for index, graph in enumerate(("meeting_ingest", "persona"), 1)]
    scheduler = JobScheduler(device_name="synthetic-device")
    scheduler._eligible_jobs = lambda: jobs
    dispatched = []
    scheduler._dispatch = lambda job: dispatched.append(job["id"])
    await scheduler._tick()
    assert dispatched == [1, 2]
    assert all(execution_timeout(job["input_params"]["graph_type"], job["input_params"]) == 600 for job in jobs)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_digestions SET memory_status = 'done' WHERE meeting_id = %s", (ready,))
    dispatched.clear()
    await scheduler._tick()
    assert dispatched == [2]


@pytest.mark.asyncio
async def test_requested_old_meeting_drains_across_scheduler_ticks_without_replaying_checkpoints(source, ready, agents, monkeypatch):
    owner = "synthetic-window-setup"
    assert digestion_db.claim_digestion([(source.provider, source.account_key)], owner)
    digestion_db.save_capture(ready, owner, digestion_db.get_context(ready), {"segments": [
        TranscriptSegment(f"Synthetic decision {index}", {}).to_dict(index) for index in range(3)
    ]}, complete=True)
    digestion_db.release(ready, owner)
    management_db.request_processing(ready)
    monkeypatch.setattr(enrichment, "WINDOW_SEGMENTS", 1)
    monkeypatch.setattr(enrichment, "AGENT_SECONDS", 0.1)
    blocked = set()

    async def bounded_window(snapshot, window, previous, **kwargs):
        segment = window[0]["id"]
        if segment != "segment-0" and segment not in blocked:
            blocked.add(segment)
            await asyncio.Event().wait()
        return await agents.analyze(snapshot, window, previous, **kwargs)

    monkeypatch.setattr(analysis, "analyze_memories", bounded_window)
    job = {"id": 1, "schedule_config": {"minutes": 15}, "input_params": {
        "graph_type": "meeting_ingest", "graph_inputs": {"source": source.name}, "timeout": 300,
    }}
    scheduler = JobScheduler()
    scheduler._eligible_jobs = lambda: [job]
    runs = []
    scheduler._dispatch = lambda job: runs.append(asyncio.create_task(dispatch("meeting_ingest", job["input_params"]["graph_inputs"])))
    for offset in (1, 2, 3):
        await scheduler._tick()
        await asyncio.wait_for(runs[-1], 5)
        record = digestion_db.get_record(ready)
        assert record["memory_artifact"]["offset"] == offset and record["memory_attempts"] == 0
    assert record["memory_status"] == "done" and len(agents.publications) == 3
    assert [call[1][0]["id"] for call in agents.analyses] == ["segment-0", "segment-1", "segment-2"]
    await scheduler._tick()
    assert len(runs) == 3


@pytest.mark.asyncio
async def test_zero_progress_budget_uses_bounded_failure_and_safe_diagnostics(source, ready, agents, monkeypatch):
    async def stalled(*args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(analysis, "analyze_memories", stalled)
    monkeypatch.setattr(enrichment, "AGENT_SECONDS", 0.01)
    with pytest.raises(RuntimeError, match="StageNoProgressTimeout"):
        await dispatch("meeting_ingest", {"source": source.name})
    row = digestion_db.get_record(ready)
    assert row["memory_attempts"] == 1 and row["memory_error"] == "StageNoProgressTimeout"
    assert not digestion_db.has_requested_work([(source.provider, source.account_key)])
    assert row["claim_owner"] is None and agents.publications == []


@pytest.mark.asyncio
async def test_vocabulary_is_durable_before_first_call_and_reused_on_retry(source, ready, agents, monkeypatch):
    from services.meetings import vocabulary_db

    vocabulary = [{"term": "SLA", "definition": "Synthetic service agreement"}]
    selections, contexts = [], []
    original = agents.analyze

    def relevant(text):
        selections.append(text)
        return copy.deepcopy(vocabulary)

    async def analyze(snapshot, *args, **kwargs):
        contexts.append(snapshot["vocabulary"])
        assert digestion_db.get_record(ready)["memory_artifact"]["vocabulary"] == contexts[-1]
        if len(contexts) == 1:
            raise analysis.MemoryAnalysisError("Synthetic failure")
        return await original(snapshot, *args, **kwargs)

    monkeypatch.setattr(vocabulary_db, "relevant", relevant)
    monkeypatch.setattr(analysis, "analyze_memories", analyze)
    with pytest.raises(RuntimeError, match="MemoryAnalysisError"):
        await dispatch("meeting_ingest", {"source": source.name})
    vocabulary[0]["definition"] = "Changed later"
    make_due(ready)
    await dispatch("meeting_ingest", {"source": source.name})
    assert len(selections) == 1 and contexts[0] == contexts[1]
    assert contexts[1][0]["definition"] == "Synthetic service agreement"


@pytest.mark.asyncio
async def test_owned_model_timeout_and_analysis_budget_have_distinct_categories(monkeypatch):
    async def stalled(_request):
        await asyncio.Event().wait()

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(analysis, "MODEL_TIMEOUT_SECONDS", 0.01)
    with pytest.raises(analysis.ModelCallTimeoutError):
        await analysis._ModelDeadline(loop.time() + 10).awrap_model_call(None, stalled)
    with pytest.raises(analysis.AnalysisBudgetExpired):
        await analysis._ModelDeadline(loop.time()).awrap_model_call(None, stalled)


@pytest.mark.asyncio
async def test_optional_context_failure_does_not_prevent_persona_staging():
    context = analysis.AnalysisContext({"id": "synthetic"}, [{"id": "one", "text": "Synthetic"}], [], require_memory_search=False)
    assert json.loads(context.stage([], "No grounded claim")) == {"staged": 0}


@pytest.mark.asyncio
async def test_effective_identity_uses_canonical_name_without_changing_raw_paged_speakers(source, feed):
    feed.segments = (
        TranscriptSegment("Synthetic first speaker", {"name": "Me", "source": "microphone"}),
        TranscriptSegment("Synthetic second speaker", {"diarization_label": "Speaker B"}),
    )
    await dispatch("meeting_ingest", {"source": source.name, "digest": False})
    from services.meetings import db

    meeting_id = db.list_summaries(source=source.name)["items"][0]["id"]
    person = profile_db.create_profile("Confirmed synthetic person")
    try:
        raw = digestion_db.get_record(meeting_id)["transcript"]["segments"]
        key = speaker_key(raw[0]["speaker"])
        management_db.update_participants(meeting_id, 0, [{"name": person["display_name"], "profile_id": person["id"], "speaker_key": key}])
        first = digestion_db.get_transcript(meeting_id, limit=1)
        second = digestion_db.get_transcript(meeting_id, limit=1, offset=1)
        assert first["items"][0]["speaker"] == raw[0]["speaker"]
        assert first["items"][0]["effective_speaker"] == {
            "profile_id": person["id"], "display_name": person["display_name"], "email": None, "source": "manual_assignment",
        }
        assert second["items"][0]["effective_speaker"]["profile_id"] is None
        profile_db.update_metadata(person["id"], person["revision"], display_name="Latest canonical name")
        assert digestion_db.get_transcript(meeting_id, limit=1)["items"][0]["effective_speaker"]["display_name"] == "Latest canonical name"
        group = next(item for item in management_db.get_participants(meeting_id)["speakers"] if item["key"] == key)
        assert group["source"] == "microphone" and group["sample"] == raw[0]["text"]
        assert group["assignment"]["profile_id"] == person["id"]
        assert digestion_db.get_record(meeting_id)["transcript"]["segments"] == raw
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM participant_profiles WHERE id = %s", (person["id"],))
