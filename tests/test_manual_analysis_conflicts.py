from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from services.api.routers.meetings import router
from services.db import get_connection
from services.meetings import analysis, db, digestion_db, enrichment, management_db, manual_analysis, memory_db, stage_db
from services.meetings.processing import ProcessingRun
from services.memory import db as vector_db
from tests.test_manual_analysis import finish_stage, jobs as jobs, payload as payload, saved as saved
from tests.test_meeting_sync import source as source
from tests.test_meeting_memory_agent import ScriptedModel, backend as backend, call, model as model


def change_participants(meeting_id):
    people = management_db.get_participants(meeting_id)
    assert people["edit_lock_reason"] is None
    app = FastAPI()
    app.include_router(router, prefix="/api/meetings")
    with TestClient(app) as client:
        response = client.put(f"/api/meetings/{meeting_id}/participants", json={
            "expected_revision": people["revision"],
            "participants": people["items"] + [{"name": "Synthetic added attendee"}],
            "expected_transcript_hash": digestion_db.get_record(meeting_id)["transcript_hash"],
        })
    assert response.status_code == 200, response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("late_failure", [False, True])
async def test_manual_analysis_conflicts_participant_edit_preserves_terminal_result(source, saved, payload, jobs, monkeypatch, late_failure):
    meeting_id = saved()
    jobs("meeting_ingest")
    request = manual_analysis.request_analysis(payload(meeting_id, scope="memories"))
    terminal = {}

    async def analyze(*args, **kwargs):
        change_participants(meeting_id)
        terminal["row"] = digestion_db.get_record(meeting_id)
        terminal["receipt"] = manual_analysis.get_request(request["request_id"])
        if late_failure:
            raise RuntimeError("Synthetic late model error")
        return {"items": [], "reason": "Synthetic late successful response"}

    def forbidden_publish(*args, **kwargs):
        raise AssertionError("Invalidated manual source must not publish")

    monkeypatch.setattr(analysis, "analyze_memories", analyze)
    monkeypatch.setattr(vector_db, "publish", forbidden_publish)
    async with enrichment.DigestionRun(source.name) as run:
        assert await run.prepare_manual()
        await run.generate_memories()
        assert digestion_db.get_record(meeting_id) == terminal["row"]
        report = run.memory_report
        assert report["outcome"] == "failed" and report["error_type"] == "ManualAnalysisInputChanged"
        assert report["progress"] == stage_db.progress(terminal["row"], "memory")
    after = digestion_db.get_record(meeting_id)
    assert after["memory_attempts"] == 3 and after["memory_error"] == "ManualAnalysisInputChanged"
    assert manual_analysis.get_request(request["request_id"]) == terminal["receipt"]
    assert digestion_db.claim_manual_memory([(source.provider, source.account_key)], "no-automatic-rerun") is None
    assert digestion_db.claim_digestion([(source.provider, source.account_key)], "no-ordinary-rerun") is None


@pytest.mark.parametrize("stage", ["memory", "profile"])
@pytest.mark.parametrize("status", ["done", "failed"])
def test_manual_analysis_conflicts_late_failure_cannot_rewrite_terminal_stage(source, saved, payload, jobs, stage, status):
    meeting_id = saved()
    jobs("meeting_ingest" if stage == "memory" else "persona")
    request = manual_analysis.request_analysis(payload(meeting_id, scope="memories" if stage == "memory" else "profiles"))
    owner = "terminal-owner"
    claimed = (digestion_db.claim_manual_memory([(source.provider, source.account_key)], owner) if stage == "memory"
               else digestion_db.claim_profile(source.name, owner))
    assert claimed
    finish_stage(meeting_id, stage, status=status)
    terminal = digestion_db.get_record(meeting_id)
    receipt = manual_analysis.get_request(request["request_id"])
    stage_db.record_failure(stage, meeting_id, owner, "LateWorkerFailure")
    assert digestion_db.get_record(meeting_id) == terminal
    assert manual_analysis.get_request(request["request_id"]) == receipt


@pytest.mark.parametrize("ownership", ["expired", "reassigned"])
def test_manual_analysis_conflicts_failure_still_requires_current_lease(source, saved, payload, jobs, ownership):
    meeting_id = saved()
    jobs("meeting_ingest")
    manual_analysis.request_analysis(payload(meeting_id, scope="memories"))
    assert digestion_db.claim_manual_memory([(source.provider, source.account_key)], "old-owner")
    with get_connection() as conn, conn.cursor() as cur:
        if ownership == "expired":
            cur.execute("UPDATE meeting_digestions SET claim_until=clock_timestamp()-interval '1 second' WHERE meeting_id=%s", (meeting_id,))
        else:
            cur.execute("UPDATE meeting_digestions SET claim_owner='new-owner' WHERE meeting_id=%s", (meeting_id,))
    before = digestion_db.get_record(meeting_id)
    with pytest.raises(db.ClaimLostError):
        memory_db.record_failure(meeting_id, "old-owner", "LateWorkerFailure")
    assert digestion_db.get_record(meeting_id) == before


def test_manual_analysis_conflicts_waiting_completion_rejects_committed_invalidation(source, saved, payload, jobs):
    meeting_id = saved()
    jobs("meeting_ingest")
    request = manual_analysis.request_analysis(payload(meeting_id, scope="memories"))
    owner = "waiting-owner"
    row = digestion_db.claim_manual_memory([(source.provider, source.account_key)], owner)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with db._cursor() as cur:
            cur.execute("SELECT meeting_id FROM meeting_digestions WHERE meeting_id=%s FOR UPDATE", (meeting_id,))
            future = pool.submit(memory_db.save_progress, meeting_id, owner, row["transcript_hash"], row["memory_artifact"], complete=True)
            from services.meetings import manual_stage

            manual_stage.invalidate_source(cur, meeting_id)
        with pytest.raises(db.ClaimLostError):
            future.result(timeout=3)
    after = digestion_db.get_record(meeting_id)
    assert after["memory_status"] == "failed" and after["memory_attempts"] == 3
    assert after["memory_error"] == "ManualAnalysisInputChanged"
    assert after["memory_artifact"] == row["memory_artifact"]
    assert manual_analysis.get_request(request["request_id"])["status"] == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["done", "failed"])
async def test_manual_analysis_conflicts_timeout_reports_terminal_state_even_after_progress(source, saved, payload, jobs, status):
    meeting_id = saved()
    jobs("meeting_ingest")
    manual_analysis.request_analysis(payload(meeting_id, scope="memories"))
    async with ProcessingRun(digestion_db.release_owner) as run:
        run.record = digestion_db.claim_manual_memory([(source.provider, source.account_key)], run.owner)
        async def work(record, *, deadline):
            artifact = {**record["memory_artifact"], "offset": 1}
            finish_stage(meeting_id, "memory", status=status, artifact=artifact)
            raise analysis.AnalysisBudgetExpired("Synthetic timeout after finalization")
        report = {}
        await run.run_stage("memory", report, work, memory_db.record_failure)
        assert report["outcome"] == status
        assert report.get("error_type") == ("SyntheticFailure" if status == "failed" else None)
        assert report["progress"] == stage_db.progress(digestion_db.get_record(meeting_id), "memory")


@pytest.mark.asyncio
async def test_manual_analysis_conflicts_old_worker_does_not_report_or_mutate_new_request(source, saved, payload, jobs):
    meeting_id = saved()
    jobs("meeting_ingest")
    old_request = manual_analysis.request_analysis(payload(meeting_id, scope="memories"))
    async with ProcessingRun(digestion_db.release_owner) as run:
        run.record = digestion_db.claim_manual_memory([(source.provider, source.account_key)], run.owner)
        original = stage_db.progress(run.record, "memory")
        observed = {}
        async def work(record, *, deadline):
            change_participants(meeting_id)
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute("UPDATE meeting_digestions SET claim_until=clock_timestamp()-interval '1 second' WHERE meeting_id=%s", (meeting_id,))
            new_request = manual_analysis.request_analysis(payload(meeting_id, scope="memories"))
            assert new_request["request_id"] != old_request["request_id"]
            assert digestion_db.claim_manual_memory([(source.provider, source.account_key)], "replacement-owner")
            observed["row"] = digestion_db.get_record(meeting_id)
            observed["receipt"] = manual_analysis.get_request(new_request["request_id"])
            raise RuntimeError("Synthetic old response")
        report = {}
        await run.run_stage("memory", report, work, memory_db.record_failure)
        assert report["outcome"] == "failed" and report["error_type"] == "ManualAnalysisSuperseded"
        assert report["progress"] == original
        assert digestion_db.get_record(meeting_id) == observed["row"]
        request_id = observed["receipt"]["request_id"]
        assert manual_analysis.get_request(request_id) == observed["receipt"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "done", "failed"])
async def test_manual_analysis_conflicts_ordinary_worker_still_raises_after_lease_replacement(source, saved, status):
    meeting_id = saved()
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_digestions SET memory_status='pending' WHERE meeting_id=%s", (meeting_id,))
    observed = {}
    async with ProcessingRun(digestion_db.release_owner) as run:
        run.record = digestion_db.claim_digestion([(source.provider, source.account_key)], run.owner)
        assert run.record
        async def work(record, *, deadline):
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute("UPDATE meeting_digestions SET claim_until=clock_timestamp()-interval '1 second' WHERE meeting_id=%s", (meeting_id,))
            assert digestion_db.claim_digestion([(source.provider, source.account_key)], "ordinary-replacement")
            if status != "pending":
                finish_stage(meeting_id, "memory", status=status)
            observed["row"] = digestion_db.get_record(meeting_id)
            raise RuntimeError("Synthetic response after lease replacement")
        with pytest.raises(db.ClaimLostError):
            await run.run_stage("memory", {}, work, memory_db.record_failure)
    assert digestion_db.get_record(meeting_id) == observed["row"]


@pytest.mark.asyncio
@pytest.mark.parametrize("manual", [False, True])
@pytest.mark.parametrize("edit_turn", [1, 3])
async def test_manual_analysis_conflicts_model_turn_stops_only_for_frozen_manual_source(
        source, saved, payload, jobs, backend, model, monkeypatch, manual, edit_turn):
    meeting_id = saved()
    if manual:
        jobs("meeting_ingest")
        request = manual_analysis.request_analysis(payload(meeting_id, scope="memories"))
    else:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("""UPDATE meeting_digestions SET memory_status='pending',
                memory_artifact=jsonb_set(memory_artifact,'{offset}','0'::jsonb) WHERE meeting_id=%s""", (meeting_id,))
    instance, _ = model([
        call("search_previous_memories", query="communication"),
        call("stage_memories", items=[], reason="No new durable information"),
        AIMessage(content="Finished"),
    ])
    original = ScriptedModel._agenerate
    observed = {}
    async def editing_model(self, *args, **kwargs):
        response = await original(self, *args, **kwargs)
        if len(self.seen) == edit_turn:
            change_participants(meeting_id)
            observed["row"] = digestion_db.get_record(meeting_id)
            if manual:
                observed["receipt"] = manual_analysis.get_request(request["request_id"])
        return response
    monkeypatch.setattr(ScriptedModel, "_agenerate", editing_model)
    async with enrichment.DigestionRun(source.name) as run:
        if manual:
            assert await run.prepare_manual()
        else:
            run.record = digestion_db.claim_digestion([(source.provider, source.account_key)], run.owner)
            assert run.record
        await run.generate_memories()
        if manual:
            assert len(instance.seen) == edit_turn and len(instance.replies) == 3 - edit_turn
            assert run.memory_report["outcome"] == "failed"
            assert run.memory_report["error_type"] == "ManualAnalysisInputChanged"
            assert digestion_db.get_record(meeting_id) == observed["row"]
            assert manual_analysis.get_request(request["request_id"]) == observed["receipt"]
        else:
            assert len(instance.seen) == 3 and run.memory_report["outcome"] == "done"
            assert digestion_db.get_record(meeting_id)["memory_attempts"] == 0
    assert backend[2] == []
