import copy
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4, uuid5

import pytest
from psycopg2.extras import Json

from services.db import get_connection
from services.meetings import digestion_db, profile_db
from services.meetings.participants import email_participant
from tests.test_meeting_profiles_db import apply, candidate, claimed as claimed, participants as participants, ready_meeting
from tests.test_meeting_sync import STAMP, source as source
from tests.test_profiles_router import client as client


@pytest.fixture
def pair(claimed, participants):
    artifact = candidate(participants)
    artifact["items"][0]["target_id"] = None
    reverse = {**copy.deepcopy(artifact["items"][0]), "subject_id": participants[1]["id"],
               "content": "Values direct communication", "evidence": [{"segment_id": "segment-1", "quote": "I value direct communication"}]}
    artifact["items"].append(reverse)
    apply(claimed, artifact, participants)
    yield tuple(profile_db.get_profile(person["id"]) for person in participants)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM participant_profiles WHERE merged_into IN %s", (tuple(person["id"] for person in participants),))


@pytest.fixture
def extra_profiles():
    ids = []

    def create(name="A meeting speaker", email=None):
        identity = email_participant(email, name) if email else {
            "id": str(uuid4()), "identity_key": "meeting:" + uuid4().hex,
            "display_name": name, "email": None, "identity_scope": "meeting", "segment_ids": [],
        }
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO participant_profiles (id, identity_key, display_name, email, identity_scope)
                           VALUES (%s, %s, %s, %s, %s)""",
                        tuple(identity[key] for key in ("id", "identity_key", "display_name", "email", "identity_scope")))
        ids.append(identity["id"])
        return profile_db.get_profile(identity["id"])

    yield create
    if ids:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM participant_profiles WHERE merged_into IN %s", (tuple(ids),))
            cur.execute("DELETE FROM participant_profiles WHERE id IN %s", (tuple(ids),))


def test_metadata_is_revision_safe_normalized_and_available_through_both_routes(client, pair):
    profile = pair[0]
    path = f"/api/profiles/{profile['id']}"
    response = client.patch(path, json={"expected_revision": 1, "tags": [" Team ", "Team", "Priority"], "starred": True})
    assert response.status_code == 200
    updated = response.json()
    assert updated["tags"] == ["Team", "Priority"] and updated["starred"] and updated["revision"] == 2
    assert updated["claims"] == profile["claims"] and updated["created_at"] == profile["created_at"]
    assert client.patch(path, json={"expected_revision": 1, "starred": False}).status_code == 409
    cleared = client.patch(f"/api/meetings/profiles/{profile['id']}", json={"expected_revision": 2, "tags": [], "starred": False})
    assert cleared.status_code == 200 and cleared.json()["revision"] == 3
    assert cleared.json()["tags"] == [] and not cleared.json()["starred"]
    assert client.patch(path, json={"expected_revision": 3, "tags": [], "starred": False}).json()["revision"] == 3


@pytest.mark.parametrize("metadata", [
    {}, {"tags": None}, {"starred": None}, {"starred": "true"}, {"starred": 1},
    {"tags": [" "]}, {"tags": ["x" * 101]}, {"tags": [str(index) for index in range(21)]}, {"tags": [1]},
    {"tags": [], "unrecognized": True},
])
def test_metadata_rejects_invalid_or_null_fields_without_changes(client, pair, metadata):
    profile = pair[0]
    response = client.patch(f"/api/profiles/{profile['id']}", json={"expected_revision": 1, **metadata})
    assert response.status_code == 422
    assert profile_db.get_profile(profile["id"])["revision"] == 1


@pytest.mark.parametrize("sort,first", [("name_asc", 0), ("name_desc", 1), ("created_at_asc", 0), ("created_at_desc", 1), ("updated_at_asc", 1), ("updated_at_desc", 0)])
def test_list_filters_tags_and_starred_with_whitelisted_sorts(client, pair, sort, first):
    marker = "management-" + uuid4().hex
    for index, row in enumerate(pair):
        profile_db.update_metadata(row["id"], 1, tags=[marker, f"tag-{index}"], starred=index == 0)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE participant_profiles SET created_at = %s + interval '1 day', updated_at = %s + interval '3 days' WHERE id = %s", (STAMP, STAMP, pair[0]["id"]))
        cur.execute("UPDATE participant_profiles SET created_at = %s + interval '2 days', updated_at = %s + interval '1 day' WHERE id = %s", (STAMP, STAMP, pair[1]["id"]))
    listed = client.get("/api/profiles", params={"tags": [marker], "sort": sort}).json()
    assert listed["total"] == 2 and listed["items"][0]["id"] == pair[first]["id"]
    assert all("claims" not in row for row in listed["items"])
    assert client.get("/api/profiles", params={"tags": [marker, "tag-0"]}).json()["total"] == 1
    assert client.get("/api/profiles", params={"tags": [marker], "starred": True}).json()["items"][0]["id"] == pair[0]["id"]
    assert client.get("/api/profiles", params={"tags": [marker], "starred": False}).json()["items"][0]["id"] == pair[1]["id"]
    assert client.get("/api/profiles", params={"sort": "name_desc; DROP TABLE participant_profiles"}).status_code == 422


def test_agent_appending_claims_preserves_user_tags_and_stars(source, claimed, participants, pair):
    profile_db.update_metadata(pair[0]["id"], 1, tags=["User tag"], starred=True)
    digestion_db.release(claimed[0], claimed[1])
    meeting_id = ready_meeting(source, "second")
    owner = "profile-management-append"
    digestion_db.claim_digestion([(source.provider, source.account_key)], owner)
    try:
        record = digestion_db.get_record(meeting_id)
        apply((meeting_id, owner, record["transcript_hash"]), candidate(participants, {
            participants[0]["id"]: 2, participants[1]["id"]: 1,
        }), participants)
    finally:
        digestion_db.release(meeting_id, owner)
    updated = profile_db.get_profile(pair[0]["id"])
    assert updated["revision"] == 3 and len(updated["claims"]) == 2
    assert updated["tags"] == ["User tag"] and updated["starred"]


def test_merge_retains_claims_overrides_metadata_history_and_old_links(client, claimed, pair):
    source, target = pair
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE participant_profiles SET display_name = %s WHERE id = %s", ("Alice Smith " + uuid4().hex, source["id"]))
    source = profile_db.correct_claim(source["id"], source["claims"][0]["id"], 1, "correct", "A nuanced priority", "Participant clarification")
    source = profile_db.update_metadata(source["id"], source["revision"], tags=["Source"], starred=True)
    source = profile_db.link_alias(source["id"], "linked-" + uuid4().hex + "@example.test", source["revision"])
    target = profile_db.update_metadata(target["id"], 1, tags=["Target"])
    before_claims = {claim["id"]: claim for row in (source, target) for claim in row["claims"]}
    response = client.post(f"/api/profiles/{source['id']}/merge", json={
        "target_id": target["id"], "expected_revision": source["revision"], "target_revision": target["revision"],
    })
    assert response.status_code == 200
    winner = response.json()
    assert winner["id"] == target["id"] and winner["display_name"] == target["display_name"]
    assert winner["revision"] == max(source["revision"], target["revision"]) + 1
    assert winner["tags"] == ["Target", "Source"] and winner["starred"]
    assert {claim["id"]: claim for claim in winner["claims"]} == before_claims
    assert {alias["id"] for alias in winner["aliases"]} == {source["id"], source["aliases"][0]["id"]}
    for alias in winner["aliases"]:
        assert client.get(f"/api/profiles/{alias['id']}").json()["id"] == winner["id"]
        assert client.get(f"/api/meetings/profiles/{alias['id']}").json()["id"] == winner["id"]
    event = winner["merge_history"][-1]
    assert event["action"] == "merge" and event["source_revision"] == source["revision"]
    assert event["moved_claim_ids"] == [source["claims"][0]["id"]]
    assert event["previous_source"]["tags"] == ["Source"] and event["previous_target"]["tags"] == ["Target"]
    assert profile_db.meeting_profiles(claimed[0])["items"] == [{key: winner[key] for key in ("id", "display_name", "email", "revision")}]
    found = client.get("/api/profiles", params={"q": source["aliases"][0]["email"]}).json()
    assert found["total"] == 1 and found["items"][0]["id"] == winner["id"]
    by_previous_name = client.get("/api/profiles", params={"q": source["display_name"]}).json()
    assert by_previous_name["total"] == 1 and by_previous_name["items"][0]["id"] == winner["id"]
    stale = client.patch(f"/api/profiles/{source['id']}", json={"expected_revision": source["revision"], "starred": False})
    assert stale.status_code == 409


def test_merging_an_existing_winner_flattens_aliases_and_promotes_reliable_email(pair, extra_profiles):
    first, second = pair
    combined = profile_db.merge_profiles(first["id"], second["id"], 1, 1)
    destination = extra_profiles()
    winner = profile_db.merge_profiles(combined["id"], destination["id"], combined["revision"], 1)
    assert winner["id"] == destination["id"] and winner["email"] == second["email"]
    assert winner["identity_scope"] == "email" and winner["display_name"] == destination["display_name"]
    assert {alias["id"] for alias in winner["aliases"]} == {first["id"], second["id"]}
    assert all(profile_db.get_profile(row["id"])["id"] == winner["id"] for row in pair)


def test_explicit_email_link_resolves_future_speakers_and_cannot_steal_or_restore(client, pair):
    source, other = pair
    email = "future-" + uuid4().hex + "@example.test"
    linked = client.post(f"/api/profiles/{source['id']}/aliases", json={"email": " " + email.upper() + " ", "expected_revision": 1})
    assert linked.status_code == 200
    canonical = linked.json()
    assert canonical["revision"] == 2 and canonical["aliases"][0]["email"] == email
    raw = email_participant(email, "A later speaker")
    raw["segment_ids"] = ["segment-9", "segment-9"]
    selected = {"id": source["id"], "identity_key": "profile:" + source["id"], "display_name": "Human selected", "email": None, "identity_scope": "meeting", "segment_ids": ["segment-10"]}
    resolved = profile_db.resolve_participants([raw, selected])
    assert len(resolved) == 1 and resolved[0]["id"] == source["id"]
    assert resolved[0]["segment_ids"] == ["segment-9", "segment-10"]
    with pytest.raises(profile_db.ProfileRevisionConflict):
        profile_db.load_profiles([raw])
    assert profile_db.link_alias(source["id"], email, 2)["revision"] == 2
    conflict = client.post(f"/api/profiles/{source['id']}/aliases", json={"email": other["email"], "expected_revision": 2})
    assert conflict.status_code == 409 and "merge" in conflict.json()["detail"]
    profile_db.delete_profile(other["id"], 1)
    assert client.post(f"/api/profiles/{source['id']}/aliases", json={"email": other["email"], "expected_revision": 2}).status_code == 409
    profile_db.delete_profile(source["id"], 2)
    assert profile_db.get_profile(raw["id"]) is None
    assert profile_db.load_profiles(profile_db.resolve_participants([raw]))[0]["deleted"]
    unknown = {**selected, "id": str(uuid4()), "identity_key": "profile:" + str(uuid4())}
    with pytest.raises(profile_db.ProfileRevisionConflict):
        profile_db.resolve_participants([unknown])


@pytest.mark.parametrize("overflow", ["tags", "claims", "divergent_id"])
def test_merge_validation_rolls_back_every_row(pair, overflow):
    source, target = pair
    if overflow == "tags":
        source = profile_db.update_metadata(source["id"], 1, tags=[f"source-{index}" for index in range(11)])
        target = profile_db.update_metadata(target["id"], 1, tags=[f"target-{index}" for index in range(10)])
    else:
        for index, row in enumerate((source, target)):
            claims = copy.deepcopy(row["claims"])
            if overflow == "claims":
                claims[0]["content"] = "private historical evidence " * 45_000
            elif index:
                claims[0]["id"] = source["claims"][0]["id"]
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute("UPDATE participant_profiles SET claims = %s WHERE id = %s", (Json(claims), row["id"]))
        source, target = (profile_db.get_profile(row["id"]) for row in pair)
    with pytest.raises((ValueError, profile_db.ProfileRevisionConflict)) as failed:
        profile_db.merge_profiles(source["id"], target["id"], source["revision"], target["revision"])
    assert "private historical" not in str(failed.value)
    assert profile_db.get_profile(source["id"]) == source
    assert profile_db.get_profile(target["id"]) == target


def test_concurrent_opposite_merges_have_one_winner_and_no_cycle(pair):
    barrier = threading.Barrier(2)

    def merge(rows):
        barrier.wait(timeout=5)
        try:
            return profile_db.merge_profiles(rows[0]["id"], rows[1]["id"], 1, 1)["id"]
        except profile_db.ProfileRevisionConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(merge, (pair, tuple(reversed(pair)))))
    winners = [winner for winner in outcomes if winner]
    assert len(winners) == 1
    assert all(profile_db.get_profile(row["id"])["id"] == winners[0] for row in pair)


def test_busy_profile_writer_returns_safe_conflict_and_rolls_back_before_retry(client, pair):
    acquired, release = threading.Event(), threading.Event()

    def hold_writer():
        with profile_db.profile_write_cursor():
            acquired.set()
            assert release.wait(15), "Test did not release the profile writer"

    with ThreadPoolExecutor(max_workers=1) as executor:
        holder = executor.submit(hold_writer)
        try:
            assert acquired.wait(5)
            response = client.patch(f"/api/profiles/{pair[0]['id']}", json={"expected_revision": 1, "starred": True})
            assert response.status_code == 409 and response.json()["detail"] == "Profiles are busy; try again."
            assert profile_db.get_profile(pair[0]["id"])["revision"] == 1
        finally:
            release.set()
            holder.result(timeout=5)
    retried = client.patch(f"/api/profiles/{pair[0]['id']}", json={"expected_revision": 1, "starred": True})
    assert retried.status_code == 200 and retried.json()["revision"] == 2


def test_reanalysis_reuses_legacy_claim_identity_and_reactivates_correction_through_aliases(source, claimed, participants, pair):
    original = pair[0]
    legacy_id = str(uuid5(profile_db._CLAIM_NAMESPACE, f"{claimed[0]}:0"))
    claims = copy.deepcopy(original["claims"])
    claims[0]["id"] = legacy_id
    claims[0]["evidence"].append({"segment_id": "segment-0", "quote": "prioritize reliability"})
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE participant_profiles SET claims = %s WHERE id = %s", (Json(claims), original["id"]))
    corrected = profile_db.correct_claim(original["id"], legacy_id, 1, "correct", "User clarified priority", "Explicit correction")
    with profile_db.profile_write_cursor() as cur:
        stored = profile_db.canonical_rows(cur, [original["id"]])[original["id"]]
        retired = copy.deepcopy(stored["claims"])
        retired[0]["superseded"] = True
        cur.execute("UPDATE participant_profiles SET claims = %s WHERE id = %s", (Json(retired), original["id"]))
    assert profile_db.get_profile(original["id"])["claims"] == []
    summary = profile_db.list_profiles(query=original["email"])["items"][0]
    assert summary["claim_count"] == summary["meeting_count"] == 0
    internal = profile_db.load_profiles([participants[0]])[0]["claims"][0]
    assert internal["superseded"] and internal["evidence"] == [] and internal["correction"]
    winner = profile_db.merge_profiles(original["id"], pair[1]["id"], 2, 1)
    resolved = profile_db.resolve_participants(participants)
    assert len(resolved) == 1
    digestion_db.release(claimed[0], claimed[1])

    def reprocess(expected_revision):
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("UPDATE meeting_digestions SET profile_status = 'pending', profile_artifact = '{}'::jsonb WHERE meeting_id = %s", (claimed[0],))
        owner = "natural-profile-replay"
        digestion_db.claim_digestion([(source.provider, source.account_key)], owner)
        item = candidate(participants)["items"][0]
        item.update(subject_id=winner["id"], target_id=None, confidence="high", rationale="A later analysis of the same fact")
        item["evidence"] = list(reversed(claims[0]["evidence"]))
        artifact = {"expected_revisions": {winner["id"]: expected_revision}, "items": [item, copy.deepcopy(item)]}
        try:
            profile_db.apply_profiles(claimed[0], owner, claimed[2], artifact, resolved)
        finally:
            digestion_db.release(claimed[0], owner)

    reprocess(winner["revision"])
    current = profile_db.get_profile(winner["id"])
    assert len(current["claims"]) == 2
    restored = next(claim for claim in current["claims"] if claim["id"] == legacy_id)
    assert restored["superseded"] is False and restored["correction"] == corrected["claims"][0]["correction"]
    assert restored["corrections"] == corrected["claims"][0]["corrections"]
    assert restored["confidence"] == corrected["claims"][0]["confidence"]
    reprocess(current["revision"])
    assert profile_db.get_profile(winner["id"])["revision"] == current["revision"]
    assert len(profile_db.get_profile(winner["id"])["claims"]) == 2
