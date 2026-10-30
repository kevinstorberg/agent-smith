import asyncio
import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid5

import pytest
from psycopg2.extras import Json

from services.db import get_connection
from services.graphs.runtime import dispatch
from services.meetings import analysis, db, digestion_db, enrichment, manual_analysis, manual_stage, memory_db, service
from services.memory import db as vector_db
from tests.test_manual_analysis import finish_stage, jobs as jobs, payload as payload, saved as saved, target as target
from tests.test_meeting_sync import source as source


@pytest.fixture
def scripted(monkeypatch):
    class Scripted:
        def __init__(self):
            self.analyses = []
            self.publications = []
            self.stored = {}
            self.syncs = []
            self.fail_publish_once = False

        async def analyze(self, snapshot, window, previous, *, deadline):
            self.analyses.append(copy.deepcopy((snapshot, window, previous)))
            duplicate = {key: value for key, value in previous[-1].items() if key != "id"}
            duplicate["content"] = "  " + duplicate["content"].upper() + "  "
            return {"items": [duplicate, {"content": f"New useful fact {len(self.analyses)}", "kind": "fact",
                "tags": ["product", "security"], "evidence": [{"segment_id": window[0]["id"], "quote": window[0]["text"]}]}], "reason": ""}

        def publish(self, memory_id, content, repo=None, tags=None, *, created_at, source_type=None, source_id=None):
            assert source_type == "meeting" and source_id
            frozen = copy.deepcopy((content, repo, tags, created_at, source_type, source_id))
            assert memory_id not in self.stored or self.stored[memory_id] == frozen
            self.stored[memory_id] = frozen
            self.publications.append((memory_id, frozen))
            if self.fail_publish_once:
                self.fail_publish_once = False
                raise RuntimeError("Synthetic lost publication acknowledgement")
            return memory_id

        async def sync(self, *args, **kwargs):
            self.syncs.append((args, kwargs))
            return {"outcome": "completed"}

    calls = Scripted()
    monkeypatch.setattr(analysis, "analyze_memories", calls.analyze)
    monkeypatch.setattr(vector_db, "publish", calls.publish)
    monkeypatch.setattr(service, "sync_sources", calls.sync)
    def unexpected_provider(*args, **kwargs):
        raise AssertionError("Saved manual analysis must not construct a note provider")
    monkeypatch.setattr(enrichment, "capture_claimed", unexpected_provider)
    return calls


async def memory_pass(source):
    async with enrichment.DigestionRun(source.name) as run:
        claimed = await run.prepare_manual()
        if claimed:
            await run.generate_memories()
        return copy.deepcopy(run.memory_report), run.owner


def due(meeting_id):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_digestions SET memory_next_attempt_at=clock_timestamp() WHERE meeting_id=%s", (meeting_id,))


@pytest.mark.asyncio
async def test_manual_analysis_memory_graph_uses_saved_context_and_preserves_old_receipts(source, target, saved, payload, jobs, scripted):
    meeting_id, other_id = saved(person=target), saved()
    jobs("meeting_ingest")
    before, other = digestion_db.get_record(meeting_id), digestion_db.get_record(other_id)
    profile_before = {key: value for key, value in before.items() if key.startswith("profile_")}
    request_body = payload(meeting_id, scope="memories")
    manual_analysis.request_analysis(request_body)
    result = json.loads(await dispatch("meeting_ingest", {"source": source.name}))
    assert result["summary_outcome"] == "skipped" and result["memories"]["outcome"] == "done"
    assert len(scripted.analyses) == len(scripted.publications) == 1 and scripted.syncs == []
    after = digestion_db.get_record(meeting_id)
    artifact, original = after["memory_artifact"], before["memory_artifact"]
    assert artifact["items"][:1] == original["items"]
    assert artifact["created_at"] == original["created_at"]
    new_id = str(uuid5(enrichment._MEMORY_NAMESPACE, f"{meeting_id}:1"))
    assert [item["id"] for item in artifact["items"]] == original["published_ids"] + [new_id]
    assert artifact["published_ids"] == original["published_ids"] + [new_id]
    assert scripted.publications[0][0] == new_id
    assert scripted.analyses[0][2] == original["items"]
    assert artifact["attribution_snapshot"] != original["attribution_snapshot"]
    assert "old" not in [entry["term"] for entry in artifact["vocabulary"]]
    assert {key: value for key, value in after.items() if key.startswith("profile_")} == profile_before
    assert digestion_db.get_record(other_id) == other
    assert manual_analysis.get_request(request_body["request_id"])["status"] == "done"
    completed = copy.deepcopy(after)
    assert manual_analysis.request_analysis(request_body)["status"] == "done"
    assert digestion_db.get_record(meeting_id) == completed
    await dispatch("meeting_ingest", {"source": source.name, "force": True, "rerun": True})
    assert len(scripted.analyses) == len(scripted.publications) == 1
    assert len(scripted.syncs) == 1 and digestion_db.get_record(meeting_id)["memory_status"] == "done"


@pytest.mark.asyncio
async def test_manual_analysis_memory_fresh_second_pass_appends_after_prior_ids_and_fences_old_owner(source, saved, payload, jobs, scripted):
    meeting_id = saved()
    jobs("meeting_ingest")
    first_body = payload(meeting_id, scope="memories")
    manual_analysis.request_analysis(first_body)
    first, old_owner = await memory_pass(source)
    assert first["outcome"] == "done"
    first_row = digestion_db.get_record(meeting_id)
    second_body = payload(meeting_id, scope="memories")
    manual_analysis.request_analysis(second_body)
    pending = digestion_db.get_record(meeting_id)
    assert pending["memory_artifact"]["manual_request_id"] == second_body["request_id"]
    assert manual_analysis.request_analysis(first_body)["status"] == "done"
    assert digestion_db.get_record(meeting_id) == pending
    async with enrichment.DigestionRun(source.name) as run:
        assert await run.prepare_manual()
        with pytest.raises(db.ClaimLostError):
            memory_db.save_progress(meeting_id, old_owner, first_row["transcript_hash"], first_row["memory_artifact"], complete=True)
        await run.generate_memories()
        assert run.memory_report["outcome"] == "done"
    second = digestion_db.get_record(meeting_id)["memory_artifact"]
    assert second["items"][:2] == first_row["memory_artifact"]["items"]
    assert second["published_ids"][:2] == first_row["memory_artifact"]["published_ids"]
    assert second["items"][-1]["id"] == str(uuid5(enrichment._MEMORY_NAMESPACE, f"{meeting_id}:2"))
    assert second["created_at"] == first_row["memory_artifact"]["created_at"]
    assert len(scripted.analyses) == len(scripted.publications) == 2
    assert manual_analysis.get_request(second_body["request_id"])["status"] == "done"
    assert (await memory_pass(source))[0]["outcome"] == "idle"
    assert len(scripted.analyses) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("lost", ["ack", "receipt"])
async def test_manual_analysis_memory_lost_publication_retries_frozen_payload_without_agent(source, saved, payload, jobs, scripted, monkeypatch, lost):
    meeting_id = saved()
    jobs("meeting_ingest")
    manual_analysis.request_analysis(payload(meeting_id, scope="memories"))
    original = memory_db.save_progress
    if lost == "ack":
        scripted.fail_publish_once = True
    else:
        failures = []
        def lose_receipt(*args, **kwargs):
            artifact = args[3]
            if len(artifact["published_ids"]) == 2 and not failures:
                failures.append(True)
                raise RuntimeError("Synthetic lost publication receipt")
            return original(*args, **kwargs)
        monkeypatch.setattr(memory_db, "save_progress", lose_receipt)
    assert (await memory_pass(source))[0]["outcome"] == "failed"
    frozen = copy.deepcopy(digestion_db.get_record(meeting_id)["memory_artifact"])
    assert len(frozen["items"]) == 2 and len(frozen["published_ids"]) == 1
    due(meeting_id)
    assert (await memory_pass(source))[0]["outcome"] == "done"
    assert len(scripted.analyses) == 1 and len(scripted.publications) == 2
    assert scripted.publications[0] == scripted.publications[1]
    assert digestion_db.get_record(meeting_id)["memory_artifact"]["items"] == frozen["items"]


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["before_analysis", "before_publish"])
async def test_manual_analysis_memory_source_drift_blocks_paid_work_or_publication(source, saved, payload, jobs, scripted, monkeypatch, boundary):
    meeting_id = saved()
    jobs("meeting_ingest")
    request = manual_analysis.request_analysis(payload(meeting_id, scope="memories"))
    def change_source():
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("UPDATE meeting_summaries SET participants_revision=participants_revision+1 WHERE id=%s", (meeting_id,))
    if boundary == "before_publish":
        original = memory_db.assert_publishable
        def changed(*args):
            change_source()
            return original(*args)
        monkeypatch.setattr(memory_db, "assert_publishable", changed)
    async with enrichment.DigestionRun(source.name) as run:
        assert await run.prepare_manual()
        if boundary == "before_analysis":
            change_source()
        await run.generate_memories()
        assert run.memory_report["outcome"] == "failed"
    assert len(scripted.analyses) == (0 if boundary == "before_analysis" else 1)
    assert scripted.publications == []
    row = digestion_db.get_record(meeting_id)
    assert row["memory_status"] == "failed" and not row["manual_analysis"]["memory"]["active"]
    assert manual_analysis.get_request(request["request_id"])["status"] == "failed"
    with pytest.raises(manual_analysis.AnalysisConflict):
        manual_stage.resume_request(request["request_id"])
    if boundary == "before_publish":
        with pytest.raises(manual_analysis.AnalysisConflict, match="Resume unfinished"):
            manual_analysis.request_analysis(payload(meeting_id, scope="memories"))
    else:
        old_items = copy.deepcopy(row["memory_artifact"]["items"])
        fresh = manual_analysis.request_analysis(payload(meeting_id, scope="memories"))
        assert fresh["request_id"] != request["request_id"]
        assert (await memory_pass(source))[0]["outcome"] == "done"
        assert digestion_db.get_record(meeting_id)["memory_artifact"]["items"][:1] == old_items
        assert manual_analysis.get_request(request["request_id"])["status"] == "failed"


@pytest.mark.asyncio
async def test_manual_analysis_memory_terminal_failure_and_legacy_retry_keep_checkpoints_and_other_scope(source, target, saved, payload, jobs, scripted, monkeypatch):
    meeting_id = saved(person=target)
    jobs()
    jobs("meeting_ingest")
    request = manual_analysis.request_analysis(payload(meeting_id, scope="both", person=target))
    profile_control = digestion_db.get_record(meeting_id)["manual_analysis"]["profile"]
    failed_calls = []
    async def fail(*args, **kwargs):
        failed_calls.append(True)
        raise RuntimeError("Synthetic memory agent failure")
    monkeypatch.setattr(analysis, "analyze_memories", fail)
    for _ in range(3):
        assert (await memory_pass(source))[0]["outcome"] == "failed"
        due(meeting_id)
    failed = digestion_db.get_record(meeting_id)
    assert len(failed_calls) == 3 and failed["memory_status"] == "failed"
    assert not failed["manual_analysis"]["memory"]["active"]
    assert failed["manual_analysis"]["profile"] == profile_control
    assert manual_analysis.get_request(request["request_id"])["items"][0]["stages"]["memory"]["status"] == "failed"
    assert (await memory_pass(source))[0]["outcome"] == "idle"
    memory_db.retry_memories(meeting_id)
    resumed = digestion_db.get_record(meeting_id)
    assert resumed["memory_artifact"] == failed["memory_artifact"]
    assert resumed["manual_analysis"]["memory"]["request_id"] == request["request_id"]
    assert resumed["manual_analysis"]["memory"]["active"]
    assert resumed["manual_analysis"]["profile"] == profile_control
    monkeypatch.setattr(analysis, "analyze_memories", scripted.analyze)
    assert (await memory_pass(source))[0]["outcome"] == "done"
    assert len(scripted.analyses) == len(scripted.publications) == 1


@pytest.mark.asyncio
async def test_manual_analysis_memory_cancellation_releases_lease_without_losing_scope(source, saved, payload, jobs, scripted, monkeypatch):
    meeting_id = saved()
    jobs("meeting_ingest")
    request = manual_analysis.request_analysis(payload(meeting_id, scope="memories"))
    entered = asyncio.Event()
    async def pause(*args, **kwargs):
        entered.set()
        await asyncio.Future()
    monkeypatch.setattr(analysis, "analyze_memories", pause)
    running = asyncio.create_task(memory_pass(source))
    await asyncio.wait_for(entered.wait(), timeout=3)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    paused = digestion_db.get_record(meeting_id)
    assert paused["claim_owner"] is None and paused["claim_until"] is None
    assert paused["memory_status"] == "pending" and paused["manual_analysis"]["memory"]["active"]
    assert paused["memory_artifact"]["manual_request_id"] == request["request_id"]
    assert scripted.publications == []
    manual_stage.resume_request(request["request_id"])
    assert digestion_db.get_record(meeting_id)["memory_artifact"] == paused["memory_artifact"]
    monkeypatch.setattr(analysis, "analyze_memories", scripted.analyze)
    assert (await memory_pass(source))[0]["outcome"] == "done"
    assert len(scripted.analyses) == len(scripted.publications) == 1


def test_manual_analysis_get_keeps_one_consistent_snapshot_during_completion(source, saved, payload, jobs, monkeypatch):
    meeting_id = saved()
    jobs()
    request = manual_analysis.request_analysis(payload(meeting_id))
    reading, completed = threading.Event(), threading.Event()
    original = manual_analysis._receipt
    def paused(cur, receipt, current_jobs):
        reading.set()
        assert completed.wait(timeout=3)
        return original(cur, receipt, current_jobs)
    monkeypatch.setattr(manual_analysis, "_receipt", paused)
    def finish():
        assert reading.wait(timeout=3)
        finish_stage(meeting_id, "profile", status="done")
        completed.set()
    with ThreadPoolExecutor(max_workers=1) as pool:
        finished = pool.submit(finish)
        in_flight = manual_analysis.get_request(request["request_id"])
        finished.result(timeout=5)
    assert in_flight["status"] == "queued"
    monkeypatch.setattr(manual_analysis, "_receipt", original)
    assert manual_analysis.get_request(request["request_id"])["status"] == "done"


def test_manual_analysis_resumed_receipt_reads_live_progress_then_freezes_completed_counters(source, saved, payload, jobs):
    meeting_id = saved()
    jobs("meeting_ingest")
    request = manual_analysis.request_analysis(payload(meeting_id, scope="memories"))
    artifact = digestion_db.get_record(meeting_id)["memory_artifact"]
    artifact["offset"] = 1
    finish_stage(meeting_id, "memory", status="failed", artifact=artifact)
    failed = manual_analysis.get_request(request["request_id"])["items"][0]["stages"]["memory"]["progress"]
    assert failed["processed_units"] == 1 and failed["attempts"] == 3
    manual_stage.resume_request(request["request_id"])
    artifact["offset"] = 2
    next_attempt = datetime.now(timezone.utc) + timedelta(minutes=3)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_digestions SET memory_artifact=%s,memory_attempts=1,memory_next_attempt_at=%s WHERE meeting_id=%s",
                    (Json(artifact), next_attempt, meeting_id))
    current = manual_analysis.get_request(request["request_id"])["items"][0]["stages"]["memory"]
    assert current["status"] == "continued"
    assert current["progress"]["processed_units"] == 2 and current["progress"]["attempts"] == 1
    assert datetime.fromisoformat(current["progress"]["next_attempt_at"]) == next_attempt
    finish_stage(meeting_id, "memory", status="done", artifact=artifact)
    terminal = manual_analysis.get_request(request["request_id"])["items"][0]["stages"]["memory"]
    manual_analysis.request_analysis(payload(meeting_id, scope="memories"))
    assert digestion_db.get_record(meeting_id)["memory_artifact"]["offset"] == 0
    assert manual_analysis.get_request(request["request_id"])["items"][0]["stages"]["memory"] == terminal
