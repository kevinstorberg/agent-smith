from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from services.db import get_connection
from services.meetings import digestion_db, profile_db
from tests.test_meeting_profiles_db import apply, candidate, claimed as claimed, participants as participants, ready_meeting
from tests.test_meeting_profiles_router import applied as applied
from tests.test_meeting_sync import STAMP, source as source


@pytest.fixture
def client():
    from services.api.app import app

    return TestClient(app)


@pytest.fixture
def browse_profiles():
    marker = uuid4().hex
    rows = [{
        "id": str(uuid4()), "display_name": f"{name} {marker}",
        "email": f"{name.lower()}-{marker}@example.test" if index % 2 == 0 else None,
        "identity_scope": "email" if index % 2 == 0 else "meeting",
        "created_at": STAMP + timedelta(days=1 if index < 2 else 0), "deleted": index == 4,
    } for index, name in enumerate(("Alex", "Blair", "Casey", "Drew", "Removed"))]
    with get_connection() as conn, conn.cursor() as cur:
        for row in rows:
            cur.execute(
                """INSERT INTO participant_profiles (id, identity_key, display_name, email, identity_scope, created_at, updated_at, deleted)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (row["id"], "profile-list:" + row["id"], row["display_name"], row["email"], row["identity_scope"],
                 row["created_at"], row["created_at"], row["deleted"]),
            )
    yield marker, rows
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM participant_profiles WHERE id IN %s", (tuple(row["id"] for row in rows),))


def test_profiles_list_pages_all_scopes_with_immutable_order_and_lean_summaries(client, browse_profiles):
    marker, rows = browse_profiles
    expected = sorted((row for row in rows if not row["deleted"]), key=lambda row: (-row["created_at"].timestamp(), row["id"]))
    first = client.get("/api/profiles", params={"q": marker, "limit": 2}).json()
    second = client.get("/api/profiles", params={"q": marker, "limit": 2, "offset": 2}).json()
    assert first["total"] == second["total"] == 4
    assert [row["id"] for row in first["items"] + second["items"]] == [row["id"] for row in expected]
    assert {row["identity_scope"] for row in first["items"]} == {"email", "meeting"}
    for row in first["items"] + second["items"]:
        assert set(row) == {"id", "display_name", "email", "identity_scope", "revision", "created_at", "updated_at", "claim_count", "meeting_count", "tags", "starred"}
        assert row["claim_count"] == row["meeting_count"] == 0
    older = expected[-1]
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE participant_profiles SET updated_at = clock_timestamp(), revision = revision + 1 WHERE id = %s", (older["id"],))
    after = client.get("/api/profiles", params={"q": marker, "limit": 2}).json()
    assert [row["id"] for row in after["items"]] == [row["id"] for row in first["items"]]
    assert client.get("/api/profiles", params={"q": marker, "offset": 100}).json() == {"items": [], "total": 4}


def test_profiles_search_matches_trimmed_name_email_and_parameterizes_query(client, browse_profiles):
    marker, rows = browse_profiles
    for query in (f" alex {marker} ", f" {rows[0]['email'].upper()} "):
        response = client.get("/api/profiles", params={"q": query})
        assert response.status_code == 200 and response.json()["total"] == 1
        assert response.json()["items"][0]["id"] == rows[0]["id"]
    assert client.get("/api/profiles", params={"q": "' OR true --"}).json() == {"items": [], "total": 0}
    assert client.get("/api/profiles", params={"q": "Removed " + marker}).json() == {"items": [], "total": 0}


@pytest.mark.parametrize("params", [
    {"limit": 0}, {"limit": 101}, {"limit": "true"}, {"limit": 1.5}, {"offset": -1}, {"offset": 1.5},
    {"q": " "}, {"q": "x" * 1001},
])
def test_profiles_list_validates_http_inputs(client, params):
    assert client.get("/api/profiles", params=params).status_code == 422


@pytest.mark.parametrize("params", [
    {"limit": True}, {"limit": 0}, {"limit": 101}, {"offset": False}, {"offset": -1}, {"offset": 0.5},
    {"query": 1}, {"query": ""}, {"query": " "}, {"query": "x" * 1001},
])
def test_profiles_list_validates_service_inputs(params):
    with pytest.raises(ValueError):
        profile_db.list_profiles(**params)


def test_profiles_canonical_and_legacy_paths_share_handlers_and_publish_one_schema(client, browse_profiles, applied):
    from services.api.app import app

    marker, _ = browse_profiles
    profile = applied[1]
    canonical, legacy = f"/api/profiles/{profile['id']}", f"/api/meetings/profiles/{profile['id']}"
    assert client.get(canonical).json() == client.get(legacy).json()
    assert client.get("/api/profiles", params={"q": marker}).json() == client.get("/api/meetings/profiles", params={"q": marker}).json()
    schema = app.openapi()
    assert not any(path.startswith("/api/meetings/profiles") for path in schema["paths"])
    operations = [operation["operationId"] for path, methods in schema["paths"].items()
                  if path.startswith("/api/profiles") for operation in methods.values()]
    assert len(operations) == len(set(operations)) == 7

    claim_id = profile["claims"][0]["id"]
    corrected = client.post(canonical + "/claims/" + claim_id, json={
        "expected_revision": 1, "action": "correct", "content": "A clarified priority", "reason": "User clarification",
    })
    assert corrected.status_code == 200 and corrected.json()["revision"] == 2
    rejected = client.post(legacy + "/claims/" + claim_id, json={"expected_revision": 2, "action": "reject", "reason": "Incorrect interpretation"})
    assert rejected.status_code == 200 and client.get(canonical).json()["revision"] == 3
    assert client.post(canonical + "/claims/" + claim_id, json={"expected_revision": 2, "action": "reject", "reason": "Stale"}).status_code == 409
    assert client.request("DELETE", canonical, json={"expected_revision": 3}).status_code == 200
    assert client.get(legacy).status_code == 404
    for path in ("/api/profiles/not-a-uuid", "/api/meetings/profiles/not-a-uuid"):
        assert client.get(path).status_code == 422
    assert client.get(f"/api/profiles/{uuid4()}").status_code == 404


def test_profiles_http_list_accumulates_meetings_and_counts_only_visible_history(client, source, claimed, participants, applied):
    first_meeting, profile = applied
    params = {"q": profile["email"]}

    def listed():
        response = client.get("/api/profiles", params=params)
        assert response.status_code == 200 and response.json()["total"] == 1
        return response.json()["items"][0]

    original = listed()
    assert original["claim_count"] == original["meeting_count"] == original["revision"] == 1
    profile_db.correct_claim(profile["id"], profile["claims"][0]["id"], 1, "reject", None, "Keep the history")
    assert listed()["claim_count"] == 1
    digestion_db.release(claimed[0], claimed[1])
    second_meeting = ready_meeting(source, "two")
    owner = "profiles-resource-second-meeting"
    assert digestion_db.claim_digestion([(source.provider, source.account_key)], owner)["meeting_id"] == second_meeting
    try:
        record = digestion_db.get_record(second_meeting)
        apply((second_meeting, owner, record["transcript_hash"]), candidate(participants, {
            participants[0]["id"]: 2, participants[1]["id"]: 0,
        }), participants)
    finally:
        digestion_db.release(second_meeting, owner)
    current = listed()
    assert current["id"] == original["id"] and current["created_at"] == original["created_at"]
    assert current["revision"] == 3 and current["claim_count"] == current["meeting_count"] == 2
    detail = client.get(f"/api/profiles/{profile['id']}").json()
    assert {claim["meeting_id"] for claim in detail["claims"]} == {first_meeting, second_meeting}
    assert detail["claims"][0]["status"] == "rejected"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_summaries SET available = false WHERE id = %s", (first_meeting,))
    assert listed()["claim_count"] == listed()["meeting_count"] == 1
    assert len(client.get(f"/api/profiles/{profile['id']}").json()["claims"]) == 1
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_summaries SET available = false WHERE id = %s", (second_meeting,))
    assert listed()["claim_count"] == listed()["meeting_count"] == 0
    assert client.get(f"/api/profiles/{profile['id']}").json()["claims"] == []
    profile_db.delete_profile(profile["id"], 3)
    assert client.get("/api/profiles", params=params).json() == {"items": [], "total": 0}
