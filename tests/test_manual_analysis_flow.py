from __future__ import annotations

import copy

import pytest
from psycopg2.extras import Json

from services.db import get_connection
from services.meetings import digestion_db, manual_analysis, profile_analysis, profile_db
from services.personas.service import PersonaRun
from tests.test_manual_analysis import jobs as jobs, payload as payload, saved as saved, source as source, target as target


def raw_profile(profile_id):
    from psycopg2.extras import RealDictCursor

    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM participant_profiles WHERE id=%s", (profile_id,))
        return dict(cur.fetchone())


async def profile_pass(source):
    async with PersonaRun(source.name) as run:
        await run.prepare()
        await run.build_profiles()
        return run.profile_report


@pytest.fixture
def extraction(monkeypatch, target):
    calls = []

    async def analyze(snapshot, window, previous, **kwargs):
        calls.append(copy.deepcopy((snapshot, window, previous, kwargs)))
        subject = target["id"]
        own = next(segment for segment in window if segment["id"] == "segment-0")
        return {"items": [{"subject_id": subject, "category": "driver", "epistemic": "self_report",
            "confidence": "high", "content": "Values reliability", "rationale": "",
            "evidence": [{"segment_id": own["id"], "quote": own["text"]}]}],
            "metadata_updates": [{"subject_id": subject, "fields": {"company": "Synthetic company"},
                "evidence": [{"segment_id": own["id"], "quote": own["text"]}]}], "reason": ""}

    monkeypatch.setattr(profile_analysis, "analyze_profiles", analyze)
    return calls


@pytest.mark.asyncio
async def test_manual_analysis_zero_claim_target_reaches_agent_once_and_stays_done(source, target, saved, payload, jobs, extraction):
    meeting_id = saved(person=target)
    unrelated = saved()
    jobs()
    before, other = digestion_db.get_record(meeting_id), digestion_db.get_record(unrelated)
    assert (await profile_pass(source))["outcome"] == "idle"
    body = payload(meeting_id, person=target)
    receipt = manual_analysis.request_analysis(body)
    report = await profile_pass(source)
    assert report["outcome"] == "done" and report["profile_ids"] == [target["id"]]
    assert len(extraction) == 1
    snapshot, window, _, context = extraction[0]
    assert snapshot["analysis_target_profile_id"] == target["id"]
    assert any(person["id"] == target["id"] and "segment-0" in person["segment_ids"] for person in context["participants"])
    assert window[0]["text"] == "I prioritize reliability"
    profile = profile_db.get_profile(target["id"])
    assert len(profile["claims"]) == 1 and profile["metadata"]["company"] == "Synthetic company"
    after = digestion_db.get_record(meeting_id)
    assert after["profile_status"] == "done" and not after["manual_analysis"]["profile"]["active"]
    assert after["memory_artifact"] == before["memory_artifact"] and after["memory_updated_at"] == before["memory_updated_at"]
    assert digestion_db.get_record(unrelated) == other
    assert manual_analysis.get_request(receipt["request_id"])["status"] == "done"
    completed = copy.deepcopy(after)
    assert manual_analysis.request_analysis(body)["status"] == "done"
    for _ in range(3):
        assert (await profile_pass(source))["outcome"] == "idle"
    assert len(extraction) == 1 and digestion_db.get_record(meeting_id) == completed
    fresh = payload(meeting_id, person=profile)
    manual_analysis.request_analysis(fresh)
    await profile_pass(source)
    assert len(extraction) == 2 and len(profile_db.get_profile(target["id"])["claims"]) == 1


@pytest.mark.asyncio
async def test_manual_analysis_source_change_fails_before_agent_and_consumes_target(source, target, saved, payload, jobs, extraction):
    meeting_id = saved(person=target)
    jobs()
    receipt = manual_analysis.request_analysis(payload(meeting_id, person=target))
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_summaries SET revision=revision+1 WHERE id=%s", (meeting_id,))
    report = await profile_pass(source)
    assert report["outcome"] == "failed" and report["error_type"] == "ManualAnalysisInputChanged"
    assert extraction == [] and profile_db.get_profile(target["id"])["claims"] == []
    after = digestion_db.get_record(meeting_id)
    assert after["profile_status"] == "failed" and after["profile_attempts"] == 3
    assert after["manual_analysis"]["profile"] == {"request_id": receipt["request_id"], "active": False}
    assert manual_analysis.get_request(receipt["request_id"])["status"] == "failed"


@pytest.mark.asyncio
async def test_manual_analysis_filters_other_subjects_before_checkpoint_and_publication(source, target, saved, payload, jobs, monkeypatch):
    meeting_id = saved(person=target)
    other = profile_db.create_profile("Another manual participant")
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("UPDATE meeting_summaries SET manual_participants=manual_participants || %s::jsonb WHERE id=%s",
                (Json([{"profile_id": other["id"], "name": other["display_name"], "segment_id": "segment-1"}]), meeting_id))
        before = raw_profile(other["id"])
        jobs()
        manual_analysis.request_analysis(payload(meeting_id, person=target))
        async def analyze(snapshot, window, previous, **kwargs):
            return {"items": [{"subject_id": other["id"], "category": "driver", "epistemic": "self_report",
                "confidence": "high", "content": "Must not publish", "rationale": "",
                "evidence": [{"segment_id": "segment-1", "quote": "I value direct communication"}]}],
                "metadata_updates": [{"subject_id": other["id"], "fields": {"company": "Must not publish"},
                    "evidence": [{"segment_id": "segment-1", "quote": "I value direct communication"}]}], "reason": "Only another subject was returned"}
        monkeypatch.setattr(profile_analysis, "analyze_profiles", analyze)
        assert (await profile_pass(source))["outcome"] == "done"
        assert raw_profile(other["id"]) == before
        artifact = digestion_db.get_record(meeting_id)["profile_artifact"]
        assert artifact["items"] == artifact["metadata_updates"] == []
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM participant_profiles WHERE id=%s", (other["id"],))


@pytest.mark.asyncio
async def test_manual_analysis_terminal_failure_resume_restores_same_target_and_checkpoints(source, target, saved, payload, jobs, extraction, monkeypatch):
    from services.meetings import manual_stage

    meeting_id = saved(person=target)
    jobs()
    receipt = manual_analysis.request_analysis(payload(meeting_id, person=target))
    original = profile_analysis.analyze_profiles
    async def fail(*args, **kwargs):
        raise RuntimeError("Synthetic failure")
    monkeypatch.setattr(profile_analysis, "analyze_profiles", fail)
    for attempt in range(3):
        report = await profile_pass(source)
        assert report["outcome"] == "failed"
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("UPDATE meeting_digestions SET profile_next_attempt_at=clock_timestamp() WHERE meeting_id=%s", (meeting_id,))
    failed = digestion_db.get_record(meeting_id)
    assert failed["profile_status"] == "failed" and not failed["manual_analysis"]["profile"]["active"]
    artifact = copy.deepcopy(failed["profile_artifact"])
    manual_stage.resume_request(receipt["request_id"])
    resumed = digestion_db.get_record(meeting_id)
    assert resumed["profile_artifact"] == artifact and resumed["manual_analysis"]["profile"]["target"]["id"] == target["id"]
    monkeypatch.setattr(profile_analysis, "analyze_profiles", original)
    assert (await profile_pass(source))["outcome"] == "done"
    assert len(extraction) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_extraction", [False, True])
async def test_manual_analysis_full_profile_run_assesses_only_selected_target(source, target, saved, payload, jobs, extraction, monkeypatch, fail_extraction):
    from services.personas import assessment, assessment_db

    meeting_id = saved(person=target)
    other = profile_db.create_profile("Unrelated dirty assessment")
    before = raw_profile(other["id"])
    jobs()
    manual_analysis.request_analysis(payload(meeting_id, person=target))
    claimed, synthesized = [], []
    original_claim = assessment_db.claim
    def claim(owner, profile_id=None):
        claimed.append(profile_id)
        return original_claim(owner, profile_id)
    async def synthesize(row, claims, *, deadline):
        synthesized.append(row["id"])
        return {"sections": assessment_db.insufficient(row), "relationships": assessment_db.relationship_insufficient(row)}
    async def fail(*args, **kwargs):
        raise RuntimeError("Synthetic extraction failure")
    monkeypatch.setattr(assessment_db, "claim", claim)
    monkeypatch.setattr(assessment, "synthesize", synthesize)
    if fail_extraction:
        monkeypatch.setattr(profile_analysis, "analyze_profiles", fail)
    try:
        async with PersonaRun(source.name) as run:
            await run.prepare()
            await run.build_profiles()
            await run.build_assessments()
        assert claimed == ([] if fail_extraction else [target["id"]])
        assert synthesized == ([] if fail_extraction else [target["id"]])
        assert raw_profile(other["id"]) == before
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM participant_profiles WHERE id=%s", (other["id"],))


@pytest.mark.asyncio
async def test_manual_analysis_assignment_change_keeps_scope_closed_until_fresh_confirmation(source, target, saved, payload, jobs, extraction):
    from services.meetings import management_db, manual_candidates

    meeting_id = saved(person=target)
    jobs()
    first = manual_analysis.request_analysis(payload(meeting_id, person=target))
    row = digestion_db.get_record(meeting_id)
    checkpoint = copy.deepcopy(row["profile_artifact"])
    participants = management_db.get_participants(meeting_id)
    management_db.update_participants(meeting_id, participants["revision"],
        participants["items"] + [{"name": "New silent attendee"}], row["transcript_hash"])
    invalid = digestion_db.get_record(meeting_id)
    assert invalid["profile_status"] == "failed" and invalid["profile_error"] == "ManualAnalysisInputChanged"
    assert invalid["profile_artifact"] == checkpoint
    assert not invalid["manual_analysis"]["profile"]["active"]
    assert digestion_db.claim_profile(source.name, "must-not-broaden") is None
    assert manual_analysis.get_request(first["request_id"])["status"] == "failed"
    with pytest.raises(manual_analysis.AnalysisConflict):
        management_db.request_processing(meeting_id)
    assert digestion_db.get_record(meeting_id)["profile_status"] == "failed"
    candidate = manual_candidates.list_candidates(profile_id=target["id"], meeting_id=meeting_id)["items"][0]
    assert candidate["stages"]["profile"]["can_reanalyze"]
    current = profile_db.get_profile(target["id"])
    manual_analysis.request_analysis(payload(meeting_id, person=current))
    assert (await profile_pass(source))["outcome"] == "done" and len(extraction) == 1


@pytest.mark.asyncio
async def test_manual_analysis_force_graph_inputs_cannot_reopen_completed_profiles(source, target, saved, monkeypatch):
    from services.graphs.runtime import dispatch
    from services.personas import assessment

    meeting_id = saved(person=target)
    before = digestion_db.get_record(meeting_id)
    async def forbidden(*args, **kwargs):
        raise AssertionError("Completed saved analysis must not call an agent")
    monkeypatch.setattr(profile_analysis, "analyze_profiles", forbidden)
    monkeypatch.setattr(assessment, "synthesize", forbidden)
    await dispatch("persona", {"source": source.name, "force": True, "rerun": True})
    assert digestion_db.get_record(meeting_id) == before
