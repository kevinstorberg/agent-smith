import asyncio
import copy
import json
from dataclasses import replace
from datetime import timedelta

import pytest

from services.db import get_connection
from services.graphs.runtime import dispatch
from services.jobs.models.execution import list_executions_for_job
from services.jobs.models.job import create_job, get_job
from services.jobs.scheduler import execute_job
from services.meetings import db, digestion_db, enrichment, factory, memory_db
from services.meetings.types import TranscriptPage
from tests.conftest import jobs_cleanup
from tests.test_meeting_sync import STAMP, note, page, source as source
from tests.test_meeting_transcript_capture import enroll, transcript_page

_clean_jobs = jobs_cleanup("MEMFLOW %")


@pytest.fixture
def feed(source, monkeypatch):
    class Feed:
        summaries = {"one": note()}
        segments = transcript_page().segments
        clients = []

    feed = Feed()

    class Provider:
        def __init__(self, config):
            self.closed = False
            feed.clients.append(self)

        async def list_page(self, cursor=None, *, updated_after=None):
            return page(*feed.summaries.values())

        async def get_summary(self, external_id):
            return feed.summaries.get(external_id)

        async def get_transcript_page(self, external_id, cursor=None):
            return TranscriptPage(feed.segments)

        async def aclose(self):
            self.closed = True

    monkeypatch.setitem(factory._PROVIDER_BUILDERS, "test", Provider)
    return feed


@pytest.fixture
def agents(monkeypatch, unidentified_speakers):
    from services.meetings import analysis, profile_analysis
    from services.memory import db as vector_db

    class Calls:
        analyses = []
        publications = []
        stored = {}

        async def analyze(self, snapshot, window, previous, *, deadline):
            self.analyses.append(copy.deepcopy((snapshot, window, previous)))
            return {"items": [{
                "content": "A recorded decision", "kind": "decision",
                "tags": ["product", "paralign"],
                "evidence": [{"segment_id": window[0]["id"], "quote": window[0]["text"]}],
            }], "reason": ""}

        def publish(self, memory_id, content, repo=None, tags=None, *, created_at, source_type=None, source_id=None):
            assert source_type == "meeting" and source_id
            frozen = (content, repo, tags, created_at)
            if memory_id in self.stored:
                assert self.stored[memory_id] == frozen
            self.stored[memory_id] = frozen
            self.publications.append(memory_id)
            return memory_id

    calls = Calls()
    monkeypatch.setattr(analysis, "analyze_memories", calls.analyze)
    async def no_profile_claims(*args, **kwargs):
        return {"items": [], "reason": "No grounded participant claims"}

    monkeypatch.setattr(profile_analysis, "analyze_profiles", no_profile_claims)
    monkeypatch.setattr(vector_db, "publish", calls.publish)
    return calls


@pytest.fixture
def ready(source, feed):
    meeting_id = enroll(source, feed.summaries["one"])
    owner = "memory-test-enroller"
    assert digestion_db.claim_transcript([(source.provider, source.account_key)], owner)
    try:
        digestion_db.save_capture(meeting_id, owner, digestion_db.get_context(meeting_id), {
            "segments": [segment.to_dict(index) for index, segment in enumerate(feed.segments)], "cursor": None,
        }, complete=True)
    finally:
        digestion_db.release(meeting_id, owner)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_digestions SET speaker_status='legacy' WHERE meeting_id=%s", (meeting_id,))
    return meeting_id


def job(source):
    return get_job(create_job("MEMFLOW " + source.name, {"minutes": 5}, {
        "graph_type": "meeting_ingest", "graph_inputs": {"source": source.name}, "timeout": 30,
    }))


def make_due(meeting_id):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_digestions SET memory_next_attempt_at = clock_timestamp() WHERE meeting_id = %s", (meeting_id,))


@pytest.mark.asyncio
async def test_graph_enriches_new_meeting_once_and_preserves_frozen_snapshot_after_edit(source, feed, agents):
    first = json.loads(await dispatch("meeting_ingest", {"source": source.name}))
    row = db.list_summaries(source=source.name)["items"][0]
    assert first["memories"]["outcome"] == "done"
    assert len(agents.analyses) == len(agents.publications) == 1
    frozen = digestion_db.get_record(row["id"])["snapshot"]

    await dispatch("meeting_ingest", {"source": source.name})
    feed.summaries["one"] = replace(note(), summary_text="Edited later", provider_updated_at=STAMP + timedelta(hours=1))
    await dispatch("meeting_ingest", {"source": source.name})

    assert len(agents.analyses) == len(agents.publications) == 1
    assert db.get_summary(row["id"])["revision"] == 2
    assert digestion_db.get_record(row["id"])["snapshot"] == frozen
    assert all(client.closed for client in feed.clients)
    assert "Recorded decision" not in json.dumps(first) and "A recorded decision" not in json.dumps(first)


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", [False, True])
async def test_noop_and_historical_rows_do_not_call_agent(source, feed, agents, existing):
    if existing:
        meeting_id = enroll(source, feed.summaries["one"])
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM meeting_digestions WHERE meeting_id = %s", (meeting_id,))
    else:
        feed.summaries = {}
    await dispatch("meeting_ingest", {"source": source.name})
    assert agents.analyses == agents.publications == []
    if existing:
        assert digestion_db.get_record(meeting_id) is None


@pytest.mark.asyncio
async def test_digest_false_captures_transcript_and_leaves_memory_work_for_enabled_run(source, feed, agents):
    await dispatch("meeting_ingest", {"source": source.name, "digest": False})
    meeting_id = db.list_summaries(source=source.name)["items"][0]["id"]
    record = digestion_db.get_record(meeting_id)
    assert record["transcript_status"] == "ready" and record["memory_status"] == "pending"
    await dispatch("meeting_ingest", {"source": source.name, "digest": False})
    assert agents.analyses == agents.publications == []
    await dispatch("meeting_ingest", {"source": source.name})
    assert len(agents.analyses) == len(agents.publications) == 1


@pytest.mark.asyncio
async def test_timeout_resumes_committed_window_without_reanalysis_or_premature_publication(source, ready, agents, monkeypatch):
    from psycopg2.extras import Json

    from services.meetings import analysis

    segments = [transcript_page("Window " + str(index) + " " + "x" * 32).segments[0].to_dict(index) for index in range(3)]
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_digestions SET transcript = %s WHERE meeting_id = %s", (Json({"segments": segments, "cursor": None}), ready))
    monkeypatch.setattr(enrichment, "WINDOW_CHARS", 60)
    monkeypatch.setattr(enrichment, "AGENT_SECONDS", 0.15)
    original = agents.analyze

    async def pause_second(snapshot, window, previous, *, deadline):
        if previous:
            await asyncio.Event().wait()
        return await original(snapshot, window, previous, deadline=deadline)

    monkeypatch.setattr(analysis, "analyze_memories", pause_second)
    async with enrichment.DigestionRun(source.name) as run:
        await run.prepare()
        await run.generate_memories()
        assert run.memory_report["outcome"] == "continued"
    record = digestion_db.get_record(ready)
    first_id = record["memory_artifact"]["items"][0]["id"]
    assert record["memory_artifact"]["offset"] == 1 and record["memory_attempts"] == 0
    assert record["claim_owner"] is None and agents.publications == []

    monkeypatch.setattr(analysis, "analyze_memories", original)
    monkeypatch.setattr(enrichment, "AGENT_SECONDS", 10)
    async with enrichment.DigestionRun(source.name) as run:
        await run.prepare()
        await run.generate_memories()
        assert run.memory_report["outcome"] == "done"
    record = digestion_db.get_record(ready)
    assert record["memory_artifact"]["offset"] == 3
    assert [call[1][0]["id"] for call in agents.analyses] == ["segment-0", "segment-1", "segment-2"]
    assert agents.publications[0] == first_id and len(agents.stored) == 3


@pytest.mark.asyncio
async def test_receipt_failure_retries_frozen_publication_without_another_agent_call(source, ready, agents, monkeypatch, caplog):
    original = memory_db.save_progress
    failed = False

    def fail_first_receipt(meeting_id, owner, transcript_hash, artifact, *, complete=False):
        nonlocal failed
        if artifact["published_ids"] and not failed:
            failed = True
            raise RuntimeError("private generated text must remain secret")
        return original(meeting_id, owner, transcript_hash, artifact, complete=complete)

    monkeypatch.setattr(memory_db, "save_progress", fail_first_receipt)
    scheduled = job(source)
    first = await execute_job(scheduled)
    record = digestion_db.get_record(ready)
    assert not first["success"] and "RuntimeError" in first["error"]
    assert record["memory_artifact"]["offset"] == 1 and record["memory_artifact"]["published_ids"] == []
    assert record["memory_attempts"] == 1 and record["claim_owner"] is None
    assert "private generated text" not in first["error"] + caplog.text

    make_due(ready)
    second = await execute_job(scheduled)
    assert second["success"] and len(agents.analyses) == 1
    assert len(agents.stored) == 1 and agents.publications == agents.publications[:1] * 2
    assert memory_db.get_memories(ready)["status"] == "done"
    executions, total = list_executions_for_job(scheduled["id"])
    assert total == 2 and {row["status"] for row in executions} == {"failed", "success"}


@pytest.mark.asyncio
async def test_job_cancellation_releases_global_lease_without_counting_failure(source, ready, agents, monkeypatch):
    from services.meetings import analysis

    started = asyncio.Event()

    async def blocked(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(analysis, "analyze_memories", blocked)
    scheduled = job(source)
    task = asyncio.create_task(execute_job(scheduled))
    try:
        await asyncio.wait_for(started.wait(), 5)
        assert digestion_db.get_record(ready)["claim_owner"]
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    record = digestion_db.get_record(ready)
    assert record["claim_owner"] is None and record["memory_attempts"] == 0
    assert record["memory_status"] == "pending" and agents.publications == []
    executions, total = list_executions_for_job(scheduled["id"])
    assert total == 1 and executions[0]["status"] == "interrupted"


@pytest.mark.asyncio
async def test_deletion_after_final_window_checkpoint_prevents_external_publication(source, ready, agents, monkeypatch):
    original = memory_db.save_progress
    deleted = False

    def delete_after_checkpoint(meeting_id, owner, transcript_hash, artifact, *, complete=False):
        nonlocal deleted
        original(meeting_id, owner, transcript_hash, artifact, complete=complete)
        if not deleted and artifact["offset"] == 1 and not artifact["published_ids"]:
            deleted = True
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute("UPDATE meeting_summaries SET available = false WHERE id = %s", (meeting_id,))

    monkeypatch.setattr(memory_db, "save_progress", delete_after_checkpoint)
    result = await execute_job(job(source))
    assert not result["success"] and "ClaimLostError" in result["error"]
    assert deleted and len(agents.analyses) == 1 and agents.publications == []
    assert memory_db.get_memories(ready) is None
    assert digestion_db.get_record(ready)["claim_owner"] is None


@pytest.mark.asyncio
async def test_stale_worker_cannot_write_or_clear_replacement_lease(source, ready, agents):
    replacement = "replacement-memory-owner"
    try:
        async with enrichment.DigestionRun(source.name) as run:
            await run.prepare()
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute("UPDATE meeting_digestions SET claim_until = clock_timestamp() - interval '1 second' WHERE meeting_id = %s", (ready,))
            assert digestion_db.claim_digestion([(source.provider, source.account_key)], replacement)
            with pytest.raises(db.ClaimLostError):
                await run.generate_memories()
        assert agents.publications == []
        assert digestion_db.get_record(ready)["claim_owner"] == replacement
    finally:
        digestion_db.release(ready, replacement)


@pytest.mark.asyncio
@pytest.mark.parametrize("category,expected", [("APITimeoutError", "APITimeoutError"), ("private error category secret-token", "MemoryAnalysisError")])
async def test_safe_agent_cause_reaches_job_and_ledger_without_private_message(source, ready, agents, monkeypatch, caplog, category, expected):
    from services.meetings import analysis

    async def failed(*args, **kwargs):
        raise analysis.MemoryAnalysisError("private model response secret-token", error_type=category)

    monkeypatch.setattr(analysis, "analyze_memories", failed)
    scheduled = job(source)
    result = await execute_job(scheduled)
    assert not result["success"]
    report = json.loads(result["error"].split("MeetingSyncError: ", 1)[1])
    assert report["memories"]["error_type"] == expected
    record = digestion_db.get_record(ready)
    assert record["memory_error"] == expected and record["memory_attempts"] == 1 and record["claim_owner"] is None
    assert "private" not in result["error"] + caplog.text and "secret-token" not in result["error"] + caplog.text
    executions, total = list_executions_for_job(scheduled["id"])
    assert total == 1 and executions[0]["status"] == "failed"
