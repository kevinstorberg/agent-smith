import json

import pytest
from psycopg2.extras import Json

from services.db import get_connection
from services.meetings import profile_db, profile_metadata, relationship_db
from services.personas import sections
from tests.test_meeting_profiles_db import candidate, claimed as claimed, participants as participants
from tests.test_meeting_sync import source as source
from tests.test_profiles_router import client as client


def invalidate(meeting_id, change):
    with get_connection() as connection, connection.cursor() as cur:
        if change == "withdrawn":
            cur.execute("UPDATE meeting_summaries SET available=false WHERE id=%s", (meeting_id,))
        elif change == "deleted":
            cur.execute("UPDATE meeting_digestions SET transcript_status='deleted' WHERE meeting_id=%s", (meeting_id,))
        elif change == "hash":
            cur.execute("UPDATE meeting_digestions SET transcript_hash=%s WHERE meeting_id=%s", ("f" * 64, meeting_id))
        else:
            cur.execute("UPDATE meeting_summaries SET participants_revision=participants_revision+1 WHERE id=%s", (meeting_id,))


@pytest.mark.parametrize("change", ["withdrawn", "deleted", "hash", "attribution"])
def test_live_profile_reads_and_counts_hide_unavailable_source_claims(client, claimed, participants, change):
    profile_db.apply_profiles(*claimed, candidate(participants), participants)
    subject, target = [profile_db.get_profile(person["id"]) for person in participants]
    assert subject["relationships"][0]["claim_count"] == 1
    invalidate(claimed[0], change)
    public = client.get(f"/api/profiles/{subject['id']}")
    assert public.status_code == 200 and public.json()["claims"] == public.json()["relationships"] == []
    assert all(profile["claims"] == [] and profile["relationships"] == [] for profile in profile_db.load_profiles(participants))
    listed = profile_db.list_profiles(query=subject["email"])["items"]
    assert len(listed) == 1 and listed[0]["claim_count"] == listed[0]["meeting_count"] == 0
    with get_connection() as connection, connection.cursor() as cur:
        cur.execute("SELECT id,revision FROM profile_relationships WHERE subject_id=%s AND target_id=%s", (subject["id"], target["id"]))
        edge_id, revision = cur.fetchone()
    edge = relationship_db.update(subject["id"], str(edge_id), revision, notes="Human-confirmed working relationship")
    assert edge["claims"] == [] and edge["human_confirmed"]
    assert profile_db.get_profile(subject["id"])["relationships"][0]["notes"] == "Human-confirmed working relationship"


@pytest.mark.parametrize("change", ["deleted", "hash", "attribution"])
@pytest.mark.parametrize("action", ["correct", "reject"])
def test_invalid_source_keeps_only_sanitized_internal_human_constraints(claimed, participants, change, action):
    profile_db.apply_profiles(*claimed, candidate(participants), participants)
    subject = profile_db.get_profile(participants[0]["id"])
    original = subject["claims"][0]
    profile_db.correct_claim(subject["id"], original["id"], subject["revision"], action,
                             "Human refinement" if action == "correct" else None, "Human direction")
    invalidate(claimed[0], change)
    assert profile_db.get_profile(subject["id"])["claims"] == []
    internal = profile_db.load_profiles(participants)[0]
    assert len(internal["claims"]) == 1
    constraint = internal["claims"][0]
    assert constraint["source_unavailable"] and constraint["evidence"] == [] and constraint["source_url"] is None
    assert constraint["correction"]["reason"] == "Human direction" and constraint["rationale"] == ""
    assert original["evidence"][0]["quote"] not in json.dumps(internal)
    listed = profile_db.list_profiles(query=subject["email"])["items"][0]
    assert listed["claim_count"] == listed["meeting_count"] == 0


def test_legacy_missing_attribution_revision_only_matches_original_revision(claimed, participants):
    profile_db.apply_profiles(*claimed, candidate(participants), participants)
    subject = profile_db.get_profile(participants[0]["id"])
    legacy = {key: value for key, value in subject["claims"][0].items() if key != "participants_revision"}
    with get_connection() as connection, connection.cursor() as cur:
        cur.execute("UPDATE participant_profiles SET claims=%s WHERE id=%s", (Json([legacy]), subject["id"]))
    context = {claimed[0]: {"available": True, "transcript_status": "ready", "transcript_hash": claimed[2], "participants_revision": 0}}
    assert profile_metadata.claim_source_valid(legacy, context)
    assert len(sections.effective_claims({"claims": [legacy]}, context)) == 1
    assert len(profile_db.get_profile(subject["id"])["claims"]) == 1
    assert profile_db.list_profiles(query=subject["email"])["items"][0]["claim_count"] == 1
    invalidate(claimed[0], "attribution")
    context[claimed[0]]["participants_revision"] = 1
    assert not profile_metadata.claim_source_valid(legacy, context)
    assert sections.effective_claims({"claims": [legacy]}, context) == []
    assert profile_db.get_profile(subject["id"])["claims"] == []
    listed = profile_db.list_profiles(query=subject["email"])["items"][0]
    assert listed["claim_count"] == listed["meeting_count"] == 0
