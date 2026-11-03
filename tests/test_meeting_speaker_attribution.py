import asyncio
import copy
import json
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from psycopg2.extras import Json

from services.api.routers.meetings import router
from services.db import get_connection
from services.graphs.runtime import dispatch
from services.meetings import digestion_db, management_db, memory_db, speaker_analysis, speaker_db
from services.meetings.participants import meeting_participants, speaker_key
from services.meetings.speaker_analysis import identify_statements as real_identify
from services.meetings.types import TranscriptSegment
from tests.test_manual_analysis import saved as saved
from tests.test_meeting_memory_agent import call, model as model
from tests.test_meeting_memory_flow import agents as agents, feed as feed, ready as ready
from tests.test_meeting_sync import source as source


def assignment(segment, name, **fields):
    return {"segment_id": segment["id"], "name": name, "confidence": "high", "rationale": "Explicit introduction",
            "evidence": [{"segment_id": segment["id"], "quote": segment["text"]}], **fields}


def statements():
    return [TranscriptSegment(text, {"source": "speaker", "attribution": "them"}).to_dict(index)
            for index, text in enumerate(("I'm Alex.", "My name is Blair.", "Yes, that works."))]


def legacy_memory_artifact():
    return {"version": 1, "offset": 0, "items": [], "published_ids": [],
            "created_at": "2026-01-01T00:00:00+00:00", "reason": "", "input_source": "transcript"}


@pytest.mark.asyncio
async def test_scripted_small_agent_assigns_shared_channel_statements_and_leaves_ambiguity_unknown(model):
    segments = statements()
    instance, roles = model([call("stage_speakers", assignments=[assignment(segments[0], "Alex"), assignment(segments[1], "Blair")],
                                  reason="The last speaker is uncertain"), AIMessage(content="Done")])
    result = await real_identify({"id": str(uuid4())}, segments, context=[], anchors=[], deadline=asyncio.get_running_loop().time() + 20)
    people = meeting_participants({"id": str(uuid4()), "statement_attributions": result["assignments"]}, segments)
    assert roles == [("meeting_speaker", "curator")]
    assert instance.tool_names == ["search_known_profiles", "stage_speakers"]
    assert [(person["display_name"], person["segment_ids"]) for person in people] == [("Alex", ["segment-0"]), ("Blair", ["segment-1"])]
    assert all(person["identity_scope"] == "meeting" for person in people)


@pytest.mark.parametrize("case", ["readonly", "duplicate", "invented_email", "invented_profile", "new_name_without_intro", "bad_quote"])
def test_statement_boundary_denies_unproved_identity_and_readonly_ids(case):
    segments = statements()
    item = assignment(segments[0], "Alex")
    targets, context, items = segments[:1], segments[1:], [item]
    if case == "readonly":
        items = [assignment(segments[1], "Blair")]
    elif case == "duplicate":
        items.append(copy.deepcopy(item))
    elif case == "invented_email":
        item["email"] = "invented@example.test"
    elif case == "invented_profile":
        item["profile_id"] = str(uuid4())
    elif case == "new_name_without_intro":
        item["name"] = "Someone else"
    else:
        item["evidence"][0]["quote"] = "Not in the transcript"
    with pytest.raises(ValueError):
        speaker_analysis.validate_assignments(items, targets, context, [], [])


def test_manual_statement_beats_channel_provider_and_auto_without_mutating_raw():
    segments = statements()
    original = copy.deepcopy(segments)
    snapshot = {"id": str(uuid4()), "statement_attributions": [assignment(segment, name) for segment, name in zip(segments, ("Auto A", "Auto B", "Auto C"))],
                "manual_participants": [{"name": "Channel", "speaker_key": speaker_key(segments[0]["speaker"])},
                                        {"name": "Statement", "segment_id": "segment-1"}]}
    people = meeting_participants(snapshot, segments)
    assert [(person["display_name"], person["segment_ids"]) for person in people] == [("Channel", ["segment-0", "segment-2"]), ("Statement", ["segment-1"])]
    assert segments == original


@pytest.mark.asyncio
async def test_graph_uses_no_speaker_model_and_persona_keeps_saved_attribution(source, feed, agents, monkeypatch, extraction_only):
    from services.meetings import profile_analysis

    feed.segments = tuple(TranscriptSegment(segment["text"], segment["speaker"]) for segment in statements()[:2]) + (
        TranscriptSegment("Provider statement", {"name": "Provider person"}),)
    await dispatch("meeting_ingest", {"source": source.name, "digest": False})
    meeting_id = digestion_db.claim_digestion([(source.provider, source.account_key)], "setup")["meeting_id"]
    digestion_db.release(meeting_id, "setup")
    before = digestion_db.get_record(meeting_id)
    management_db.update_participants(meeting_id, 0, [{"name": "Manual person", "segment_id": "segment-0"}], before["transcript_hash"])
    historical = {"assignments": [assignment(before["transcript"]["segments"][1], "Saved person")],
                  "committed_transcript_hash": before["transcript_hash"]}
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_digestions SET speaker_artifact=%s WHERE meeting_id=%s", (Json(historical), meeting_id))

    def forbidden(*args, **kwargs):
        pytest.fail("The production graph must never invoke participant inference")

    monkeypatch.setattr(speaker_analysis, "identify_statements", forbidden)
    result = json.loads(await dispatch("meeting_ingest", {"source": source.name}))
    assert result["memories"]["outcome"] == "done" and "participants" not in result
    assert digestion_db.get_record(meeting_id)["speaker_status"] == "pending"
    assert digestion_db.get_record(meeting_id)["speaker_artifact"] == historical
    catalog = []

    async def analyze(snapshot, window, previous, *, participants, **kwargs):
        catalog.extend(participants)
        return {"items": [], "reason": "No durable profile observations"}

    monkeypatch.setattr(profile_analysis, "analyze_profiles", analyze)
    await dispatch("persona", {"source": source.name})
    assert {(person["display_name"], tuple(person["segment_ids"])) for person in catalog} == {
        ("Manual person", ("segment-0",)), ("Saved person", ("segment-1",)), ("Provider person", ("segment-2",))}


def test_removed_identify_endpoint_cannot_change_saved_state(saved):
    meeting_id = saved(suffix="retired-identify")
    before = digestion_db.get_record(meeting_id)
    app = FastAPI()
    app.include_router(router, prefix="/api/meetings")
    with TestClient(app) as client:
        response = client.post(f"/api/meetings/{meeting_id}/identify-participants")
    assert response.status_code == 410
    assert "removed" in response.json()["detail"]
    assert digestion_db.get_record(meeting_id) == before


def test_obsolete_speaker_pending_does_not_block_manual_memory_or_persona_claim(ready, source):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_digestions SET speaker_status='pending',manual_analysis=%s WHERE meeting_id=%s",
                    (Json({"memory": {"active": True}}), ready))
    memory = digestion_db.claim_manual_memory([(source.provider, source.account_key)], "manual-memory")
    assert memory["meeting_id"] == ready
    digestion_db.release(ready, "manual-memory")
    persona = digestion_db.claim_profile(source.name, "persona")
    assert persona["meeting_id"] == ready
    digestion_db.release_profile_owner("persona")


def test_retired_speaker_pending_never_wakes_an_automatic_job(saved, source):
    from services.jobs.service import has_requested_work

    meeting_id = saved(suffix="retired-speaker-wake")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_digestions SET speaker_status='pending',requested_at=clock_timestamp() WHERE meeting_id=%s", (meeting_id,))
    job = {"input_params": {"graph_type": "meeting_ingest", "graph_inputs": {"source": source.name}}}
    assert not has_requested_work(job)
    job["input_params"]["graph_inputs"]["meeting_id"] = meeting_id
    assert not has_requested_work(job)


def test_draft_is_private_until_atomic_commit_and_manual_revision_change_is_cas(ready, source):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_digestions SET speaker_status='pending' WHERE meeting_id=%s", (ready,))
    claimed = digestion_db.claim_identification(source.name, "speaker-test")
    record, artifact = speaker_db.prepare(ready, "speaker-test", claimed["transcript_hash"])
    artifact.update(offset=1, total_units=1, draft_assignments=[])
    speaker_db.save_progress(ready, "speaker-test", claimed["transcript_hash"], artifact)
    assert speaker_db.committed(digestion_db.get_record(ready)) == []
    digestion_db.release(ready, "speaker-test")
    management_db.update_participants(ready, 0, [{"name": "Manual roster"}])
    digestion_db.claim_identification(source.name, "speaker-test")
    with pytest.raises(speaker_db.AttributionInputChanged):
        speaker_db.apply(ready, "speaker-test", claimed["transcript_hash"], artifact)
    row = digestion_db.get_record(ready)
    assert row["speaker_attempts"] == 0 and row["speaker_artifact"].get("offset", 0) == 0
    digestion_db.release(ready, "speaker-test")


def test_memory_lease_allows_manual_edit_but_capture_and_persona_lock_are_explicit(ready, source):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_digestions SET speaker_status='legacy' WHERE meeting_id=%s", (ready,))
    claimed = digestion_db.claim_digestion([(source.provider, source.account_key)], "memory-editor")
    assert management_db.get_participants(ready)["edit_lock_reason"] is None
    updated = management_db.update_participants(ready, 0, [{"name": "During memory"}], claimed["transcript_hash"])
    assert updated["revision"] == 1
    digestion_db.release(ready, "memory-editor")
    digestion_db.claim_profile(source.name, "profile-editor")
    assert management_db.get_participants(ready)["edit_lock_reason"] == "analyzing_personas"
    with pytest.raises(management_db.MeetingManagementConflict, match="persona"):
        management_db.update_participants(ready, 1, [])
    digestion_db.release_profile_owner("profile-editor")


def test_disjoint_window_skips_oversized_statement_without_reusing_ids():
    segments = [{"id": f"segment-{index}", "text": "x" * length} for index, length in enumerate((1, 12_001, 2, 3))]
    first, offset = speaker_analysis.target_window(segments, 0)
    assert [row["id"] for row in first] == ["segment-0"] and offset == 1
    skipped, offset = speaker_analysis.target_window(segments, offset)
    assert skipped == [] and offset == 2
    last, offset = speaker_analysis.target_window(segments, offset)
    assert [row["id"] for row in last] == ["segment-2", "segment-3"] and offset == 4


def test_stale_statement_assignment_can_be_removed_after_transcript_changes(ready):
    from psycopg2.extras import Json

    row = digestion_db.get_record(ready)
    segment = row["transcript"]["segments"][0]
    management_db.update_participants(ready, 0, [{"name": "Old statement person", "segment_id": segment["id"]}], row["transcript_hash"])
    replacement = copy.deepcopy(row["transcript"])
    replacement["segments"][0]["id"] = "recaptured-statement"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_digestions SET transcript=%s WHERE meeting_id=%s", (Json(replacement), ready))
    assert management_db.get_participants(ready)["stale_segment_ids"] == [segment["id"]]
    assert management_db.update_participants(ready, 1, [])["items"] == []


@pytest.mark.asyncio
async def test_manual_statement_snapshot_is_retained_without_becoming_memory_analysis_input(ready, source, agents):
    row = digestion_db.get_record(ready)
    segment_id = row["transcript"]["segments"][0]["id"]
    management_db.update_participants(ready, 0, [{"name": "Manually identified", "segment_id": segment_id}], row["transcript_hash"])
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_digestions SET speaker_status='pending',memory_status='failed',memory_artifact=%s WHERE meeting_id=%s",
                    (Json(legacy_memory_artifact()), ready))
    memory_db.retry_memories(ready)
    await dispatch("meeting_ingest", {"source": source.name})
    assert agents.analyses[0][0]["memory_source"] == "summary"
    assert all(section["id"].startswith("summary-") and "effective_speaker" not in section for section in agents.analyses[0][1])
    assert "Manually identified" not in repr(agents.analyses)
    row = digestion_db.get_record(ready)
    assert row["participant_snapshot"][0]["segment_id"] == segment_id and row["participants_revision"] == 1


def test_real_roster_is_retained_when_directory_exceeds_candidate_budget():
    roster = {"name": "Meeting person", "email": "person@example.test"}
    snapshot = {"manual_participants": [roster], "identity_candidates": [{"name": f"Directory {index}", "profile_id": str(uuid4())} for index in range(250)]}
    rows = speaker_analysis.candidates(snapshot)
    assert len(rows) == 200 and rows[0] == roster


@pytest.mark.asyncio
async def test_known_canonical_candidate_reaches_shared_resolver_and_deleted_identity_cannot_publish(ready, source, monkeypatch):
    from services.meetings import profile_db
    from services.meetings import speaker_runtime

    person = profile_db.create_profile("Known speaker " + uuid4().hex)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_digestions SET speaker_status='pending' WHERE meeting_id=%s", (ready,))
    saw = []

    async def identify(snapshot, targets, **kwargs):
        candidate = next(row for row in speaker_analysis.candidates(snapshot) if row.get("profile_id") == person["id"])
        saw.append(candidate)
        return {"assignments": [assignment(targets[0], candidate["name"], profile_id=person["id"])], "reason": "Known named context"}

    monkeypatch.setattr(speaker_analysis, "identify_statements", identify)
    try:
        claimed = digestion_db.claim_identification(source.name, "historical-speaker")
        from types import SimpleNamespace

        run = SimpleNamespace(owner="historical-speaker", speaker_report={})
        await speaker_runtime.identify(run, claimed, deadline=asyncio.get_running_loop().time() + 20)
        digestion_db.release(ready, "historical-speaker")
        row = digestion_db.get_record(ready)
        assert row["speaker_status"] == "done" and saw[0]["profile_id"] == person["id"]
        assert digestion_db.get_transcript(ready)["items"][0]["effective_speaker"]["profile_id"] == person["id"]
        speaker_db.request_identification(ready)
        claimed = digestion_db.claim_identification(source.name, "deleted-speaker")
        _, artifact = speaker_db.prepare(ready, "deleted-speaker", claimed["transcript_hash"])
        artifact["draft_assignments"] = [assignment(row["transcript"]["segments"][0], person["display_name"], profile_id=person["id"])]
        profile_db.delete_profile(person["id"], person["revision"])
        with pytest.raises(ValueError, match="deleted"):
            speaker_db.apply(ready, "deleted-speaker", claimed["transcript_hash"], artifact)
    finally:
        digestion_db.release(ready, "historical-speaker")
        digestion_db.release(ready, "deleted-speaker")
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM participant_profiles WHERE id=%s", (person["id"],))


@pytest.mark.asyncio
async def test_scripted_identifier_reads_full_known_context_beyond_seed_directory_and_uses_canonical_person(source, feed, agents, model, monkeypatch, extraction_only):
    from langchain_core.messages import ToolMessage
    from types import SimpleNamespace

    from services.meetings import db, profile_analysis, profile_db, profile_directory, speaker_runtime

    person = profile_db.create_profile("Breanna " + uuid4().hex, "bree-" + uuid4().hex + "@example.test")
    person = profile_db.update_metadata(person["id"], person["revision"], nicknames=["Bree"],
                                        metadata={"company": "Example Clinic", "job_role": "Eligibility manager"},
                                        section_notes={"overview": "Coordinates careful eligibility verification."})
    segments = [TranscriptSegment("I'm Bree, and I manage eligibility at Example Clinic.", {"source": "speaker", "attribution": "them"}).to_dict(0)]
    feed.segments = (TranscriptSegment(segments[0]["text"], segments[0]["speaker"]),)
    monkeypatch.setattr(profile_directory, "names", lambda *args, **kwargs: {"items": [], "total": 0})
    monkeypatch.setattr(speaker_analysis, "identify_statements", real_identify)
    instance, roles = model([
        call("search_known_profiles", query="Bree"),
        call("stage_speakers", assignments=[assignment(segments[0], "Bree", profile_id=person["id"])], reason="Explicit introduction matches known nickname and role"),
        AIMessage(content="Done"),
    ])
    catalog = []

    async def analyze(snapshot, window, previous, *, participants, **kwargs):
        catalog.extend(participants)
        return {"items": [], "reason": "No durable profile assertion"}

    monkeypatch.setattr(profile_analysis, "analyze_profiles", analyze)
    try:
        await dispatch("meeting_ingest", {"source": source.name, "digest": False})
        meeting_id = db.list_summaries(source=source.name)["items"][0]["id"]
        claimed = digestion_db.claim_identification(source.name, "historical-lookup")
        run = SimpleNamespace(owner="historical-lookup", speaker_report={})
        await speaker_runtime.identify(run, claimed, deadline=asyncio.get_running_loop().time() + 20)
        digestion_db.release(meeting_id, "historical-lookup")
        result = json.loads(await dispatch("meeting_ingest", {"source": source.name}))
        assert "participants" not in result and roles == [("meeting_speaker", "curator")]
        reply = next(message for message in instance.seen[1] if isinstance(message, ToolMessage))
        context = json.loads(reply.content)["items"][0]
        assert context["nicknames"] == ["Bree"] and context["company"] == "Example Clinic"
        assert context["job_role"] == "Eligibility manager" and "careful eligibility" in context["overview"]
        assert agents.analyses[0][0]["memory_source"] == "summary"
        assert "effective_speaker" not in agents.analyses[0][1][0]
        row = digestion_db.get_record(meeting_id)
        assert row["speaker_artifact"]["assignments"][0]["profile_id"] == person["id"]
        assert {candidate["profile_id"] for candidate in row["speaker_artifact"]["resolved_candidates"]} == {person["id"]}
        await dispatch("persona", {"source": source.name})
        assert catalog[0]["id"] == person["id"] and catalog[0]["segment_ids"] == ["segment-0"]
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM participant_profiles WHERE id=%s", (person["id"],))


def test_known_profile_context_has_hard_envelope_budget_and_no_evidence_or_history(monkeypatch):
    from services.meetings import profile_db, speaker_profiles

    ids = [str(uuid4()) for _ in range(3)]
    monkeypatch.setattr(profile_db, "list_profiles", lambda *args, **kwargs: {"items": [{"id": key} for key in ids], "total": 100})
    seen = []

    def read(profile_id, *, include_evidence):
        seen.append(include_evidence)
        return {"id": profile_id, "display_name": "Known person", "nicknames": ["Nickname" * 10] * 20,
                "emails": ["known@example.test"], "metadata": {"company": "Org", "job_role": "Role"},
                "section_notes": {"overview": "Meaningful background. " * 1000},
                "relationships": [{"subject_name": "Known person", "target_name": "Other", "label": "Colleague", "notes": "Human constraint", "human_confirmed": True,
                                   "claims": [{"content": "PRIVATE_CLAIM"}], "history": ["PRIVATE_HISTORY"]}] * 20,
                "claims": [{"content": "PRIVATE_CLAIM"}], "merge_history": ["PRIVATE_HISTORY"]}

    monkeypatch.setattr(profile_db, "get_profile", read)
    result = speaker_profiles.read_contexts("Known", None, set())
    encoded = json.dumps(result, ensure_ascii=False)
    assert len(encoded.encode("utf-8")) <= 8000 and result["omitted"] > 0
    assert result["matched"] == 100 and result["omitted"] == 100 - len(result["items"])
    assert "PRIVATE_CLAIM" not in encoded and "PRIVATE_HISTORY" not in encoded
    assert len(result["items"][0]["overview"]) == 1500 and len(result["items"][0]["relationships"]) == 5
    assert result["items"][0]["relationships"][0]["human_confirmed"]
    assert seen and not any(seen)


@pytest.mark.asyncio
async def test_unknown_profile_id_does_not_read_or_expand_identity_catalog(model, monkeypatch):
    from langchain_core.messages import ToolMessage

    from services.meetings import profile_db

    monkeypatch.setattr(profile_db, "get_profile", lambda *args, **kwargs: pytest.fail("Unknown IDs must not be read"))
    instance, _ = model([call("search_known_profiles", profile_id=str(uuid4())),
                         call("stage_speakers", assignments=[], reason="There is no reliable identity"), AIMessage(content="Done")])
    result = await real_identify({"id": str(uuid4())}, statements(), context=[], anchors=[], deadline=asyncio.get_running_loop().time() + 20)
    reply = next(message for message in instance.seen[1] if isinstance(message, ToolMessage))
    assert "unknown profile ID" in json.loads(reply.content)["error"]
    assert result["assignments"] == [] and "resolved_candidates" not in result


@pytest.mark.asyncio
async def test_summary_memory_input_is_independent_of_canonical_rename_during_continuation(ready, source, agents, monkeypatch):
    from psycopg2.extras import Json

    from services.meetings import analysis, enrichment, profile_db

    person = profile_db.create_profile("Original canonical name " + uuid4().hex)
    segments = digestion_db.get_record(ready)["transcript"]["segments"]
    summary = "Summary part 0.Summary part 1."
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_digestions SET memory_status='failed',memory_artifact=%s WHERE meeting_id=%s",
            (Json(legacy_memory_artifact()), ready))
        cur.execute("UPDATE meeting_summaries SET summary_text=%s,revision=revision+1 WHERE id=%s", (summary, ready))
    management_db.update_participants(ready, 0, [{"name": "Nickname", "profile_id": person["id"], "speaker_key": speaker_key(segments[0]["speaker"])}])
    memory_db.retry_memories(ready)
    monkeypatch.setattr(enrichment, "WINDOW_CHARS", 15)

    async def pause(snapshot, window, previous, *, deadline):
        if previous:
            raise analysis.AnalysisBudgetExpired("Synthetic pause after the first saved summary window")
        return await agents.analyze(snapshot, window, previous, deadline=deadline)

    monkeypatch.setattr(analysis, "analyze_memories", pause)
    try:
        async with enrichment.DigestionRun(source.name) as run:
            await run.prepare()
            await run.generate_memories()
            assert run.memory_report["outcome"] == "continued"
        artifact = digestion_db.get_record(ready)["memory_artifact"]
        assert artifact["offset"] == 1 and artifact["input_snapshot"]["summary_text"] == summary
        assert "attribution_snapshot" not in artifact and "attribution_identities" not in artifact
        profile_db.update_metadata(person["id"], person["revision"], display_name="Renamed canonical person")
        monkeypatch.setattr(analysis, "analyze_memories", agents.analyze)
        async with enrichment.DigestionRun(source.name) as run:
            await run.prepare()
            await run.generate_memories()
            assert run.memory_report["outcome"] == "done", run.memory_report
        assert [call[1][0]["id"] for call in agents.analyses] == ["summary-0", "summary-1"]
        assert all(call[0]["memory_source"] == "summary" and call[0]["summary_text"] == summary for call in agents.analyses)
        assert all("effective_speaker" not in section for call in agents.analyses for section in call[1])
        assert person["display_name"] not in repr(agents.analyses) and "Renamed canonical person" not in repr(agents.analyses)
        assert profile_db.get_profile(person["id"])["display_name"] == "Renamed canonical person"
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM participant_profiles WHERE id=%s", (person["id"],))
