from uuid import uuid4

import pytest
from psycopg2.extras import Json

from services.db import get_connection
from services.meetings import profile_db
from services.meetings.participants import speaker_key
from tests.test_meeting_profiles_db import ready_meeting
from tests.test_meeting_sync import source as source
from tests.test_meetings_router import client as client


@pytest.fixture
def profiles():
    ids = []

    def create(name):
        profile = profile_db.create_profile(name, f"{uuid4().hex}@example.test")
        ids.append(profile["id"])
        return profile

    yield create
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM participant_profiles WHERE id::text=ANY(%s) OR merged_into::text=ANY(%s)", (ids, ids))


def store_people(meeting_id, *, attendees=(), manual=(), segments=(), speaker_artifact=None, profile_artifact=None):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_summaries SET metadata=%s,manual_participants=%s WHERE id=%s",
                    (Json({"attendees": list(attendees)}), Json(list(manual)), meeting_id))
        cur.execute("""UPDATE meeting_digestions SET transcript_status='ready',transcript_hash=%s,transcript=%s,
            speaker_artifact=%s,profile_status='pending',profile_artifact=%s WHERE meeting_id=%s""",
                    ("a" * 64, Json({"segments": list(segments)}), Json(speaker_artifact or {}), Json(profile_artifact or {}), meeting_id))
        assert cur.rowcount == 1


def stored_state(meeting_id):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT to_jsonb(m) AS meeting,to_jsonb(d) AS digestion FROM meeting_summaries m
            LEFT JOIN meeting_digestions d ON d.meeting_id=m.id WHERE m.id=%s""", (meeting_id,))
        meeting = cur.fetchone()
        cur.execute("SELECT to_jsonb(p) AS profile FROM participant_profiles p ORDER BY id")
        return meeting, cur.fetchall()


def summary(profile):
    return {key: profile[key] for key in ("id", "display_name", "email", "revision")}


@pytest.mark.parametrize("status", ["not_imported", "blocked", "pending", "running", "failed", "done"])
def test_meeting_profiles_show_linked_existing_people_independently_of_analysis(client, source, profiles, status):
    meeting_id = ready_meeting(source)
    first, second = profiles("zeta person"), profiles("Alpha person")
    store_people(meeting_id, attendees=[{"name": first["display_name"], "email": first["email"].upper()}],
                 manual=[{"name": second["display_name"], "profile_id": second["id"]}])
    with get_connection() as conn, conn.cursor() as cur:
        if status == "not_imported":
            cur.execute("DELETE FROM meeting_digestions WHERE meeting_id=%s", (meeting_id,))
        elif status == "blocked":
            cur.execute("UPDATE meeting_digestions SET transcript_status='pending' WHERE meeting_id=%s", (meeting_id,))
        elif status == "running":
            cur.execute("""UPDATE meeting_digestions SET profile_claim_owner='association-test',
                profile_claim_until=clock_timestamp()+interval '10 minutes' WHERE meeting_id=%s""", (meeting_id,))
        elif status in {"failed", "done"}:
            cur.execute("UPDATE meeting_digestions SET profile_status=%s WHERE meeting_id=%s", (status, meeting_id))
    before = stored_state(meeting_id)
    response = client.get(f"/api/meetings/{meeting_id}/profiles")
    assert response.status_code == 200
    assert response.json()["status"] == status
    assert response.json()["items"] == [summary(second), summary(first)]
    assert all(profile["claims"] == [] for profile in (first, second))
    assert stored_state(meeting_id) == before


def test_meeting_profiles_use_canonical_ids_without_merging_names_or_creating_people(client, source, profiles):
    meeting_id = ready_meeting(source)
    winner, loser, distinct = [profiles("Same name") for _ in range(3)]
    deleted, name_only = profiles("Deleted person"), profiles("Name only")
    alias = f"{uuid4().hex}@example.test"
    winner = profile_db.link_alias(winner["id"], alias, winner["revision"])
    winner = profile_db.merge_profiles(loser["id"], winner["id"], loser["revision"], winner["revision"])
    profile_db.delete_profile(deleted["id"], deleted["revision"])
    store_people(meeting_id, attendees=[
        {"name": "Former name", "email": alias.upper()},
        {"name": loser["display_name"], "email": loser["email"]},
        {"name": deleted["display_name"], "email": deleted["email"]},
        {"name": name_only["display_name"]},
        {"name": "Unknown person", "email": f"{uuid4().hex}@example.test"},
    ], manual=[
        {"name": "Chosen canonical", "profile_id": winner["id"]},
        {"name": "Chosen former", "profile_id": loser["id"]},
        {"name": distinct["display_name"], "profile_id": distinct["id"]},
        {"name": "Missing profile", "profile_id": str(uuid4())},
    ], segments=[{"id": "segment-0", "speaker": {"name": name_only["display_name"]}}])
    before = stored_state(meeting_id)
    result = client.get(f"/api/meetings/{meeting_id}/profiles")
    assert result.status_code == 200
    assert {item["id"] for item in result.json()["items"]} == {winner["id"], distinct["id"]}
    assert len(result.json()["items"]) == 2
    assert stored_state(meeting_id) == before


def test_meeting_profiles_reuse_effective_statement_precedence_and_ignore_stale_manual_links(client, source, profiles):
    meeting_id = ready_meeting(source)
    statement, channel, provider, automatic, shadowed, stale = [profiles(name) for name in
        ("Statement", "Channel", "Provider", "Automatic", "Shadowed automatic", "Stale manual")]
    shared = {"source": "speaker", "attribution": "them"}
    segments = [{"id": f"segment-{index}", "speaker": speaker} for index, speaker in enumerate([
        shared, shared, {"name": provider["display_name"], "email": provider["email"]}, {"source": "microphone", "attribution": "me"},
    ])]
    assignments = [{"segment_id": f"segment-{index}", "name": person["display_name"], "profile_id": person["id"], "confidence": "high"}
                   for index, person in enumerate([shadowed, shadowed, shadowed, automatic])]
    store_people(meeting_id, manual=[
        {"name": statement["display_name"], "profile_id": statement["id"], "segment_id": "segment-0"},
        {"name": channel["display_name"], "profile_id": channel["id"], "speaker_key": speaker_key(shared)},
        {"name": stale["display_name"], "profile_id": stale["id"], "segment_id": "missing-segment"},
        {"name": stale["display_name"], "profile_id": stale["id"], "speaker_key": "f" * 64},
    ], segments=segments, speaker_artifact={"committed_transcript_hash": "a" * 64, "assignments": assignments})
    before = stored_state(meeting_id)
    response = client.get(f"/api/meetings/{meeting_id}/profiles")
    assert response.status_code == 200
    assert {person["id"] for person in response.json()["items"]} == {person["id"] for person in (statement, channel, provider, automatic)}
    assert stored_state(meeting_id) == before


@pytest.mark.parametrize("committed_hash", ["a" * 64, "b" * 64])
def test_meeting_profiles_exclude_draft_and_stale_hash_statement_identities(client, source, profiles, committed_hash):
    meeting_id = ready_meeting(source)
    committed, draft = profiles("Committed"), profiles("Draft")
    def assignment(person):
        return {"segment_id": "segment-0", "name": person["display_name"], "profile_id": person["id"], "confidence": "high"}
    store_people(meeting_id, segments=[{"id": "segment-0", "speaker": {}}], speaker_artifact={
        "committed_transcript_hash": committed_hash, "assignments": [assignment(committed)], "draft_assignments": [assignment(draft)],
    })
    result = client.get(f"/api/meetings/{meeting_id}/profiles")
    assert result.status_code == 200
    assert result.json()["items"] == ([summary(committed)] if committed_hash == "a" * 64 else [])


@pytest.mark.parametrize("status", ["pending", "done"])
def test_meeting_profiles_only_include_completed_artifact_outputs(client, source, profiles, status):
    meeting_id = ready_meeting(source)
    profile = profiles("Previously generated")
    store_people(meeting_id, profile_artifact={"profile_ids": [profile["id"]]})
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_digestions SET profile_status=%s WHERE meeting_id=%s", (status, meeting_id))
    result = client.get(f"/api/meetings/{meeting_id}/profiles")
    assert result.status_code == 200
    assert result.json()["items"] == ([summary(profile)] if status == "done" else [])


@pytest.mark.parametrize("status", ["pending", "done"])
def test_meeting_profiles_project_identity_and_progress_without_loading_private_outputs(client, source, profiles, monkeypatch, status):
    meeting_id = ready_meeting(source)
    profile = profiles("Known speaker")
    assignment = {"segment_id": "segment-0", "name": profile["display_name"], "profile_id": profile["id"], "confidence": "high"}
    store_people(meeting_id, segments=[{"id": "segment-0", "speaker": {}, "text": "PRIVATE_TRANSCRIPT"}], speaker_artifact={
        "committed_transcript_hash": "a" * 64,
        "assignments": [{**assignment, "evidence": [{"quote": "PRIVATE_EVIDENCE"}], "rationale": "PRIVATE_RATIONALE"}],
        "draft_assignments": [{"quote": "PRIVATE_DRAFT"}],
    }, profile_artifact={"offset": 1, "total_units": 99, "items": [{"content": "PRIVATE_CLAIM"}],
                         "metadata_updates": [{"value": "PRIVATE_METADATA"}], "profile_ids": [profile["id"]], "reason": "Saved reason"})
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_digestions SET profile_status=%s WHERE meeting_id=%s", (status, meeting_id))
    original = profile_db._associated_profiles
    def inspect_projection(cur, row):
        assert row["segments"] == [{"id": "segment-0", "speaker": {}}]
        assert row["speaker_artifact"] == {"committed_transcript_hash": "a" * 64, "assignments": [assignment]}
        assert row["profile_artifact"] == ({"profile_ids": [profile["id"]]} if status == "done" else {})
        assert row["profile_progress"] == {"processed_units": 1, "total_units": 99, "staged_count": 2, "saved_count": 1, "attempts": 0}
        assert row["profile_reason"] == "Saved reason"
        assert "PRIVATE" not in str(row)
        return original(cur, row)
    monkeypatch.setattr(profile_db, "_associated_profiles", inspect_projection)
    result = client.get(f"/api/meetings/{meeting_id}/profiles")
    assert result.status_code == 200 and result.json()["items"] == [summary(profile)]


def test_meeting_profiles_keep_one_source_snapshot_during_transcript_replacement(client, source, profiles, monkeypatch):
    meeting_id = ready_meeting(source)
    original_person, replacement = profiles("Original speaker"), profiles("Replacement speaker")
    store_people(meeting_id, segments=[{"id": "segment-0", "speaker": {}}], speaker_artifact={
        "committed_transcript_hash": "a" * 64, "assignments": [{"segment_id": "segment-0", "name": original_person["display_name"],
            "profile_id": original_person["id"], "confidence": "high"}],
    })
    original = profile_db._associated_profiles
    after_replacement = []
    def replace_after_source_read(cur, row):
        with get_connection() as conn, conn.cursor() as writer:
            writer.execute("UPDATE meeting_digestions SET transcript_hash=%s,transcript=%s,speaker_artifact='{}'::jsonb WHERE meeting_id=%s",
                           ("b" * 64, Json({"segments": [{"id": "segment-0", "speaker": {"email": replacement["email"]}}]}), meeting_id))
        after_replacement.append(stored_state(meeting_id))
        return original(cur, row)
    monkeypatch.setattr(profile_db, "_associated_profiles", replace_after_source_read)
    response = client.get(f"/api/meetings/{meeting_id}/profiles")
    assert response.status_code == 200 and response.json()["items"] == [summary(original_person)]
    assert stored_state(meeting_id) == after_replacement[0]
    monkeypatch.setattr(profile_db, "_associated_profiles", original)
    assert client.get(f"/api/meetings/{meeting_id}/profiles").json()["items"] == [summary(replacement)]
