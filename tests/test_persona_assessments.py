import copy
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from uuid import uuid4

import pytest
from psycopg2.errors import LockNotAvailable
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from services.db import get_connection
from services.graphs.runtime import dispatch
from services.meetings import digestion_db, profile_db, profile_fields, management_db, memory_db
from services.meetings.types import TranscriptSegment
from services.personas import assessment, assessment_db, revisions
from tests.test_meeting_memory_agent import backend as backend, call, model as model
from tests.test_meeting_profiles_db import candidate, claimed as claimed, participants as participants
from tests.test_meeting_sync import note, source as source
from tests.test_meeting_transcript_capture import enroll


@pytest.fixture
def observed(claimed, participants):
    participants[0]["segment_ids"].append("segment-1")
    artifact = candidate(participants)
    second = copy.deepcopy(artifact["items"][0])
    second.update(category="driver", content="Protects reliability before making decisions", target_id=None)
    second["evidence"] = [{"segment_id": "segment-1", "quote": "I value direct communication"}]
    artifact["items"].append(second)
    profile_db.apply_profiles(*claimed, artifact, participants)
    return profile_db.get_profile(participants[0]["id"])


def output(snapshot, **changes):
    result = assessment_db.insufficient(snapshot["profile"])
    ids = [claim["id"] for claim in snapshot["claims"]]
    result["overview"] = {"status": "supported", "text": "Prioritizes reliable collaboration.", "claim_ids": ids[:1]}
    result["drivers"] = {"status": "supported", "text": "Reliability guides decisions; evidence remains limited.", "claim_ids": ids[:2]}
    result.update(changes)
    return result


@pytest.fixture
def roster_observed(source, participants):
    from services.meetings.participants import email_participant

    for index, person in enumerate(participants):
        participants[index] = email_participant(person["email"], person["display_name"])
    texts = ("I work at Example Co and prioritize reliability.", "I value written decisions before approval.",
             "I work at Other Co and value direct communication.")
    participants[0]["segment_ids"] = ["segment-0", "segment-1"]
    participants[1]["segment_ids"] = ["segment-2"]
    summary = replace(note("roster"), metadata={"attendees": [
        {"name": person["display_name"], "email": person["email"]} for person in participants]})
    meeting_id = enroll(source, summary)
    record = digestion_db.claim_transcript([(source.provider, source.account_key)], "roster-capture")
    segments = [TranscriptSegment(text, {"name": participants[0 if index < 2 else 1]["display_name"],
                                        "email": participants[0 if index < 2 else 1]["email"]}).to_dict(index)
                for index, text in enumerate(texts)]
    digestion_db.save_capture(meeting_id, "roster-capture", digestion_db.get_context(meeting_id), {"segments": segments}, complete=True)
    record = digestion_db.get_record(meeting_id)
    memory_db.save_progress(meeting_id, "roster-capture", record["transcript_hash"], {"items": [], "reason": "No new memory"}, complete=True)
    # This fixture starts from historical evidence to verify assessment rebasing.
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_digestions SET speaker_status='legacy' WHERE meeting_id=%s", (meeting_id,))
    digestion_db.release(meeting_id, "roster-capture")
    assert digestion_db.claim_profile(source.name, "roster-profiles")["meeting_id"] == meeting_id
    artifact = candidate(participants)
    artifact["items"] = [{**artifact["items"][0], "subject_id": participants[0 if index < 2 else 1]["id"],
                          "target_id": None, "content": text, "evidence": [{"segment_id": f"segment-{index}", "quote": text}]}
                         for index, text in enumerate(texts)]
    artifact["metadata_updates"] = [{"subject_id": person["id"], "fields": {"company": company},
                                      "evidence": [{"segment_id": f"segment-{index}", "quote": texts[index]}]}
                                     for person, company, index in ((participants[0], "Example Co", 0), (participants[1], "Other Co", 2))]
    profile_db.apply_profiles(meeting_id, "roster-profiles", record["transcript_hash"], artifact, participants)
    digestion_db.release_profile_owner("roster-profiles")
    result = []
    for index, person in enumerate(participants):
        snapshot = assessment_db.claim("roster-assessment", person["id"])
        candidates = output(snapshot) if index == 0 else assessment_db.insufficient(snapshot["profile"])
        if index == 1:
            candidates["overview"] = {"status": "supported", "text": "Values direct communication at Other Co.",
                                      "claim_ids": [snapshot["claims"][0]["id"]]}
        result.append(assessment_db.apply("roster-assessment", snapshot, candidates))
    return meeting_id, result


def test_persona_assessment_saved_evidence_apply_history_and_unchanged_skip(observed):
    snapshot = assessment_db.claim("test-assessment", observed["id"])
    assert len(snapshot["claims"]) == 2
    updated = assessment_db.apply("test-assessment", snapshot, output(snapshot))
    assert updated["revision"] == observed["revision"] + 1
    assert updated["section_notes"]["drivers"].startswith("Reliability")
    assert updated["assessment"] == {**updated["assessment"], "status": "current", "coverage": {"claim_count": 2, "meeting_count": 1}}
    assert updated["section_evidence"]["drivers"]["coverage"] == {"claim_count": 2, "meeting_count": 1}
    history = revisions.list_history(observed["id"])
    assert history["total"] == 2
    assert history["items"][0]["source"] == "assessment" and history["items"][0]["actor"] == "agent"
    assert history["items"][0]["changes"]["section_notes"]["after"]["drivers"] == updated["section_notes"]["drivers"]
    assessment_db.request(observed["id"], updated["revision"])
    assert assessment_db.claim("unchanged", observed["id"]) == {"skipped": True, "id": observed["id"]}
    assert revisions.list_history(observed["id"])["total"] == 2


@pytest.mark.parametrize("change", ["withdrawn", "hash", "attribution", "deleted_transcript", "corrected", "rejected"])
def test_persona_assessment_and_history_hide_invalid_evidence_then_become_due(observed, claimed, change):
    snapshot = assessment_db.claim("test-assessment", observed["id"])
    assessment_db.apply("test-assessment", snapshot, output(snapshot))
    if change in {"corrected", "rejected"}:
        profile_db.correct_claim(observed["id"], observed["claims"][0]["id"], 2,
                                 "correct" if change == "corrected" else "reject", "Human clarification", "Review")
    else:
        with get_connection() as conn, conn.cursor() as cur:
            if change == "withdrawn":
                cur.execute("UPDATE meeting_summaries SET available=false WHERE id=%s", (claimed[0],))
            elif change == "hash":
                cur.execute("UPDATE meeting_digestions SET transcript_hash=%s WHERE meeting_id=%s", ("f" * 64, claimed[0]))
            elif change == "attribution":
                cur.execute("UPDATE meeting_summaries SET participants_revision=participants_revision+1 WHERE id=%s", (claimed[0],))
            else:
                cur.execute("UPDATE meeting_digestions SET transcript_status='deleted' WHERE meeting_id=%s", (claimed[0],))
    profile = profile_db.get_profile(observed["id"])
    assert "drivers" not in profile["section_notes"]
    audit = revisions.list_history(observed["id"])
    assert all("drivers" not in item["changes"].get("section_notes", {}).get("after", {}) for item in audit["items"])
    assert any(item["source_restricted"] for item in audit["items"])
    assert assessment_db.has_requested_work(observed["id"])


def test_persona_assessment_human_edits_clears_release_and_cosmetic_changes(observed):
    profile = profile_db.update_metadata(observed["id"], 1, section_notes={"overview": "My context", "drivers": ""})
    snapshot = assessment_db.claim("protected", profile["id"])
    assert "drivers" not in assessment_db.insufficient(snapshot["profile"])
    result = assessment_db.insufficient(snapshot["profile"])
    current = assessment_db.apply("protected", snapshot, result)
    assert current["section_notes"] == {"overview": "My context"}
    assert current["section_evidence"]["drivers"] == {"human": True, "origin": "human"}
    cosmetic = profile_db.update_metadata(current["id"], current["revision"], tags=["favorite"], starred=True)
    assert cosmetic["assessment"]["status"] == "current"
    assert not assessment_db.has_requested_work(current["id"])
    unlocked = profile_db.update_metadata(current["id"], cosmetic["revision"], allow_agent_sections=["drivers"])
    assert not unlocked["section_evidence"]["drivers"]["human"]
    assert assessment_db.has_requested_work(current["id"])
    assert revisions.list_history(current["id"])["items"][0]["actor"] == "human"


def test_persona_assessment_concurrent_human_edit_preserved_and_lease_bounded(observed):
    snapshot = assessment_db.claim("first", observed["id"])
    assert assessment_db.claim("second", observed["id"]) is None
    edited = profile_db.update_metadata(observed["id"], observed["revision"], section_notes={"drivers": "Human assessment"})
    with pytest.raises(profile_db.ProfileRevisionConflict, match="changed"):
        assessment_db.apply("first", snapshot, output(snapshot))
    assessment_db.fail(observed["id"], "first", "ProfileRevisionConflict")
    assert profile_db.get_profile(observed["id"])["section_notes"]["drivers"] == "Human assessment"
    assert not assessment_db.has_requested_work(observed["id"])
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE participant_profiles SET assessment_next_attempt_at=now()-interval '1 second' WHERE id=%s", (observed["id"],))
    retried = assessment_db.claim("second", observed["id"])
    assert retried["profile"]["revision"] == edited["revision"]
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE participant_profiles SET assessment_claim_until=now()-interval '1 second' WHERE id=%s", (observed["id"],))
    with pytest.raises(profile_db.ProfileRevisionConflict, match="lease"):
        assessment_db.apply("second", retried, assessment_db.insufficient(retried["profile"]))
    assessment_db.release_owner("second")


def test_persona_assessment_repeated_or_overlapping_utterances_are_not_independent(observed):
    snapshot = assessment_db.claim("independence", observed["id"])
    claims = copy.deepcopy(snapshot["claims"])
    claims[1]["evidence"] = [{"segment_id": claims[0]["evidence"][0]["segment_id"], "quote": "different portion"}]
    with pytest.raises(ValueError, match="independent"):
        assessment.validate_output(snapshot["profile"], claims, output(snapshot))
    claims[1]["evidence"].append(snapshot["claims"][1]["evidence"][0])
    with pytest.raises(ValueError, match="independent"):
        assessment.validate_output(snapshot["profile"], claims, output(snapshot))
    assessment_db.release_owner("independence")


@pytest.mark.asyncio
@pytest.mark.parametrize("protected", [False, True])
async def test_persona_assessment_no_evidence_or_all_human_never_calls_model(observed, protected, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No paid assessment is useful for this profile")

    profile = observed
    if protected:
        profile = profile_db.update_metadata(profile["id"], profile["revision"], section_notes={key: "Human context" for key in profile_fields.SECTION_FIELDS})
    else:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("UPDATE meeting_summaries SET available=false WHERE id=%s", (observed["claims"][0]["meeting_id"],))
    monkeypatch.setattr(assessment, "synthesize", forbidden)
    report = json.loads(await dispatch("persona", {"profile_id": profile["id"]}))
    assert report["assessments"]["outcome"] == "done"
    assert not assessment_db.has_requested_work(profile["id"])


def test_persona_assessment_released_human_section_signature_stable_after_apply(observed):
    profile = profile_db.update_metadata(observed["id"], observed["revision"], section_notes={"drivers": "Human draft"})
    profile = profile_db.update_metadata(profile["id"], profile["revision"], allow_agent_sections=["drivers"])
    snapshot = assessment_db.claim("release-hash", profile["id"])
    profile = assessment_db.apply("release-hash", snapshot, output(snapshot))
    assessment_db.request(profile["id"], profile["revision"])
    assert assessment_db.claim("released-unchanged", profile["id"])["skipped"]


def test_persona_assessment_api_history_unlock_and_manual_job_override(observed, monkeypatch):
    from fastapi.testclient import TestClient
    from services.api.app import app
    from services.jobs import scheduler, scoping
    from services.jobs.models import job as job_db

    client = TestClient(app)
    key = observed["id"]
    protected = client.patch(f"/api/profiles/{key}", json={"expected_revision": 1, "section_notes": {"working_style": "Human style"}})
    assert protected.status_code == 200
    unlocked = client.patch(f"/api/profiles/{key}", json={"expected_revision": 2, "allow_agent_sections": ["working_style"]})
    assert unlocked.status_code == 200 and unlocked.json()["section_evidence"]["working_style"]["human"] is False
    assert client.patch(f"/api/profiles/{key}", json={"expected_revision": 2, "allow_agent_sections": ["working_style"]}).status_code == 409
    page = client.get(f"/api/profiles/{key}/history", params={"limit": 1}).json()
    assert page["total"] == 3 and page["items"][0]["actor"] == "human"
    assert client.get(f"/api/profiles/{key}/history/{page['items'][0]['id']}").json() == page["items"][0]
    assert client.get(f"/api/profiles/{uuid4()}/history/{page['items'][0]['id']}").status_code == 404
    configured = {"id": 41, "input_params": {"graph_type": "persona", "graph_inputs": {"source": "work"}, "timeout": 600}}
    seen = []
    async def execute(job):
        seen.append(copy.deepcopy(job))
        return {"success": True, "execution_id": 99}
    monkeypatch.setattr(job_db, "list_graph_jobs", lambda graph_type: [configured])
    monkeypatch.setattr(scoping, "job_runs_on_device", lambda job_id, device: True)
    monkeypatch.setattr(scheduler, "execute_job", execute)
    response = client.post(f"/api/profiles/{key}/rebuild", json={"expected_revision": 3})
    assert response.status_code == 200 and response.json() == {"success": True, "execution_id": 99, "job_id": 41, "profile_id": key}
    assert seen[0]["input_params"]["graph_inputs"] == {"profile_id": key}
    assert configured["input_params"]["graph_inputs"] == {"source": "work"}
    assert client.post(f"/api/profiles/{key}/rebuild", json={"expected_revision": 1}).status_code == 409
    assert len(seen) == 1
    monkeypatch.setattr(job_db, "list_graph_jobs", lambda graph_type: [])
    assert client.post(f"/api/profiles/{key}/rebuild", json={"expected_revision": 3}).status_code == 409


@pytest.mark.asyncio
async def test_persona_assessment_failure_backoff_and_retry_bound_preserve_extraction(observed, monkeypatch):
    from services.graphs.library.persona import PersonaProcessingError

    async def fail(*args, **kwargs):
        raise assessment.AssessmentError("Private source details", error_type="SyntheticAssessmentFailure")
    monkeypatch.setattr(assessment, "synthesize", fail)
    with pytest.raises(PersonaProcessingError) as caught:
        await dispatch("persona", {"profile_id": observed["id"]})
    assert "Private" not in str(caught.value) and "SyntheticAssessmentFailure" in str(caught.value)
    state = profile_db.get_profile(observed["id"])["assessment"]
    assert state["attempts"] == 1 and state["status"] == "failed"
    assert not assessment_db.has_requested_work(observed["id"])
    record = digestion_db.get_record(observed["claims"][0]["meeting_id"])
    assert record["profile_status"] == "done" and record["profile_artifact"]["offset"] == 2
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE participant_profiles SET assessment_attempts=%s, assessment_next_attempt_at=now()-interval '1 hour' WHERE id=%s",
                    (assessment_db.MAX_ATTEMPTS, observed["id"]))
    assert not assessment_db.has_requested_work(observed["id"])
    assert assessment_db.claim("exhausted", observed["id"]) is None
    assessment_db.request(observed["id"], observed["revision"])
    assert assessment_db.has_requested_work(observed["id"])


@pytest.mark.asyncio
async def test_persona_assessment_cancellation_releases_lease_without_resetting_evidence(observed, monkeypatch):
    entered = asyncio.Event()
    async def waiting(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(assessment, "synthesize", waiting)
    task = asyncio.create_task(dispatch("persona", {"profile_id": observed["id"]}))
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    profile = profile_db.get_profile(observed["id"])
    assert profile["assessment_claim_owner"] is None and profile["assessment_claim_until"] is None
    assert profile["assessment"]["attempts"] == 0
    assert digestion_db.get_record(observed["claims"][0]["meeting_id"])["profile_status"] == "done"
    assert assessment_db.has_requested_work(observed["id"])


@pytest.mark.asyncio
async def test_persona_assessment_scheduled_graph_automatically_uses_saved_claims(observed, monkeypatch):
    from services.personas.factory import MeetingContextProvider

    calls = []
    async def synthesize(row, claims, **kwargs):
        calls.append(row["id"])
        return {"sections": output({"profile": row, "claims": claims}), "relationships": assessment_db.relationship_insufficient(row)}
    monkeypatch.setattr(MeetingContextProvider, "claim", lambda self, owner, **kwargs: None)
    monkeypatch.setattr(assessment, "synthesize", synthesize)
    for _ in range(3):
        report = json.loads(await dispatch("persona", {}))
        assert report["profiles"]["outcome"] == "idle"
        if observed["id"] in calls:
            break
    assert calls == [observed["id"]]
    assert profile_db.get_profile(observed["id"])["section_notes"]["drivers"].startswith("Reliability")


def test_persona_assessment_publication_locks_live_sources_through_receipt_commit(observed, monkeypatch):
    snapshot = assessment_db.claim("source-lock", observed["id"])
    locked = threading.Event()
    resume = threading.Event()
    original = assessment_db._snapshot
    def paused(cur, row):
        locked.set()
        assert resume.wait(5)
        return original(cur, row)
    monkeypatch.setattr(assessment_db, "_snapshot", paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        applying = pool.submit(assessment_db.apply, "source-lock", snapshot, output(snapshot))
        assert locked.wait(5)
        try:
            with pytest.raises(LockNotAvailable):
                with get_connection() as conn, conn.cursor() as cur:
                    cur.execute("SET LOCAL lock_timeout = '100ms'")
                    cur.execute("UPDATE meeting_summaries SET available=false WHERE id=%s", (observed["claims"][0]["meeting_id"],))
        finally:
            resume.set()
        assert applying.result(timeout=5)["section_notes"]["drivers"].startswith("Reliability")


@pytest.mark.parametrize("remap", [False, True])
def test_persona_assessment_roster_edits_preserve_unaffected_profiles_without_paid_refresh(roster_observed, remap):
    meeting_id, profiles = roster_observed
    before = digestion_db.get_record(meeting_id)
    speakers = management_db.get_participants(meeting_id)["speakers"]
    roster = [{"name": profile["display_name"], "email": profile["email"]} for profile in profiles]
    roster.append({"name": "Silent attendee", "email": "silent@example.invalid"})
    if remap:
        alex = next(speaker for speaker in speakers if speaker["label"] == profiles[0]["display_name"])
        roster[0] = {"name": "Actual speaker", "email": "actual@example.invalid", "speaker_key": alex["key"]}
    management_db.update_participants(meeting_id, 0, roster)
    for index, previous in enumerate(profiles):
        current = profile_db.get_profile(previous["id"])
        if remap and index == 0:
            assert current["claims"] == [] and current["metadata"] == {} and current["section_notes"] == {}
            assert assessment_db.has_requested_work(previous["id"])
        else:
            assert [claim["id"] for claim in current["claims"]] == [claim["id"] for claim in previous["claims"]]
            assert current["metadata"] == previous["metadata"] and current["section_notes"] == previous["section_notes"]
            assert all(claim["participants_revision"] == 1 for claim in current["claims"])
            assert current["metadata_provenance"]["company"]["participants_revision"] == 1
            assert not assessment_db.has_requested_work(current["id"])
            assessment_db.request(current["id"], current["revision"])
            assert assessment_db.claim("roster-unchanged", current["id"])["skipped"]
    after = digestion_db.get_record(meeting_id)
    assert after["profile_artifact"] == before["profile_artifact"] and after["profile_status"] == "done"
    assert after["memory_artifact"] == before["memory_artifact"] and after["memory_status"] == "done"


@pytest.mark.asyncio
async def test_persona_assessment_real_react_saved_claims_and_memory_research(observed, backend, model):
    snapshot = assessment_db.claim("react", observed["id"])
    candidates = output(snapshot)
    instance, roles = model([
        call("get_observations", offset=0, limit=20),
        call("search_previous_memories", query="reliability"),
        call("stage_assessment", sections=candidates, relationships=assessment_db.relationship_insufficient(snapshot["profile"]), reason="Saved evidence"),
        AIMessage(content="Final prose is not saved"),
    ])
    result = await assessment.synthesize(snapshot["profile"], snapshot["claims"])
    assert result == {"sections": candidates, "relationships": assessment_db.relationship_insufficient(snapshot["profile"]), "reason": "Saved evidence"}
    assert roles == [("persona", "curator")]
    assert instance.tool_names == ["search_previous_memories", "get_memory", "get_observations", "stage_assessment"]
    data = next(message.content for message in instance.seen[0] if isinstance(message, HumanMessage))
    assert "effective_content" in data and "observations" in data
    assert "transcript_window" not in data and backend[2] == []
    assessment_db.release_owner("react")


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["one_claim", "unknown_claim", "invalid_schema"])
async def test_persona_assessment_invalid_stage_clears_accepted_result(observed, model, invalid):
    snapshot = assessment_db.claim("invalid", observed["id"])
    valid = output(snapshot)
    broken = copy.deepcopy(valid)
    if invalid == "one_claim":
        broken["drivers"]["claim_ids"] = broken["drivers"]["claim_ids"][:1]
    elif invalid == "unknown_claim":
        broken["drivers"]["claim_ids"] = [str(uuid4()), str(uuid4())]
    else:
        broken["drivers"]["status"] = "invented"
    instance, _ = model([call("stage_assessment", sections=valid, relationships=assessment_db.relationship_insufficient(snapshot["profile"])), call("stage_assessment", sections=broken, relationships=assessment_db.relationship_insufficient(snapshot["profile"])), AIMessage(content="Done")])
    with pytest.raises(assessment.AssessmentError, match="without a valid"):
        await assessment.synthesize(snapshot["profile"], snapshot["claims"])
    assert any(isinstance(message, ToolMessage) and ("error" in message.content or "Invalid assessment schema" in message.content)
               for message in instance.seen[-1])
    assessment_db.release_owner("invalid")


@pytest.mark.asyncio
async def test_persona_assessment_graph_profile_mode_skips_transcript_and_duplicates(observed, monkeypatch):
    from services.personas.factory import MeetingContextProvider

    def forbidden(*args, **kwargs):
        raise AssertionError("Saved-observation rebuild must not claim or reprocess transcripts")

    calls = []
    async def synthesize(row, claims, **kwargs):
        calls.append(row["id"])
        return {"sections": output({"profile": row, "claims": claims}), "relationships": assessment_db.relationship_insufficient(row)}
    monkeypatch.setattr(MeetingContextProvider, "claim", forbidden)
    monkeypatch.setattr(assessment, "synthesize", synthesize)
    report = json.loads(await dispatch("persona", {"profile_id": observed["id"]}))
    assert report["profiles"]["outcome"] == "idle"
    assert report["assessments"]["outcome"] == "done" and calls == [observed["id"]]
    assert digestion_db.get_record(observed["claims"][0]["meeting_id"])["profile_status"] == "done"
    assessment_db.request(observed["id"], profile_db.get_profile(observed["id"])["revision"])
    assert json.loads(await dispatch("persona", {"profile_id": observed["id"]}))["assessments"]["unchanged"]
    assert calls == [observed["id"]]
