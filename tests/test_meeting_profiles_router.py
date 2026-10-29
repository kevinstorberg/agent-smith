from uuid import uuid4

import pytest

from services.db import get_connection
from services.meetings import digestion_db, profile_db
from tests.test_meeting_profiles_db import apply, candidate, claimed as claimed, participants as participants
from tests.test_meeting_sync import source as source
from tests.test_meetings_router import client as client, saved as saved


@pytest.fixture
def applied(claimed, participants):
    apply(claimed, candidate(participants), participants)
    return claimed[0], profile_db.get_profile(participants[0]["id"])


def test_profile_routes_expose_applied_profiles_and_grounded_claims(client, applied):
    meeting_id, profile = applied
    listed = client.get(f"/api/meetings/{meeting_id}/profiles")
    assert listed.status_code == 200 and listed.json()["status"] == "done"
    assert listed.json()["items"] == [{key: profile[key] for key in ("id", "display_name", "email", "revision")}]
    detail = client.get(f"/api/meetings/profiles/{profile['id']}")
    assert detail.status_code == 200
    assert detail.json()["identity_scope"] == "email"
    assert detail.json()["claims"][0]["evidence"] == profile["claims"][0]["evidence"]
    assert detail.json()["claims"][0]["target_name"] == "Blair"


def test_profile_http_correction_rejection_and_conflict_preserve_original_evidence(client, applied):
    _, profile = applied
    original = profile["claims"][0]
    path = f"/api/meetings/profiles/{profile['id']}/claims/{original['id']}"
    body = {"expected_revision": 1, "action": "correct", "content": "Values reliability when practical", "reason": "Clarified by participant"}
    response = client.post(path, json=body)
    assert response.status_code == 200 and response.json()["revision"] == 2
    claim = response.json()["claims"][0]
    assert claim["status"] == "corrected" and claim["correction"]["content"] == body["content"]
    assert claim["content"] == original["content"] and claim["evidence"] == original["evidence"]
    assert client.post(path, json=body).status_code == 409
    assert profile_db.get_profile(profile["id"])["revision"] == 2

    rejected = client.post(path, json={"expected_revision": 2, "action": "reject", "reason": "The interpretation is incorrect"})
    assert rejected.status_code == 200 and rejected.json()["revision"] == 3
    claim = rejected.json()["claims"][0]
    assert claim["status"] == "rejected" and claim["correction"]["reason"] == "The interpretation is incorrect"
    assert claim["content"] == original["content"] and claim["evidence"] == original["evidence"]


def test_profile_http_deletion_checks_revision_and_retains_tombstone(client, applied, participants):
    meeting_id, profile = applied
    path = f"/api/meetings/profiles/{profile['id']}"
    stale = client.request("DELETE", path, json={"expected_revision": 2})
    assert stale.status_code == 409 and profile_db.get_profile(profile["id"]) is not None
    removed = client.request("DELETE", path, json={"expected_revision": 1})
    assert removed.status_code == 200 and removed.json() == {"deleted": True, "id": profile["id"]}
    assert client.get(path).status_code == 404
    assert client.get(f"/api/meetings/{meeting_id}/profiles").json()["items"] == []
    deleted = profile_db.load_profiles(participants)[0]
    assert deleted["deleted"] and deleted["revision"] == 2 and deleted["claims"] == []
    assert client.post(f"/api/meetings/{meeting_id}/profiles/retry").status_code == 422


@pytest.mark.parametrize("changes", [
    {"expected_revision": True}, {"expected_revision": 0}, {"reason": " "}, {"action": "overwrite"},
    {"content": " "}, {"content": None}, {"content": "x" * 2001}, {"unexpected": "field"},
])
def test_profile_http_validates_corrections_before_mutating(client, applied, changes):
    _, profile = applied
    body = {"expected_revision": 1, "action": "correct", "content": "A corrected claim", "reason": "A grounded correction", **changes}
    path = f"/api/meetings/profiles/{profile['id']}/claims/{profile['claims'][0]['id']}"
    assert client.post(path, json=body).status_code == 422
    assert profile_db.get_profile(profile["id"])["revision"] == 1


def test_profile_http_retry_queues_only_a_failed_stage_with_completed_inputs(client, claimed):
    meeting_id, owner, _ = claimed
    for _ in range(3):
        profile_db.record_failure(meeting_id, owner, "SafeFailure")
    digestion_db.release_profile_owner(owner)
    assert client.get(f"/api/meetings/{meeting_id}/profiles").json()["status"] == "failed"
    response = client.post(f"/api/meetings/{meeting_id}/profiles/retry")
    assert response.status_code == 200 and response.json() == {"success": True}
    assert client.get(f"/api/meetings/{meeting_id}/profiles").json()["status"] == "pending"
    assert client.post(f"/api/meetings/{meeting_id}/profiles/retry").status_code == 422


def test_profile_http_rejects_old_missing_and_unavailable_meetings(client, saved):
    _, rows, _ = saved
    old_id, unavailable_id = rows[0]["id"], rows[1]["id"]
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM meeting_digestions WHERE meeting_id = %s", (old_id,))
        cur.execute("UPDATE meeting_summaries SET available = false WHERE id = %s", (unavailable_id,))
    old = client.get(f"/api/meetings/{old_id}/profiles")
    assert old.status_code == 200 and old.json()["status"] == "not_imported"
    assert client.post(f"/api/meetings/{old_id}/profiles/retry").status_code == 422
    for key in (str(uuid4()), unavailable_id):
        assert client.get(f"/api/meetings/{key}/profiles").status_code == 404
        assert client.post(f"/api/meetings/{key}/profiles/retry").status_code == 404
    assert client.get("/api/meetings/not-a-uuid/profiles").status_code == 422


def test_profile_http_hides_claims_after_source_meeting_becomes_unavailable(client, applied):
    meeting_id, profile = applied
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_summaries SET available = false WHERE id = %s", (meeting_id,))
    response = client.get(f"/api/meetings/profiles/{profile['id']}")
    assert response.status_code == 200 and response.json()["claims"] == []


def test_profile_http_validates_profile_and_claim_identifiers(client, applied):
    _, profile = applied
    assert client.get("/api/meetings/profiles/not-a-uuid").status_code == 422
    assert client.get(f"/api/meetings/profiles/{uuid4()}").status_code == 404
    path = f"/api/meetings/profiles/{profile['id']}/claims/not-a-uuid"
    body = {"expected_revision": 1, "action": "reject", "reason": "Wrong attribution"}
    assert client.post(path, json=body).status_code == 422
    assert client.request("DELETE", f"/api/meetings/profiles/{profile['id']}", json={"expected_revision": True}).status_code == 422
