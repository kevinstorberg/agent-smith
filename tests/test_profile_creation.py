import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest

from services.db import get_connection
from services.graphs.runtime import dispatch
from services.meetings import db, digestion_db, management_db, profile_db
from services.meetings.participants import email_participant, speaker_key
from services.meetings.types import TranscriptSegment
from tests.test_meeting_memory_flow import agents as agents, feed as feed
from tests.test_meeting_profiles_db import claimed as claimed, participants as participants
from tests.test_meeting_profiles_router import applied as applied
from tests.test_meeting_sync import note, source as source
from tests.test_profile_identity_flow import profile_agent as profile_agent
from tests.test_profiles_router import client as client


@pytest.fixture
def created_profiles():
    ids = []
    yield ids
    if ids:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM participant_profiles WHERE merged_into IN %s", (tuple(ids),))
            cur.execute("DELETE FROM participant_profiles WHERE id IN %s", (tuple(ids),))


def post_profile(client, ids, body, path="/api/profiles"):
    response = client.post(path, json=body)
    if response.status_code == 201:
        ids.append(response.json()["id"])
    return response


def test_name_only_profiles_are_first_class_and_duplicate_names_stay_separate(client, created_profiles):
    first = post_profile(client, created_profiles, {"display_name": " Jordan Rivera "})
    second = post_profile(client, created_profiles, {"display_name": "Jordan Rivera", "email": None}, "/api/meetings/profiles")
    assert first.status_code == second.status_code == 201
    profile = first.json()
    assert profile["display_name"] == "Jordan Rivera" and profile["email"] is None and profile["identity_scope"] == "manual"
    assert profile["id"] != second.json()["id"] and UUID(profile["id"]).version == 4
    assert profile["identity_key"] == "manual:" + profile["id"]
    assert profile["claims"] == profile["aliases"] == profile["merge_history"] == profile["tags"] == []
    assert profile["revision"] == 1 and not profile["starred"]
    assert client.get(f"/api/profiles/{profile['id']}").json() == profile
    listed = client.get("/api/profiles", params={"q": "Jordan Rivera"}).json()
    assert listed["total"] == 2 and all(row["claim_count"] == row["meeting_count"] == 0 for row in listed["items"])
    assert profile_db.load_profiles([{**profile, "segment_ids": []}])[0]["identity_scope"] == "manual"


def test_email_creation_uses_normalized_meeting_identity_and_exports_actual_http_contract(client, created_profiles, tmp_path):
    request = {"display_name": "Jordan Rivera", "email": "jordan.rivera.contract@example.invalid"}
    response = post_profile(client, created_profiles, request)
    assert response.status_code == 201
    expected = email_participant(request["email"].upper(), request["display_name"])
    profile = response.json()
    assert profile["id"] == expected["id"] and profile["identity_key"] == expected["identity_key"]
    assert profile["email"] == expected["email"] and profile["identity_scope"] == "email"
    duplicate_request = {"display_name": "A different name", "email": " " + request["email"].upper() + " "}
    duplicate = post_profile(client, created_profiles, duplicate_request)
    assert duplicate.status_code == 409 and "existing profile" in duplicate.json()["detail"]
    assert profile_db.get_profile(profile["id"]) == profile
    (tmp_path / "profile-create-contract.json").write_text(json.dumps({
        "create": {"request": request, "status": response.status_code, "body": profile},
        "duplicate": {"request": duplicate_request, "status": duplicate.status_code, "body": duplicate.json()},
    }, indent=2))


@pytest.mark.parametrize("owner_state", ["canonical", "alias", "deleted"])
def test_create_never_takes_over_an_email_identity(client, created_profiles, owner_state):
    email = "owner-" + uuid4().hex + "@example.invalid"
    body = {"display_name": "Original owner"}
    if owner_state != "alias":
        body["email"] = email
    owner = post_profile(client, created_profiles, body).json()
    if owner_state == "alias":
        owner = profile_db.link_alias(owner["id"], email, 1)
    if owner_state == "deleted":
        profile_db.delete_profile(owner["id"], 1)
    before = profile_db.get_profile(owner["id"])
    duplicate = post_profile(client, created_profiles, {"display_name": "Replacement owner", "email": email.upper()})
    assert duplicate.status_code == 409
    assert profile_db.get_profile(owner["id"]) == before


def test_concurrent_email_creation_has_one_winner(created_profiles):
    email = "race-" + uuid4().hex + "@example.invalid"
    barrier = threading.Barrier(2)

    def create(name):
        barrier.wait(timeout=5)
        try:
            return profile_db.create_profile(name, email)
        except profile_db.ProfileRevisionConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(create, ("First person", "Second person")))
    winners = [profile for profile in outcomes if profile]
    assert len(winners) == 1
    created_profiles.append(winners[0]["id"])
    assert profile_db.get_profile(winners[0]["id"])["display_name"] == winners[0]["display_name"]
    assert profile_db.list_profiles(query=email)["total"] == 1


@pytest.mark.parametrize("body", [
    {}, {"display_name": ""}, {"display_name": " "}, {"display_name": None}, {"display_name": True},
    {"display_name": "x" * 201}, {"display_name": "Jordan", "email": ""}, {"display_name": "Jordan", "email": "not-an-email"},
    {"display_name": "Jordan", "email": True}, {"display_name": "Jordan", "email": "a" * 321},
    {"display_name": "Jordan", "unknown": "field"},
])
def test_create_validates_name_and_optional_email_at_http_boundary(client, body):
    assert client.post("/api/profiles", json=body).status_code == 422


def test_rename_is_revision_safe_and_preserves_identity_evidence_and_meeting_snapshot(client, applied, claimed):
    profile = applied[1]
    snapshot = copy.deepcopy(digestion_db.get_record(claimed[0]))
    path = f"/api/profiles/{profile['id']}"
    response = client.patch(path, json={"expected_revision": 1, "display_name": " Jordan Rivera ", "tags": ["People"], "starred": True})
    assert response.status_code == 200
    updated = response.json()
    assert updated["display_name"] == "Jordan Rivera" and updated["revision"] == 2
    assert updated["tags"] == ["People"] and updated["starred"]
    for key in ("id", "identity_key", "email", "identity_scope", "claims", "aliases", "merge_history", "created_at"):
        assert updated[key] == profile[key]
    assert digestion_db.get_record(claimed[0]) == snapshot
    assert client.patch(path, json={"expected_revision": 1, "display_name": "Stale name"}).status_code == 409
    noop = client.patch(path, json={"expected_revision": 2, "display_name": " Jordan Rivera "}).json()
    assert noop["revision"] == 2 and noop["updated_at"] == updated["updated_at"]
    for name in (None, "", " ", "x" * 201, True):
        assert client.patch(path, json={"expected_revision": 2, "display_name": name}).status_code == 422
    assert profile_db.get_profile(profile["id"])["display_name"] == "Jordan Rivera"


def test_renaming_through_an_old_alias_updates_only_the_canonical_name(client, created_profiles):
    source = post_profile(client, created_profiles, {"display_name": "Old identity"}).json()
    target = post_profile(client, created_profiles, {"display_name": "Current identity"}).json()
    merged = profile_db.merge_profiles(source["id"], target["id"], 1, 1)
    renamed = client.patch(f"/api/meetings/profiles/{source['id']}", json={"expected_revision": merged["revision"], "display_name": "Jordan Rivera"})
    assert renamed.status_code == 200 and renamed.json()["id"] == target["id"]
    assert renamed.json()["identity_scope"] == "manual" and renamed.json()["identity_key"] == target["identity_key"]
    assert renamed.json()["merge_history"] == merged["merge_history"] and renamed.json()["aliases"] == merged["aliases"]
    assert profile_db.get_profile(source["id"])["display_name"] == "Jordan Rivera"


def test_manual_profile_can_link_a_future_email_without_changing_its_identity(client, created_profiles):
    profile = post_profile(client, created_profiles, {"display_name": "Jordan Rivera"}).json()
    email = "future-" + uuid4().hex + "@example.invalid"
    linked = profile_db.link_alias(profile["id"], email, 1)
    assert linked["id"] == profile["id"] and linked["identity_key"] == profile["identity_key"]
    assert linked["identity_scope"] == "email" and linked["email"] == email
    raw = email_participant(email, "Future meeting name")
    raw["segment_ids"] = ["segment-0"]
    resolved = profile_db.resolve_participants([raw])
    assert resolved[0]["id"] == profile["id"] and resolved[0]["identity_key"] == profile["identity_key"]
    assert profile_db.load_profiles(resolved)[0]["id"] == profile["id"]


@pytest.mark.asyncio
async def test_name_only_profile_is_used_by_explicit_meeting_attribution_in_the_actual_graph(
    client, source, feed, agents, profile_agent, created_profiles,
):
    profile = post_profile(client, created_profiles, {"display_name": "Jordan Rivera"}).json()
    feed.summaries = {"manual-profile": note("manual-profile")}
    feed.segments = (TranscriptSegment("I prefer a verified owner for every task.", {"name": "Me", "source": "microphone"}),)
    await dispatch("meeting_ingest", {"source": source.name, "digest": False})
    meeting_id = db.list_summaries(source=source.name)["items"][0]["id"]
    captured = digestion_db.get_record(meeting_id)
    snapshot = copy.deepcopy(captured["snapshot"])
    management_db.update_participants(meeting_id, 0, [{
        "name": profile["display_name"], "profile_id": profile["id"],
        "speaker_key": speaker_key(captured["transcript"]["segments"][0]["speaker"]),
    }])
    await dispatch("meeting_ingest", {"source": source.name})
    result = json.loads(await dispatch("persona", {"source": source.name}))
    assert result["profiles"]["profile_ids"] == [profile["id"]]
    observed = profile_agent[0][-1]
    assert observed["participants"][0]["id"] == profile["id"] and observed["participants"][0]["identity_scope"] == "manual"
    assert profile_db.get_profile(profile["id"])["revision"] == 2
    assert profile_db.get_profile(profile["id"])["claims"][0]["evidence"][0]["quote"] == feed.segments[0].text
    assert digestion_db.get_record(meeting_id)["snapshot"] == snapshot
