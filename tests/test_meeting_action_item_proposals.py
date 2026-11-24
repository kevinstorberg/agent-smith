from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from psycopg2.extras import Json, RealDictCursor

from services.action_items import db as tasks
from services.db import get_connection
from services.graphs.runtime import dispatch
from services.jobs.service import create_job_with_default_config, has_requested_work
from services.jobs.models.job import get_job
from services.meetings import db, enrichment, factory
from services.meetings.analysis import AnalysisBudgetExpired
from services.meetings.service import MeetingSyncError
from services.action_items import proposals as proposals
from tests.conftest import action_item_owner, jobs_cleanup
from tests.test_meeting_sync import STAMP, note, page, source as source

SUMMARY = "Morgan will send the design document. Morgan will prepare the checklist."
_clean_jobs = jobs_cleanup("AIFLOW %")


@pytest.fixture(autouse=True)
def scripted_action_item_filter(monkeypatch):
    from services.meetings import action_item_run
    from tests.test_action_item_matching import Encoder, BUDGET

    monkeypatch.setattr(action_item_run, "get_embeddings", lambda: Encoder())
    monkeypatch.setattr(action_item_run, "get_memory_token_budget", lambda: BUDGET)
    monkeypatch.setattr(action_item_run, "MEMORY_EMBEDDING_DIMENSION", 2)

    async def compare(snapshot, data, **kwargs):
        return {
            "items": [
                {
                    "candidate_id": index,
                    "actionable": True,
                    "matches": [],
                    "rationale": "Synthetic distinct unfinished work",
                    "evidence": data["candidates"][index]["evidence"],
                }
                for index in data["candidate_ids"]
            ]
        }

    monkeypatch.setattr(action_item_run.action_item_filter, "analyze_window", compare)


@pytest.fixture
def runs():
    from services.meetings import action_item_db

    return action_item_db


@pytest.fixture(autouse=True)
def clean_generated_proposals(source):
    yield
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """DELETE FROM action_item_proposal_receipts WHERE proposal_id IN (
                SELECT payload.proposal_id FROM action_item_proposal_payloads payload
                JOIN meeting_summaries meeting ON meeting.id=payload.meeting_id
                WHERE meeting.account_key=%s)""",
            (source.account_key,),
        )
        cursor.execute(
            """DELETE FROM action_item_proposals WHERE id IN (
                SELECT payload.proposal_id FROM action_item_proposal_payloads payload
                JOIN meeting_summaries meeting ON meeting.id=payload.meeting_id
                WHERE meeting.account_key=%s)""",
            (source.account_key,),
        )


@pytest.fixture
def saved(source):
    def save(external_id="one", text=SUMMARY, *, updated_at=STAMP):
        owner = "action-item-flow-fixture"
        assert db.claim_source(source, owner)
        try:
            result = db.save_progress(
                source,
                owner,
                {},
                summary=note(external_id, text, updated_at=updated_at),
            )
        finally:
            db.release_source(source, owner, "completed")
        return db.get_summary(result["id"])

    return save


@pytest.fixture
def worker(source):
    return get_job(
        create_job_with_default_config(
            "AIFLOW " + source.name,
            {"minutes": 5},
            {
                "graph_type": "meeting_ingest",
                "graph_inputs": {"source": source.name},
                "timeout": 600,
            },
        )
    )


@pytest.fixture
def http():
    from services.api.routers.meetings import router

    app = FastAPI()
    app.include_router(router, prefix="/meetings")
    with TestClient(app) as client:
        yield client


@pytest.fixture
def feed(source, monkeypatch):
    class Feed:
        notes = {"one": note(text=SUMMARY)}

    feed = Feed()

    class Provider:
        async def list_page(self, cursor=None, *, updated_after=None):
            return page(*feed.notes.values())

        async def get_summary(self, external_id):
            return feed.notes.get(external_id)

        async def aclose(self):
            return None

    monkeypatch.setitem(factory._PROVIDER_BUILDERS, "test", lambda config: Provider())
    return feed


def candidate(
    title="AIFLOW design document", quote="Morgan will send the design document."
):
    return {
        "action": "create",
        "changes": {"title": title},
        "rationale": "A meeting commitment awaits review.",
        "evidence": [{"segment_id": "summary-0", "quote": quote}],
    }


def proposal_rows(source):
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """SELECT proposal.* FROM action_item_proposals proposal
               JOIN action_item_proposal_payloads payload ON payload.proposal_id=proposal.id
               JOIN meeting_summaries meeting ON meeting.id=payload.meeting_id
               WHERE meeting.account_key=%s ORDER BY proposal.id""",
            (source.account_key,),
        )
        return [dict(row) for row in cursor.fetchall()]


def make_due(meeting_id):
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "UPDATE meeting_action_item_runs SET action_items_next_attempt_at=clock_timestamp() WHERE meeting_id=%s",
            (meeting_id,),
        )


async def generate(source):
    from services.meetings.action_item_run import ActionItemRun

    async with ActionItemRun(source.name) as run:
        await run.prepare()
        await run.generate_proposals()
        return run.report


async def graph_result(source, *, digest=True):
    try:
        return json.loads(
            await dispatch("meeting_ingest", {"source": source.name, "digest": digest})
        )
    except MeetingSyncError as error:
        return json.loads(str(error))


def install_analysis(monkeypatch, *, items=None):
    from services.meetings import action_item_run

    calls = []

    async def analyze(snapshot, inventory, previous, projects, **kwargs):
        calls.append(
            deepcopy(
                {
                    "snapshot": snapshot,
                    "inventory": inventory,
                    "previous": previous,
                    "projects": projects,
                }
            )
        )
        return {
            "items": deepcopy([candidate()] if items is None else items),
            "reason": "Explicit commitments only",
        }

    monkeypatch.setattr(
        action_item_run.action_item_analysis, "analyze_action_items", analyze
    )
    return calls


def test_new_import_enrolls_without_a_transcript_or_memory_dependency(
    source, saved, runs
):
    meeting = saved()
    record = runs.get_record(meeting["id"])
    assert record["action_items_status"] == "pending"
    assert record["source_revision"] == meeting["revision"]
    assert record["source_hash"] == meeting["content_hash"]
    assert record["snapshot"]["summary_text"] == SUMMARY
    assert runs.has_work([(source.provider, source.account_key)])
    assert not runs.has_work([("test", "unrelated-account")])
    assert proposal_rows(source) == []


def test_historical_source_updates_do_not_enroll_without_an_explicit_request(
    source, saved, runs, worker
):
    meeting = saved()
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "DELETE FROM meeting_action_item_runs WHERE meeting_id=%s", (meeting["id"],)
        )
    updated = saved(
        text=SUMMARY + " Later context.", updated_at=STAMP + timedelta(hours=1)
    )
    assert updated["revision"] == 2
    assert runs.get_record(meeting["id"]) is None
    assert not runs.has_work([(source.provider, source.account_key)])
    runs.request(meeting["id"], updated["revision"])
    assert runs.get_record(meeting["id"])["source_revision"] == 2
    assert has_requested_work(worker)


def test_changed_enrolled_summary_resets_only_its_own_analysis(source, saved, runs):
    meeting = saved()
    claim = runs.claim(
        [(source.provider, source.account_key)], action_item_owner("first-owner")
    )
    runs.save_progress(
        meeting["id"],
        action_item_owner("first-owner"),
        {"items": [], "reason": "None", "offset": 1, "total_units": 1},
        complete=True,
    )
    runs.release_owner(action_item_owner("first-owner"))
    assert claim["source_revision"] == 1 and not runs.has_work(
        [(source.provider, source.account_key)]
    )
    updated = saved(
        text=SUMMARY + " Later context.", updated_at=STAMP + timedelta(hours=1)
    )
    current = runs.get_record(meeting["id"])
    assert (
        current["action_items_status"] == "pending"
        and current["source_revision"] == updated["revision"]
    )
    assert (
        current["action_items_artifact"] == {} and current["action_items_attempts"] == 0
    )
    assert runs.has_work([(source.provider, source.account_key)])


def test_claim_expiry_and_owner_cleanup_cannot_steal_another_worker(
    source, saved, runs
):
    meeting = saved()
    identities = [(source.provider, source.account_key)]
    assert (
        runs.claim(identities, action_item_owner("first-owner"))["meeting_id"]
        == meeting["id"]
    )
    assert runs.claim(identities, action_item_owner("second-owner")) is None
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "UPDATE meeting_action_item_runs SET claim_until=clock_timestamp()-interval '1 second' WHERE meeting_id=%s",
            (meeting["id"],),
        )
    assert (
        runs.claim(identities, action_item_owner("second-owner"))["meeting_id"]
        == meeting["id"]
    )
    runs.release_owner(action_item_owner("first-owner"))
    assert runs.get_record(meeting["id"])["claim_owner"] == action_item_owner(
        "second-owner"
    )
    with pytest.raises(db.ClaimLostError):
        runs.save_progress(meeting["id"], action_item_owner("first-owner"), {})
    runs.release_owner(action_item_owner("second-owner"))
    assert runs.get_record(meeting["id"])["claim_owner"] is None


def test_retry_bounds_are_visible_and_manual_retry_resets_terminal_failure(
    source, saved, runs, worker
):
    meeting = saved()
    identities = [(source.provider, source.account_key)]
    for attempt in range(1, 4):
        owner = action_item_owner(f"failing-owner-{attempt}")
        make_due(meeting["id"])
        assert runs.claim(identities, owner)
        runs.record_failure(meeting["id"], owner, "SyntheticFailure")
        current = runs.get_record(meeting["id"])
        assert current["action_items_attempts"] == attempt
        assert current["action_items_status"] == (
            "failed" if attempt == 3 else "pending"
        )
        assert current["action_items_error"] == "SyntheticFailure"
        if attempt < 3:
            next_attempt = datetime.fromisoformat(
                current["action_items_next_attempt_at"]
            )
            delay = (next_attempt - datetime.now(timezone.utc)).total_seconds()
            baseline = 60 * 5 ** (attempt - 1)
            assert baseline * 0.8 - 3 <= delay <= baseline * 1.2 + 3
        runs.release_owner(owner)
    assert not runs.has_work(identities)
    assert runs.status(meeting["id"], worker_available=True)["status"] == "failed"
    runs.request(meeting["id"], meeting["revision"])
    refreshed = runs.get_record(meeting["id"])
    assert (
        refreshed["action_items_attempts"] == 0
        and refreshed["action_items_error"] is None
    )
    assert refreshed["action_items_status"] == "pending" and has_requested_work(worker)


@pytest.mark.asyncio
async def test_summary_stage_generates_once_even_when_transcript_capture_is_unsupported(
    source, feed, runs, monkeypatch
):
    calls = install_analysis(monkeypatch)
    result = await graph_result(source)
    meeting = db.list_summaries(source=source.name)["items"][0]
    assert result["action_items"]["outcome"] == "done"
    assert len(calls) == 1 and calls[0]["snapshot"]["summary_text"] == SUMMARY
    assert len(proposal_rows(source)) == 1
    assert runs.get_record(meeting["id"])["action_items_status"] == "done"
    second = await graph_result(source)
    assert second["action_items"]["outcome"] == "idle"
    assert len(calls) == len(proposal_rows(source)) == 1


@pytest.mark.asyncio
async def test_memory_failure_does_not_suppress_proposal_generation(
    source, saved, feed, runs, monkeypatch
):
    meeting = saved()
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "UPDATE meeting_digestions SET transcript_status='ready',memory_status='pending',transcript_hash=%s WHERE meeting_id=%s",
            ("a" * 64, meeting["id"]),
        )

    async def fail_memories(self):
        self.memory_report = {
            "outcome": "failed",
            "error_type": "SyntheticMemoryFailure",
        }

    monkeypatch.setattr(enrichment.DigestionRun, "generate_memories", fail_memories)
    calls = install_analysis(monkeypatch)
    result = await graph_result(source)
    assert result["memories"]["outcome"] == "failed"
    assert result["action_items"]["outcome"] == "done"
    assert len(calls) == len(proposal_rows(source)) == 1


@pytest.mark.asyncio
async def test_digest_false_reaches_actual_node_without_running_analysis(
    source, feed, runs, monkeypatch
):
    def forbidden(*args, **kwargs):
        pytest.fail("digest=false must never initialize the proposal model")

    from services.meetings import action_item_run

    monkeypatch.setattr(
        action_item_run.action_item_analysis, "analyze_action_items", forbidden
    )
    result = await graph_result(source, digest=False)
    meeting = db.list_summaries(source=source.name)["items"][0]
    assert runs.get_record(meeting["id"])["action_items_status"] == "pending"
    assert proposal_rows(source) == []
    assert result["action_items"]["outcome"] in {"disabled", "skipped"}


@pytest.mark.asyncio
async def test_budget_resume_reuses_frozen_model_result_and_does_not_duplicate_proposals(
    source, saved, runs, monkeypatch
):
    meeting = saved()
    second = candidate("AIFLOW checklist", "Morgan will prepare the checklist.")
    calls = install_analysis(monkeypatch, items=[candidate(), second])
    attempts = []

    def timed_out(snapshot, items, result, **kwargs):
        assert kwargs.get("lease_owner")
        attempts.append(items)
        raise AnalysisBudgetExpired(
            "Synthetic budget exhausted after durable filtering"
        )

    with monkeypatch.context() as patch:
        patch.setattr(proposals, "publish_filtered_batch", timed_out)
        first = await generate(source)
    assert first["outcome"] == "continued" and proposal_rows(source) == []
    assert len(attempts) == 1
    assert runs.get_record(meeting["id"])["action_items_attempts"] == 0
    final = await generate(source)
    assert final["outcome"] == "done" and len(proposal_rows(source)) == 2
    assert len(calls) == 1
    assert runs.get_record(meeting["id"])["claim_owner"] is None


@pytest.mark.asyncio
async def test_cancelled_generation_releases_its_lease_and_can_be_retried(
    source, saved, runs, monkeypatch
):
    from services.meetings import action_item_run

    meeting = saved()
    started = asyncio.Event()

    async def wait(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(
        action_item_run.action_item_analysis, "analyze_action_items", wait
    )
    task = asyncio.create_task(generate(source))
    await asyncio.wait_for(started.wait(), timeout=3)
    assert runs.get_record(meeting["id"])["claim_owner"]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert runs.get_record(meeting["id"])["claim_owner"] is None
    assert proposal_rows(source) == []
    calls = install_analysis(monkeypatch, items=[])
    report = await generate(source)
    assert report["outcome"] == "done" and len(calls) == 1


@pytest.mark.asyncio
async def test_committed_proposal_before_lost_checkpoint_replays_without_model_or_duplicate(
    source, saved, runs, monkeypatch
):
    meeting = saved()
    calls = install_analysis(monkeypatch)
    persist = proposals.publish_filtered_batch

    def committed_then_cancelled(snapshot, items, result, **kwargs):
        assert kwargs.get("lease_owner")
        persist(snapshot, items, result, **kwargs)
        raise asyncio.CancelledError()

    with monkeypatch.context() as patch:
        patch.setattr(proposals, "publish_filtered_batch", committed_then_cancelled)
        with pytest.raises(asyncio.CancelledError):
            await generate(source)
    assert len(proposal_rows(source)) == 1
    assert runs.get_record(meeting["id"])["claim_owner"] is None
    result = await generate(source)
    assert result["outcome"] == "idle" and len(calls) == 1
    assert len(proposal_rows(source)) == 1


@pytest.mark.asyncio
async def test_empty_context_finishes_once_with_visible_reason_and_no_task_mutation(
    source, saved, runs, monkeypatch
):
    meeting = saved()
    calls = install_analysis(monkeypatch, items=[])
    report = await generate(source)
    assert report["outcome"] == "done" and proposal_rows(source) == []
    status = runs.status(meeting["id"], worker_available=True)
    assert status["status"] == "done" and status["proposal_count"] == 0
    await generate(source)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_source_change_during_model_await_cannot_publish_stale_proposals(
    source, saved, runs, monkeypatch
):
    from services.meetings import action_item_analysis

    meeting = saved()

    async def changed_during_analysis(*args, **kwargs):
        saved(
            text=SUMMARY + " The meeting was corrected.",
            updated_at=STAMP + timedelta(hours=1),
        )
        return {
            "items": [candidate()],
            "reason": "A result from the superseded snapshot",
        }

    monkeypatch.setattr(
        action_item_analysis, "analyze_action_items", changed_during_analysis
    )
    with pytest.raises(db.ClaimLostError):
        await generate(source)
    record = runs.get_record(meeting["id"])
    assert record["source_revision"] == 2 and record["action_items_status"] == "pending"
    assert record["action_items_artifact"] == {} and record["claim_owner"] is None
    assert proposal_rows(source) == []
    calls = install_analysis(monkeypatch)
    assert (await generate(source))["outcome"] == "done"
    assert len(calls) == 1 and calls[0]["snapshot"]["revision"] == 2
    assert len(proposal_rows(source)) == 1


@pytest.mark.asyncio
async def test_actual_inventory_above_old_row_limit_reaches_model_completely(
    source, saved, runs, monkeypatch
):
    meeting = saved()
    calls = install_analysis(monkeypatch, items=[])
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """INSERT INTO action_items(title,status,completed_at)
               SELECT 'AIFLOW inventory '||number,'completed',clock_timestamp()
               FROM generate_series(1,201) number"""
        )
    try:
        result = await generate(source)
        assert result["outcome"] == "done"
        assert len(calls) == 1
        assert (
            len(
                [
                    row
                    for row in calls[0]["inventory"]
                    if row["title"].startswith("AIFLOW inventory ")
                ]
            )
            == 201
        )
        assert any(
            row["title"] == "AIFLOW inventory 201" for row in calls[0]["inventory"]
        )
        assert runs.get_record(meeting["id"])["action_items_attempts"] == 0
        assert proposal_rows(source) == []
    finally:
        with get_connection() as conn, conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM action_items WHERE title LIKE 'AIFLOW inventory %'"
            )


def test_http_request_queues_historical_meeting_without_generating_or_mutating_tasks(
    source, saved, runs, worker, http, monkeypatch
):
    meeting = saved()
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "DELETE FROM meeting_action_item_runs WHERE meeting_id=%s", (meeting["id"],)
        )
        cursor.execute("SELECT count(*) FROM action_items")
        tasks_before = cursor.fetchone()[0]
    calls = install_analysis(monkeypatch)
    response = http.post(
        f"/meetings/{meeting['id']}/action-item-proposals",
        json={"expected_revision": meeting["revision"]},
    )
    assert response.status_code == 202
    assert (
        response.json()["status"] == "pending"
        and response.json()["worker_available"] is True
    )
    record = runs.get_record(meeting["id"])
    assert (
        record["source_revision"] == meeting["revision"]
        and record["source_hash"] == meeting["content_hash"]
    )
    assert calls == [] and proposal_rows(source) == [] and has_requested_work(worker)
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM action_items")
        assert cursor.fetchone()[0] == tasks_before


def test_http_stale_revision_and_running_request_preserve_existing_generation(
    source, saved, runs, worker, http
):
    meeting = saved()
    endpoint = f"/meetings/{meeting['id']}/action-item-proposals"
    stale = http.post(endpoint, json={"expected_revision": meeting["revision"] + 1})
    assert stale.status_code == 409 and "changed" in stale.json()["detail"].lower()
    assert runs.get_record(meeting["id"])["source_revision"] == meeting["revision"]
    runs.claim(
        [(source.provider, source.account_key)], action_item_owner("in-flight-owner")
    )
    try:
        running = http.post(endpoint, json={"expected_revision": meeting["revision"]})
        assert (
            running.status_code == 409 and "already" in running.json()["detail"].lower()
        )
        assert runs.get_record(meeting["id"])["claim_owner"] == action_item_owner(
            "in-flight-owner"
        )
        assert proposal_rows(source) == []
    finally:
        runs.release_owner(action_item_owner("in-flight-owner"))


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"expected_revision": 0},
        {"expected_revision": -1},
        {"expected_revision": True},
        {"expected_revision": "1"},
        {"expected_revision": 1.0},
        {"expected_revision": 1, "owner": "Removed setup field"},
        {"expected_revision": 1, "unexpected": "Not accepted"},
    ],
)
def test_http_request_contract_rejects_nonpositive_or_coerced_revisions_and_unknown_fields(
    source, saved, runs, http, body
):
    meeting = saved()
    response = http.post(f"/meetings/{meeting['id']}/action-item-proposals", json=body)
    assert response.status_code == 422
    assert runs.get_record(meeting["id"])["action_items_attempts"] == 0
    assert proposal_rows(source) == []


def test_http_request_requires_a_real_covering_worker_and_unknown_meeting_returns_404(
    source, saved, runs, http
):
    meeting = saved()
    assert not runs.has_worker(meeting)
    response = http.post(
        f"/meetings/{meeting['id']}/action-item-proposals",
        json={"expected_revision": meeting["revision"]},
    )
    assert response.status_code == 503 and "job" in response.json()["detail"].lower()
    assert proposal_rows(source) == []
    missing = http.post(
        f"/meetings/{uuid4()}/action-item-proposals", json={"expected_revision": 1}
    )
    assert missing.status_code == 404


def test_processing_http_status_exposes_progress_without_raw_summary_or_proposal_artifacts(
    source, saved, runs, worker, http
):
    meeting = saved()
    artifact = {
        "items": [{"changes": {"title": "PRIVATE-PROPOSAL-CONTENT"}}],
        "input_snapshot": {"summary_text": "PRIVATE-RAW-SUMMARY"},
        "reason": "Some commitments require review",
        "offset": 0,
        "published_ids": [],
    }
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "UPDATE meeting_action_item_runs SET action_items_artifact=%s WHERE meeting_id=%s",
            (Json(artifact), meeting["id"]),
        )
    response = http.get(f"/meetings/{meeting['id']}/processing")
    assert response.status_code == 200
    state = response.json()["action_item_proposals"]
    assert state["worker_available"] is True and state["status"] == "pending"
    assert state["attempts"] == 0 and state["proposal_count"] == 0
    assert "PRIVATE-RAW-SUMMARY" not in response.text
    assert "PRIVATE-PROPOSAL-CONTENT" not in response.text
    assert SUMMARY not in response.text and "input_snapshot" not in response.text


@pytest.mark.asyncio
async def test_task_drift_reanalyzes_before_atomic_batch_publication(
    source, saved, runs, monkeypatch
):
    from services.meetings import action_item_analysis

    completion = "Morgan confirmed the integration review is complete."
    meeting = saved(text=SUMMARY + " " + completion)
    target = tasks.create(
        {"title": "AIFLOW integration review", "description": "Original notes"}
    )
    calls = []

    async def analyze(snapshot, inventory, previous, projects, **kwargs):
        calls.append(deepcopy({"inventory": inventory, "previous": previous}))
        reviewed = next(row for row in inventory if row["id"] == target["id"])
        if len(calls) == 1:
            tasks.update(
                target["id"],
                {
                    "expected_revision": reviewed["revision"],
                    "description": "Later manual notes",
                },
            )
        update = {
            "action": "update",
            "target_id": reviewed["id"],
            "expected_revision": reviewed["revision"],
            "changes": {"status": "completed"},
            "rationale": "The summary explicitly reports completion.",
            "evidence": [{"segment_id": "summary-0", "quote": completion}],
        }
        return {
            "items": [candidate(), update],
            "reason": "Review supported commitments",
        }

    monkeypatch.setattr(action_item_analysis, "analyze_action_items", analyze)
    try:
        first = await generate(source)
        assert (
            first["outcome"] == "failed"
            and first["error_type"] == "ProposalConflictError"
        )
        first_rows = proposal_rows(source)
        assert first_rows == []
        failed = runs.get_record(meeting["id"])
        assert (
            failed["action_items_attempts"] == 1
            and failed["action_items_status"] == "pending"
        )
        assert "items" not in failed["action_items_artifact"]
        assert failed["action_items_artifact"]["published_ids"] == []
        assert tasks.get(target["id"])["status"] == "open"
        make_due(meeting["id"])
        second = await generate(source)
        assert second["outcome"] == "done" and len(calls) == 2
        reviewed = next(
            row for row in calls[1]["inventory"] if row["id"] == target["id"]
        )
        assert (
            reviewed["revision"] == 2
            and reviewed["description"] == "Later manual notes"
        )
        assert calls[1]["previous"] == []
        rows = proposal_rows(source)
        assert len(rows) == 2
        update = next(row for row in rows if row["action"] == "update")
        assert update["target_id"] == target["id"] and update["base_version"] == 2
        assert set(
            runs.get_record(meeting["id"])["action_items_artifact"]["published_ids"]
        ) == {row["id"] for row in rows}
        live = tasks.get(target["id"])
        assert live["status"] == "open" and live["revision"] == 2
        assert live["description"] == "Later manual notes"
    finally:
        current = tasks.get(target["id"])
        tasks.delete(current["id"], {"expected_revision": current["revision"]})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "corruption", ["offset_out_of_range", "changed_frozen_summary"]
)
async def test_invalid_checkpoint_fails_before_publication_and_manual_generation_recovers(
    source, saved, runs, worker, monkeypatch, corruption
):
    meeting = saved()
    calls = install_analysis(monkeypatch)

    def stop_before_publication(snapshot, items, result, **kwargs):
        assert kwargs.get("lease_owner")
        raise asyncio.CancelledError()

    with monkeypatch.context() as patch:
        patch.setattr(proposals, "publish_filtered_batch", stop_before_publication)
        with pytest.raises(asyncio.CancelledError):
            await generate(source)
    record = runs.get_record(meeting["id"])
    artifact = deepcopy(record["action_items_artifact"])
    assert len(artifact["items"]) == 1 and artifact["offset"] == 0
    assert len(calls) == 1 and proposal_rows(source) == []
    if corruption == "offset_out_of_range":
        artifact["offset"] = len(artifact["items"]) + 1
    else:
        artifact["input_snapshot"]["summary_text"] = "A summary that was never captured"
        artifact["input_hash"] = "f" * 64
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "UPDATE meeting_action_item_runs SET action_items_artifact=%s WHERE meeting_id=%s",
            (Json(artifact), meeting["id"]),
        )
    failed = await generate(source)
    assert failed["outcome"] == "failed" and failed["error_type"] == "ValueError"
    assert len(calls) == 1 and proposal_rows(source) == []
    current = runs.get_record(meeting["id"])
    assert current["action_items_attempts"] == 1 and current["claim_owner"] is None
    runs.request(meeting["id"], meeting["revision"])
    reset = runs.get_record(meeting["id"])
    assert reset["action_items_artifact"] == {} and reset["action_items_attempts"] == 0
    assert (await generate(source))["outcome"] == "done"
    assert len(calls) == 2 and len(proposal_rows(source)) == 1
