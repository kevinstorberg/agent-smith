import copy
import json
from uuid import uuid4

import pytest
from psycopg2.extras import Json

from services.db import get_connection
from services.meetings import digestion_db, management_db, processing_db, profile_db
from tests.test_meetings_router import client as client, saved as saved


@pytest.mark.parametrize("transcript,status,running", [
    (None, "pending", False), ("pending", "pending", False), ("pending", "pending", True),
    ("ready", "pending", False), ("ready", "pending", True), ("ready", "done", True),
    ("ready", "failed", False), ("ready", "failed", True), ("deleted", "pending", False),
    ("deleted", "done", False), ("unavailable", "pending", False), ("unsupported", "failed", False),
    ("failed", "pending", False),
])
def test_compact_and_all_public_stage_readers_share_characterization_matrix(client, saved, transcript, status, running):
    meeting_id = saved[1][0]["id"]
    with get_connection() as conn, conn.cursor() as cur:
        if transcript is None:
            cur.execute("DELETE FROM meeting_digestions WHERE meeting_id=%s", (meeting_id,))
        else:
            artifact = {"offset": 1, "total_units": 2, "items": [{"id": str(uuid4()), "content": "PRIVATE_MEMORY"}],
                        "metadata_updates": [{"value": "PRIVATE_METADATA"}], "profile_ids": [], "published_ids": ["receipt"], "reason": "saved reason"}
            speaker = {"offset": 1, "total_units": 2, "draft_assignments": [{"quote": "PRIVATE_QUOTE"}], "assignments": [{"confidence": "high"}]}
            cur.execute("""UPDATE meeting_digestions SET transcript_status=%s,transcript=%s,transcript_hash=%s,
                memory_status=%s,profile_status=%s,speaker_status=%s,memory_artifact=%s,profile_artifact=%s,speaker_artifact=%s,
                memory_error='MemoryError',profile_error='ProfileError',speaker_error='SpeakerAnalysisError',
                claim_until=CASE WHEN %s THEN clock_timestamp()+interval '5 minutes' ELSE NULL END,
                profile_claim_until=CASE WHEN %s THEN clock_timestamp()+interval '5 minutes' ELSE NULL END WHERE meeting_id=%s""",
                (transcript, Json({"segments": [{"id": "segment-0", "text": "PRIVATE_TRANSCRIPT", "speaker": {}}]}), "a" * 64,
                 status, status, status, Json(artifact), Json(artifact), Json(speaker), running, running, meeting_id))
    base = f"/api/meetings/{meeting_id}"
    compact = client.get(base + "/processing")
    assert compact.status_code == 200
    data = compact.json()
    assert data["transcript"]["status"] == ("not_imported" if transcript is None else "capturing" if transcript == "pending" and running else transcript)
    expected_generation = "not_imported" if transcript is None else "done" if status == "done" else "blocked" if transcript != "ready" else "running" if running else status
    assert data["memories"]["status"] == data["profiles"]["status"] == expected_generation
    assert data["speakers"]["status"] == ("not_imported" if transcript is None else "running" if status == "pending" and running else status)
    full_transcript = digestion_db.get_transcript(meeting_id)
    assert data["transcript"] == {key: full_transcript[key] for key in ("status", "total", "error_type", "captured_at")}
    for name in ("memories", "profiles"):
        full = client.get(base + "/" + name).json()
        assert data[name] == {key: full[key] for key in ("status", "reason", "error_type", "progress")}
        assert client.get(base + "/" + name).json()["status"] == data[name]["status"]
    people = client.get(base + "/participants").json()
    assert data["speakers"] == people["attribution"]
    assert data["edit_lock_reason"] == people["edit_lock_reason"]
    assert "PRIVATE" not in compact.text
    assert set(data) == {"transcript", "speakers", "memories", "profiles", "edit_lock_reason"}


def test_ready_transcript_does_not_hide_a_speaker_failure_before_any_statement_was_reviewed(client, saved):
    meeting_id = saved[1][0]["id"]
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""UPDATE meeting_digestions SET transcript_status='ready',transcript='{"segments":[]}'::jsonb,
            speaker_status='failed',speaker_error='SpeakerAnalysisError',speaker_artifact='{"offset":0}'::jsonb
            WHERE meeting_id=%s""", (meeting_id,))
    state = client.get(f"/api/meetings/{meeting_id}/processing").json()
    assert state["transcript"]["status"] == "ready"
    assert state["speakers"]["status"] == "failed" and state["speakers"]["error_type"] == "SpeakerAnalysisError"
    assert state["speakers"]["progress"]["processed_units"] == 0


def test_compact_state_is_read_only_and_checks_meeting_boundary(client, saved):
    meeting_id = saved[1][0]["id"]
    before = digestion_db.get_record(meeting_id)
    assert processing_db.get_processing(meeting_id)
    assert digestion_db.get_record(meeting_id) == before
    assert client.get(f"/api/meetings/{uuid4()}/processing").status_code == 404
    assert client.get("/api/meetings/invalid/processing").status_code == 422
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_summaries SET available=false WHERE id=%s", (meeting_id,))
    assert client.get(f"/api/meetings/{meeting_id}/processing").status_code == 404


def test_people_group_verified_aliases_without_changing_each_statement_or_provider_entry(client, saved):
    meeting_id = saved[1][0]["id"]
    email = f"personal-{uuid4().hex}@example.test"
    profile = profile_db.create_profile("Complete Canonical Name", email)
    alias_email = f"work-{uuid4().hex}@example.test"
    profile = profile_db.link_alias(profile["id"], alias_email, profile["revision"])
    assignments = [{"name": "Manual nickname", "email": alias_email.upper(), "profile_id": profile["id"], "segment_id": f"segment-{index}"} for index in range(5)]
    provider = [{"name": "Full provider display name", "email": email.upper()}, {"name": "Unlinked complete name"}]
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("UPDATE meeting_summaries SET manual_participants=%s,metadata=%s WHERE id=%s", (Json(assignments), Json({"attendees": provider}), meeting_id))
            cur.execute("UPDATE meeting_digestions SET transcript_status='ready',speaker_status='legacy',transcript_hash=%s,transcript=%s,snapshot=%s WHERE meeting_id=%s",
                        ("a" * 64, Json({"segments": [{"id": f"segment-{index}", "text": "Saved statement", "speaker": {}} for index in range(5)]}),
                         Json({"id": meeting_id, "metadata": {"attendees": provider}}), meeting_id))
        data = client.get(f"/api/meetings/{meeting_id}/participants").json()
        assert len(data["people"]) == 1
        person = data["people"][0]
        assert person["key"] == "profile:" + profile["id"]
        assert person["display_name"] == "Complete Canonical Name" and person["profile_id"] == profile["id"]
        assert person["assignments"] == assignments
        assert set(person["emails"]) == {email, alias_email}
        assert person["sources"] == ["provider", "manual"]
        assert data["items"] == assignments and data["provider_participants"] == provider
        assert data["unlinked_attendees"] == [{"source": "provider", "participant": provider[1]}]
        assert management_db.get_participants(meeting_id)["items"] == assignments
        remaining = [entry for entry in assignments if entry["segment_id"] != "segment-2"]
        removed = client.put(f"/api/meetings/{meeting_id}/participants", json={"expected_revision": data["revision"],
            "expected_transcript_hash": "a" * 64, "participants": remaining})
        assert removed.status_code == 200
        after = removed.json()
        assert len(after["people"]) == 1 and len(after["people"][0]["assignments"]) == 4
        assert {entry["segment_id"] for entry in after["items"]} == {entry["segment_id"] for entry in remaining}
        assert after["provider_participants"] == provider
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM participant_profiles WHERE merged_into=%s OR id=%s", (profile["id"], profile["id"]))


def test_unlinked_assignments_use_stable_source_references_not_names_or_array_positions(saved):
    meeting_id = saved[1][0]["id"]
    entries = [{"name": "Sam", "segment_id": "segment-9"}, {"name": "Sam", "segment_id": "segment-4"}, {"name": "A bare roster name"}]
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_summaries SET manual_participants=%s WHERE id=%s", (Json(entries), meeting_id))
    first = management_db.get_participants(meeting_id)
    assert {person["key"] for person in first["people"]} == {"statement:segment-9", "statement:segment-4"}
    changed = copy.deepcopy(entries)
    changed[0]["name"] = "Updated display name"
    changed.reverse()
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_summaries SET manual_participants=%s WHERE id=%s", (Json(changed), meeting_id))
    second = management_db.get_participants(meeting_id)
    assert {person["key"] for person in second["people"]} == {person["key"] for person in first["people"]}
    assert len(second["unlinked_attendees"]) == 1
    assert json.dumps(entries) != json.dumps(changed)
