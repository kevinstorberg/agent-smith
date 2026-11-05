import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import logging
from types import SimpleNamespace
from uuid import uuid4

import pytest

from services.graphs.runtime import dispatch
from services.meetings import (
    analysis,
    digestion,
    digestion_db,
    label_analysis,
    management_db,
    processing,
    service,
    work_requests,
)
from services.observability import billable_operation, current_trigger, trigger_context
from services.personas import assessment, assessment_db
from services.personas import service as persona_service
from tests.test_meeting_memory_flow import (
    agents as agents,
    feed as feed,
    ready as ready,
)
from tests.test_meeting_sync import Provider, note, source as source


SECRET = "PRIVATE_SOURCE_REASON_TRANSCRIPT_CANARY"
STAMP = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def capture_work_logs(caplog):
    caplog.set_level(logging.INFO, logger="agent_smith.work")
    caplog.set_level(logging.INFO, logger="agent_smith.billable")


def decisions(caplog):
    return [
        record.work_decision
        for record in caplog.records
        if hasattr(record, "work_decision")
    ]


def stage_record(reason=None):
    controls = (
        work_requests.mark({}, "memory", reason, requested_at=STAMP) if reason else {}
    )
    return {
        "meeting_id": str(uuid4()),
        "memory_status": "pending",
        "memory_attempts": 2,
        "memory_artifact": {
            "offset": 3,
            "items": [],
            "published_ids": [],
            "reason": SECRET,
            "input_source": "summary",
            "input_hash": "a" * 64,
            "input_snapshot": {
                "revision": 4,
                "source_name": "work",
                "summary_text": SECRET,
            },
        },
        "snapshot": {"revision": 1, "summary_text": SECRET},
        "manual_analysis": controls,
        "transcript": {"segments": [{"text": SECRET}]},
        "transcript_hash": "b" * 64,
    }


def test_stage_metadata_uses_existing_marker_and_frozen_summary_without_payload():
    row = stage_record("memory_retry")
    request_id = str(uuid4())
    row["manual_analysis"]["memory"] = {
        "request_id": request_id,
        "active": True,
        "source": {"summary_text": SECRET},
    }
    original = deepcopy(row)

    fields = processing.stage_metadata(row, "memory")

    assert fields["reason"] == "memory_retry" and fields["requested_at"] == STAMP
    assert fields["manual_request_id"] == request_id
    assert fields["source_kind"] == "summary" and fields["source_hash"] == "a" * 64
    assert (
        fields["source_revision"] == 4
        and fields["checkpoint"] == 3
        and fields["attempt"] == 3
    )
    assert SECRET not in repr(fields)
    assert row == original


@pytest.mark.parametrize(
    "marker",
    [
        None,
        {"requested_at": -1, "reason": "memory_retry"},
        {"requested_at": 1, "reason": SECRET},
        {"requested_at": 1, "reason": "memory_retry", "extra": SECRET},
    ],
)
def test_legacy_or_invalid_queued_reason_stays_unknown(marker):
    row = stage_record()
    row["manual_analysis"] = {"memory": {"active": True, "request_id": str(uuid4())}}
    if marker is not None:
        row["manual_analysis"]["work_requests"] = {"memory": marker}

    fields = processing.stage_metadata(row, "memory")

    assert fields["reason"] == "unknown" and "requested_at" not in fields
    assert fields["checkpoint"] == 3 and fields["attempt"] == 3
    assert SECRET not in repr(fields)


@pytest.mark.asyncio
async def test_concurrent_stage_work_inherits_its_own_durable_cause_and_resets_context(
    caplog,
):
    seen = {}
    rows = [stage_record("memory_retry"), stage_record("manual_resume")]

    async def run(row):
        async def work(record, *, deadline):
            with billable_operation("synthetic", "stage_probe"):
                captured = current_trigger()
                await asyncio.sleep(0)
                assert current_trigger() == captured
                seen[record["meeting_id"]] = captured
            row["memory_status"] = "done"

        async with processing.ProcessingRun(
            lambda owner: None, get_record=lambda context_id: row
        ) as runner:
            runner.record = row
            report = {}
            await runner.run_stage("memory", report, work, lambda *args: None)
            assert report["outcome"] == "done"

    with trigger_context(trigger="job", graph="meeting_ingest", execution_id=37):
        before = current_trigger()
        await asyncio.gather(*(run(row) for row in rows))
        assert current_trigger() == before
    assert current_trigger() == {}
    for row, reason in zip(rows, ("memory_retry", "manual_resume"), strict=True):
        fields = seen[row["meeting_id"]]
        assert fields["meeting_id"] == row["meeting_id"] and fields["reason"] == reason
        assert fields["stage"] == "memory" and fields["source_kind"] == "summary"
        assert fields["execution_id"] == 37
    assert SECRET not in caplog.text
    assert (
        len([item for item in decisions(caplog) if item["decision"] == "stage_result"])
        == 2
    )


@pytest.mark.asyncio
async def test_cancelled_stage_preserves_cancellation_identity_and_does_not_leak_context(
    caplog,
):
    row = stage_record("memory_retry")
    cancellation = asyncio.CancelledError(SECRET)

    async def cancelled(record, *, deadline):
        with billable_operation("synthetic", "cancel_probe"):
            raise cancellation

    with trigger_context(trigger="job", graph="meeting_ingest"):
        before = current_trigger()
        async with processing.ProcessingRun(
            lambda owner: None, get_record=lambda context_id: row
        ) as runner:
            runner.record = row
            with pytest.raises(asyncio.CancelledError) as raised:
                await runner.run_stage("memory", {}, cancelled, lambda *args: None)
            assert raised.value is cancellation
        assert current_trigger() == before
    assert current_trigger() == {}
    assert SECRET not in caplog.text


@pytest.mark.asyncio
async def test_capture_context_identifies_transcript_work_and_real_retry_reason(
    monkeypatch, caplog
):
    row = stage_record("transcript_retry")
    row.update(transcript_status="pending", attempts=1)
    captured = []
    context = {
        "id": row["meeting_id"],
        "provider": "test",
        "account_key": "account",
        "revision": 5,
    }
    monkeypatch.setattr(digestion.db, "get_context", lambda meeting_id: context)

    async def close():
        return None

    provider = SimpleNamespace(get_transcript_page=lambda *args: None, aclose=close)
    monkeypatch.setattr(digestion, "build_meeting_provider", lambda config: provider)

    async def capture(*args):
        captured.append(current_trigger())
        return 2

    monkeypatch.setattr(digestion, "_capture", capture)
    report = {}
    await digestion.capture_claimed(
        {("test", "account"): SimpleNamespace(name="work")}, "owner", row, report
    )

    assert report["outcome"] == "ready" and report["segments"] == 2
    assert captured[0]["stage"] == "transcript_capture"
    assert (
        captured[0]["source_kind"] == "transcript"
        and captured[0]["source_revision"] == 5
    )
    assert captured[0]["reason"] == "transcript_retry" and captured[0]["attempt"] == 2
    assert SECRET not in caplog.text


@pytest.mark.asyncio
async def test_summary_agent_context_uses_frozen_input_and_idle_poll_does_not_repeat_work(
    source, ready, agents, monkeypatch, caplog
):
    seen = []

    async def analyze(snapshot, window, previous, **kwargs):
        seen.append(current_trigger())
        return await agents.analyze(snapshot, window, previous, **kwargs)

    monkeypatch.setattr(analysis, "analyze_memories", analyze)
    management_db.request_processing(ready)
    await dispatch("meeting_ingest", {"source": source.name})
    row = digestion_db.get_record(ready)
    frozen = row["memory_artifact"]["input_snapshot"]["summary_text"]
    assert (
        seen[0]["reason"] == "process_meeting" and seen[0]["source_kind"] == "summary"
    )
    assert seen[0]["source_hash"] == hashlib.sha256(frozen.encode()).hexdigest()
    assert (
        seen[0]["source_revision"]
        == row["memory_artifact"]["input_snapshot"]["revision"]
    )

    await dispatch("meeting_ingest", {"source": source.name})

    assert len(seen) == 1 and len(agents.publications) == 1
    assert any(
        item["decision"] == "no_eligible_work" and item["stage"] == "memory"
        for item in decisions(caplog)
    )


@pytest.mark.asyncio
async def test_label_suggestions_have_a_distinct_summary_stage_without_logging_data(
    monkeypatch, caplog
):
    result = {"labels": ["product"], "reason": SECRET}
    captured = []

    async def analyze(context, **kwargs):
        captured.append(current_trigger())
        assert kwargs["model_role"] == "meeting_memory"
        return result

    monkeypatch.setattr(label_analysis, "run_analysis", analyze)
    actual = await label_analysis.suggest_labels(
        {
            "id": str(uuid4()),
            "revision": 2,
            "title": SECRET,
            "summary_text": SECRET,
            "labels": [],
        }
    )

    assert actual is result
    assert (
        captured[0]["stage"] == "meeting_label_suggestion"
        and captured[0]["source_kind"] == "summary"
    )
    assert SECRET not in caplog.text


@pytest.mark.asyncio
async def test_persona_assessment_has_independent_saved_claim_context(
    monkeypatch, caplog
):
    profile_id = str(uuid4())
    snapshot = {
        "id": profile_id,
        "input_hash": "c" * 64,
        "profile": {"revision": 3, "assessment_attempts": 1},
        "claims": [{"id": str(uuid4())}],
    }
    observed = []
    provider = SimpleNamespace(
        get_record=lambda context_id: None, release_owner=lambda owner: None
    )
    monkeypatch.setattr(persona_service, "build_context_provider", lambda: provider)
    monkeypatch.setattr(assessment_db, "claim", lambda *args: snapshot)
    monkeypatch.setattr(assessment_db, "release_owner", lambda owner: None)
    monkeypatch.setattr(
        assessment_db,
        "insufficient",
        lambda row: {"drivers": {"status": "insufficient_evidence"}},
    )
    monkeypatch.setattr(assessment_db, "relationship_insufficient", lambda row: [])
    monkeypatch.setattr(assessment_db, "apply", lambda *args: {})

    async def synthesize(*args, **kwargs):
        observed.append(current_trigger())
        return {"sections": {}, "relationships": [], "reason": SECRET}

    monkeypatch.setattr(assessment, "synthesize", synthesize)
    async with persona_service.PersonaRun(profile_id=profile_id) as runner:
        await runner.build_assessments()
        assert runner.assessment_report["outcome"] == "done"

    assert len(observed) == 1
    assert (
        observed[0]["stage"] == "persona_assessment"
        and observed[0]["source_kind"] == "saved_claims"
    )
    assert (
        observed[0]["profile_id"] == profile_id
        and observed[0]["source_hash"] == "c" * 64
    )
    assert observed[0]["attempt"] == 2 and observed[0]["reason"] == "unknown"
    assert SECRET not in caplog.text


@pytest.mark.asyncio
async def test_sync_logs_processed_references_without_renaming_api_statistics(
    source, caplog
):
    caplog.set_level(logging.INFO, logger=service.__name__)
    result = await service.sync_source(
        source.name, provider=Provider([note(text=SECRET)])
    )

    assert result["processed"] == result["created"] == 1
    assert "processed_refs" not in result
    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == service.__name__
    ]
    assert any("processed_refs=1" in message for message in messages)
    assert any(
        item["decision"] == "summary_saved" and item["stage_status"] == "created"
        for item in decisions(caplog)
    )
    assert SECRET not in caplog.text
    assert SECRET not in json.dumps(decisions(caplog))
