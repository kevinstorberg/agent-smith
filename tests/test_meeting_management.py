import copy
import json
from uuid import uuid4

import pytest

from services.db import get_connection
from services.graphs.runtime import dispatch
from services.meetings import db, digestion_db, management_db, profile_db
from services.meetings.participants import email_participant
from services.meetings.types import TranscriptSegment
from tests.test_meeting_memory_flow import agents as agents, feed as feed
from tests.test_meeting_profiles_db import apply, candidate, claimed as claimed, participants as participants
from tests.test_meeting_sync import note, source as source
from tests.test_meeting_transcript_capture import enroll
from tests.test_meetings_router import client as client, saved as saved


def path(meeting_id):
    return f"/api/meetings/{meeting_id}"


def test_explicit_old_meeting_request_enrolls_once_and_takes_priority(client, saved):
    configs, rows, _ = saved
    older, automatic = rows
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM meeting_digestions WHERE meeting_id = %s", (older["id"],))
    assert client.get(path(older["id"]) + "/participants").json()["enrolled"] is False
    assert client.post(path(older["id"]) + "/process").json() == {"status": "queued"}
    first = digestion_db.get_record(older["id"])
    assert first["requested_at"] and first["transcript_status"] == "pending"
    assert client.post(path(older["id"]) + "/process").json() == {"status": "queued"}
    assert digestion_db.get_record(older["id"])["requested_at"] == first["requested_at"]
    identities = [(config.provider, config.account_key) for config in configs]
    assert digestion_db.claim_digestion(identities, "manual-priority")["meeting_id"] == older["id"]
    digestion_db.release(older["id"], "manual-priority")
    assert digestion_db.get_record(automatic["id"])["requested_at"] is None


def test_manual_roster_is_revision_safe_survives_provider_refresh_and_does_not_autoenroll(client, saved):
    configs, rows, _ = saved
    meeting = rows[0]
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM meeting_digestions WHERE meeting_id = %s", (meeting["id"],))
    body = {"expected_revision": 0, "participants": [{"name": "  Alex  ", "email": "ALEX@example.invalid"}]}
    response = client.put(path(meeting["id"]) + "/participants", json=body)
    assert response.status_code == 200
    data = response.json()
    assert data["revision"] == 1 and data["items"] == [{"name": "Alex", "email": "alex@example.invalid"}]
    assert not data["enrolled"] and digestion_db.get_record(meeting["id"]) is None
    assert client.put(path(meeting["id"]) + "/participants", json=body).status_code == 409
    noop = {**body, "expected_revision": 1}
    assert client.put(path(meeting["id"]) + "/participants", json=noop).json()["revision"] == 1
    config = configs[0]
    assert db.claim_source(config, "refresh")
    db.save_progress(config, "refresh", {}, summary=note(text="Provider changed its summary"))
    db.release_source(config, "refresh", "completed")
    after = client.get(path(meeting["id"]) + "/participants").json()
    assert after["items"] == data["items"] and after["revision"] == 1


def test_active_processing_rejects_participant_edit_and_claim_snapshots_human_inputs(client, saved):
    configs, rows, _ = saved
    meeting_id = rows[0]["id"]
    saved_people = [{"name": "Alex", "email": "alex@example.invalid"}]
    assert client.put(path(meeting_id) + "/participants", json={"expected_revision": 0, "participants": saved_people}).status_code == 200
    claimed = digestion_db.claim_digestion([(configs[0].provider, configs[0].account_key)], "active-editor")
    assert claimed["participant_snapshot"] == saved_people and claimed["participants_revision"] == 1
    before = db.get_summary(meeting_id)
    response = client.put(path(meeting_id) + "/participants", json={"expected_revision": 1, "participants": []})
    assert response.status_code == 409
    assert db.get_summary(meeting_id)["manual_participants"] == before["manual_participants"]
    assert client.post(path(meeting_id) + "/process").json() == {"status": "running"}
    digestion_db.release(meeting_id, "active-editor")


@pytest.mark.parametrize("changes", [
    {"expected_revision": True}, {"expected_revision": -1}, {"unexpected": True},
    {"participants": [{"name": " "}]}, {"participants": [{"name": "Alex", "email": "not-an-email"}]},
    {"participants": [{"name": "Alex", "speaker_key": "f" * 64}]},
    {"participants": [{"name": "Alex", "profile_id": str(uuid4())}]},
    {"participants": [{"name": "Alex", "extra": "field"}]},
    {"participants": [{"name": "Alex"}] * 201},
])
def test_participant_boundary_rejects_invalid_inputs_without_changes(client, saved, changes):
    meeting_id = saved[1][0]["id"]
    response = client.put(path(meeting_id) + "/participants", json={"expected_revision": 0, "participants": [], **changes})
    assert response.status_code == 422
    assert client.get(path(meeting_id) + "/participants").json()["revision"] == 0


def test_processing_keeps_explicit_deletion_and_source_unavailability(client, saved):
    meeting_id = saved[1][0]["id"]
    digestion_db.delete_transcript(meeting_id)
    assert client.post(path(meeting_id) + "/process").status_code == 422
    assert digestion_db.get_record(meeting_id)["transcript_status"] == "deleted"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_summaries SET available = false WHERE id = %s", (meeting_id,))
    assert client.get(path(meeting_id) + "/participants").status_code == 404
    assert client.post(path(meeting_id) + "/process").status_code == 404
    assert client.put(path(meeting_id) + "/participants", json={"expected_revision": 0, "participants": []}).status_code == 404


def test_changing_speaker_assignment_retires_wrong_attribution_without_losing_memory_or_history(client, claimed, participants):
    apply(claimed, candidate(participants), participants)
    meeting_id, owner, _ = claimed
    profile = profile_db.get_profile(participants[0]["id"])
    claim = profile["claims"][0]
    profile_db.correct_claim(profile["id"], claim["id"], profile["revision"], "correct", "Human clarification", "Participant correction")
    digestion_db.release(meeting_id, owner)
    before = digestion_db.get_record(meeting_id)
    response = client.get(path(meeting_id) + "/participants").json()
    assert response["speakers"] and "transcript" not in response and "I prioritize" not in json.dumps(response)
    data = client.put(path(meeting_id) + "/participants", json={"expected_revision": 0, "participants": [{
        "name": "Actual speaker", "email": "actual@example.invalid", "speaker_key": response["speakers"][0]["key"],
    }]})
    assert data.status_code == 200
    after = digestion_db.get_record(meeting_id)
    assert after["snapshot"] == before["snapshot"] and after["transcript"] == before["transcript"]
    assert after["memory_artifact"] == before["memory_artifact"] and after["memory_status"] == "done"
    assert after["profile_status"] == "pending" and after["profile_artifact"] == {}
    assert profile_db.get_profile(profile["id"])["claims"] == []
    internal = profile_db.load_profiles(participants)[0]
    assert internal["claims"][0]["superseded"] and internal["claims"][0]["id"] == claim["id"]
    assert internal["claims"][0]["correction"]["content"] == "Human clarification"


def test_existing_profile_can_be_assigned_but_deleted_profile_cannot(client, claimed, participants):
    apply(claimed, candidate(participants), participants)
    meeting_id, owner, _ = claimed
    digestion_db.release(meeting_id, owner)
    speakers = client.get(path(meeting_id) + "/participants").json()["speakers"]
    person = {"name": "Alex", "profile_id": participants[0]["id"], "speaker_key": speakers[0]["key"]}
    response = client.put(path(meeting_id) + "/participants", json={"expected_revision": 0, "participants": [person]})
    assert response.status_code == 200 and response.json()["items"][0]["profile_id"] == person["profile_id"]
    profile = profile_db.get_profile(person["profile_id"])
    profile_db.delete_profile(profile["id"], profile["revision"])
    rejected = client.put(path(meeting_id) + "/participants", json={"expected_revision": 1, "participants": [person]})
    assert rejected.status_code == 422


@pytest.mark.asyncio
async def test_older_meeting_manual_roster_reaches_real_graph_catalog_without_republishing_memories(source, feed, agents, monkeypatch):
    from services.meetings import profile_analysis

    person = email_participant(f"alex-{source.account_key}@example.invalid", "Alex")
    meeting_id = enroll(source, feed.summaries["one"])
    feed.segments = (TranscriptSegment("I prioritize accurate records", {"name": "Alex"}),)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM meeting_digestions WHERE meeting_id = %s", (meeting_id,))
    management_db.update_participants(meeting_id, 0, [{"name": "Alex", "email": person["email"]}])
    assert digestion_db.get_record(meeting_id) is None
    calls = []

    async def analyze(snapshot, window, previous, *, participants, profiles, memories, deadline):
        calls.append(copy.deepcopy(participants))
        return {"items": [{"subject_id": participants[0]["id"], "target_id": None, "category": "priority",
                           "content": "Prioritizes accurate records", "epistemic": "self_report", "confidence": "high",
                           "rationale": "Direct statement", "evidence": [{"segment_id": window[0]["id"], "quote": window[0]["text"]}]}], "reason": ""}

    monkeypatch.setattr(profile_analysis, "analyze_profiles", analyze)
    try:
        management_db.request_processing(meeting_id)
        result = json.loads(await dispatch("meeting_ingest", {"source": source.name}))
        assert result["profiles"]["outcome"] == "done" and calls[0][0]["id"] == person["id"]
        profile = profile_db.get_profile(person["id"])
        original_claim = copy.deepcopy(profile["claims"][0])
        profile_db.correct_claim(profile["id"], original_claim["id"], profile["revision"], "correct", "Accuracy is important", "Clarified")
        frozen = copy.deepcopy(digestion_db.get_record(meeting_id))
        assert len(agents.analyses) == len(agents.publications) == 1
        assert management_db.request_processing(meeting_id) == {"status": "done"}
        management_db.update_participants(meeting_id, 1, [
            {"name": "Alex", "email": person["email"]}, {"name": "Silent attendee", "email": "silent@example.invalid"},
        ])
        await dispatch("meeting_ingest", {"source": source.name})
        updated = profile_db.get_profile(person["id"])
        assert len(updated["claims"]) == 1 and updated["claims"][0]["id"] == original_claim["id"]
        assert updated["claims"][0]["correction"]["content"] == "Accuracy is important"
        assert len(agents.analyses) == len(agents.publications) == 1
        assert digestion_db.get_record(meeting_id)["memory_artifact"] == frozen["memory_artifact"]
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM participant_profiles WHERE id = %s", (person["id"],))
