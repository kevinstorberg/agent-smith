import asyncio
import json
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from services.db import get_connection
from services.meetings import digestion_db, management_db, profile_analysis, profile_db, relationship_db
from services.meetings.analysis import AnalysisBudgetExpired
from services.personas import assessment, assessment_db, service as persona_service
from tests.test_meeting_memory_agent import call, model as model
from tests.test_meeting_memory_flow import feed as feed, ready as ready
from tests.test_meeting_sync import source as source


def quoted(messages):
    return json.loads(next(message.content for message in messages if isinstance(message, HumanMessage)).split("\n", 1)[1])


@pytest.mark.asyncio
async def test_actual_persona_worker_resume_and_synthesis_reference_current_human_context(ready, source, model, monkeypatch):
    capture_owner = "current-context-capture"
    captured = digestion_db.claim_digestion([(source.provider, source.account_key)], capture_owner)
    first_segment = captured["transcript"]["segments"][0]
    digestion_db.save_capture(ready, capture_owner, digestion_db.get_context(ready), {
        "segments": [first_segment, {**first_segment, "id": "segment-1"}],
    }, complete=True)
    digestion_db.release(ready, capture_owner)
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE meeting_digestions SET speaker_status='legacy' WHERE meeting_id=%s", (ready,))
    person = profile_db.create_profile("Current human " + uuid4().hex)
    other = profile_db.create_profile("Current colleague " + uuid4().hex)
    current = profile_db.update_metadata(person["id"], person["revision"], metadata={"company": "Current company", "supervisor": ""},
                                         section_notes={"drivers": "Human priority", "strengths": ""})
    relationship_db.create(person["id"], other["id"], current["revision"], other["revision"], notes="Human relationship assessment")
    management_db.update_participants(ready, 0, [{"name": current["display_name"], "profile_id": current["id"], "segment_id": "segment-0"}],
                                      digestion_db.get_record(ready)["transcript_hash"])
    monkeypatch.setattr(persona_service, "WINDOW_SEGMENTS", 1)
    real_analyze, paused = profile_analysis.analyze_profiles, False

    async def pause_once(snapshot, window, previous, **kwargs):
        nonlocal paused
        if window[0]["id"] == "segment-1" and not paused:
            paused = True
            raise AnalysisBudgetExpired("Synthetic checkpoint pause")
        return await real_analyze(snapshot, window, previous, **kwargs)

    monkeypatch.setattr(profile_analysis, "analyze_profiles", pause_once)

    async def run():
        async with persona_service.PersonaRun(source.name) as worker:
            await worker.prepare()
            await worker.build_profiles()
            return worker.profile_report

    first, _ = model([call("stage_profiles", items=[], reason="No new claims"), AIMessage(content="Done")])
    try:
        assert (await run())["outcome"] == "continued"
        initial = next(row for row in quoted(first.seen[0])["canonical_profiles"] if row["id"] == person["id"])
        assert initial["metadata"] == {"company": "Current company"}
        assert initial["metadata_provenance"]["supervisor"] == {"human": True}
        assert initial["section_notes"]["drivers"] == "Human priority" and initial["section_evidence"]["strengths"]["human"]
        assert initial["relationships"][0]["notes"] == "Human relationship assessment"
        latest = profile_db.get_profile(person["id"])
        edited = profile_db.update_metadata(person["id"], latest["revision"], metadata={"company": "Updated before resume"},
                                           section_notes={"drivers": "Updated human priority"})
        # Existing revision fencing discards the stale candidate before another call.
        assert (await run())["error_type"] == "ProfileRevisionConflict"
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE meeting_digestions SET profile_next_attempt_at=clock_timestamp() WHERE meeting_id=%s", (ready,))
        resumed, _ = model([call("stage_profiles", items=[], reason="No new claims"), AIMessage(content="Done")] * 2)
        assert (await run())["outcome"] == "done"
        fresh = next(row for row in quoted(resumed.seen[0])["canonical_profiles"] if row["id"] == person["id"])
        assert fresh["metadata"]["company"] == "Updated before resume" and fresh["section_notes"]["drivers"] == "Updated human priority"
        assert fresh["metadata_provenance"]["supervisor"]["human"] and fresh["section_evidence"]["strengths"]["human"]
        snapshot = assessment_db.claim("current-context-test", person["id"])
        final, _ = model([call("stage_assessment", sections=assessment_db.insufficient(snapshot["profile"]), reason="No additional observations"), AIMessage(content="Done")])
        await assessment.synthesize(snapshot["profile"], snapshot["claims"], deadline=asyncio.get_running_loop().time() + 20)
        payload = quoted(final.seen[0])
        assert payload["profile"]["metadata"] == edited["metadata"]
        assert payload["profile"]["section_notes"]["drivers"] == "Updated human priority"
        assert payload["profile"]["metadata_provenance"]["supervisor"]["human"]
        assert payload["profile"]["section_evidence"]["strengths"]["human"]
        assert payload["relationships"][0]["notes"] == "Human relationship assessment"
        assert profile_db.get_profile(person["id"])["metadata"] == edited["metadata"]
    finally:
        assessment_db.release_owner("current-context-test")
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM participant_profiles WHERE id IN %s", ((person["id"], other["id"]),))
