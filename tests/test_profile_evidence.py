import copy
import json
from uuid import uuid4

import pytest
from psycopg2.extras import Json

from services.db import get_connection
from services.meetings import profile_db
from services.personas import sections
from tests.test_meeting_profiles_db import claimed as claimed, participants as participants
from tests.test_meeting_profiles_router import applied as applied
from tests.test_meeting_sync import source as source
from tests.test_profile_source_visibility import invalidate
from tests.test_profiles_router import browse_profiles as browse_profiles, client as client


@pytest.fixture
def proof_profile(applied):
    meeting_id, profile = applied
    claim = profile["claims"][0]
    source = {key: claim[key] for key in ("meeting_id", "transcript_hash", "participants_revision")}
    proof = {"human": False, "status": "supported", "claim_ids": [claim["id"]],
             "claim_signatures": {claim["id"]: sections.claim_signature(claim)}, "sources": [source],
             "coverage": {"claim_count": 1, "meeting_count": 1}, "generated_at": "2026-10-29T12:00:00+00:00"}
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("""UPDATE participant_profiles SET metadata=%s, metadata_provenance=%s,
            section_notes=%s, section_evidence=%s, merge_history=%s WHERE id=%s""", (
            Json({"company": "Example Labs"}), Json({"company": {**source, "evidence": claim["evidence"]}}),
            Json({"strengths": "Supported summary"}), Json({"strengths": proof, "drivers": {"human": True, "origin": "human"}}),
            Json([{"previous_target": {"section_notes": {"overview": "Private historical snapshot"}}}]), profile["id"],
        ))
    return meeting_id, profile


def test_compact_profile_keeps_current_narratives_and_counts_without_evidence_or_history(client, proof_profile):
    _, profile = proof_profile
    path = f"/api/profiles/{profile['id']}"
    full = client.get(path).json()
    compact = client.get(path, params={"include_evidence": False}).json()
    assert full["claims"] == profile["claims"] and full["merge_history"]
    assert compact["claims"] == [] and compact["evidence_loaded"] is False
    assert compact["claim_count"] == compact["meeting_count"] == 1
    assert compact["section_notes"] == {"strengths": "Supported summary"}
    assert compact["section_evidence"]["drivers"] == {"human": True, "claim_count": 0}
    proof = compact["section_evidence"]["strengths"]
    assert proof["claim_count"] == 1 and proof["status"] == "supported"
    assert not set(proof) & {"claim_ids", "claim_signatures", "sources"}
    assert compact["metadata_provenance"]["company"] == {
        "meeting_id": profile["claims"][0]["meeting_id"], "evidence": [], "evidence_count": len(profile["claims"][0]["evidence"]),
    }
    assert compact["relationships"][0]["claims"] == [] and compact["relationships"][0]["claim_count"] == 1
    assert "merge_history" not in compact and "identity_key" not in compact
    assert not any(key.startswith("assessment_") for key in compact)
    assert "Private historical snapshot" not in json.dumps(compact)
    assert profile["claims"][0]["evidence"][0]["quote"] not in json.dumps(compact)
    assert client.get(f"/api/meetings/profiles/{profile['id']}", params={"include_evidence": False}).json() == compact


@pytest.mark.parametrize("change", ["withdrawn", "deleted", "hash", "attribution"])
def test_compact_profile_and_paged_evidence_revalidate_source_without_profile_revision_change(client, proof_profile, change):
    meeting_id, profile = proof_profile
    invalidate(meeting_id, change)
    path = f"/api/profiles/{profile['id']}"
    compact = client.get(path, params={"include_evidence": False}).json()
    assert compact["revision"] == profile["revision"]
    assert compact["claim_count"] == compact["meeting_count"] == 0
    assert compact["metadata"] == compact["section_notes"] == {}
    assert compact["section_evidence"] == {"drivers": {"human": True, "claim_count": 0}}
    assert compact["relationships"] == []
    assert client.get(path + "/claims").json() == {
        "profile_id": profile["id"], "revision": profile["revision"], "items": [], "total": 0,
    }


def test_claim_feed_filters_before_pagination_and_keeps_human_corrections_and_rejections(client, applied, monkeypatch):
    _, profile = applied
    original = profile["claims"][0]
    claims = [{**copy.deepcopy(original), "id": str(uuid4()), "content": f"Observation {index}"} for index in range(6)]
    claims[0]["transcript_hash"] = "withdrawn-source-hash"
    claims[2]["superseded"] = True
    claims[3].update(status="rejected", correction={"action": "reject", "content": None, "reason": "Human rejection"})
    claims[4].update(status="corrected", correction={"action": "correct", "content": "Human correction", "reason": "Clarification"})
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE participant_profiles SET claims=%s WHERE id=%s", (Json(claims), profile["id"]))

    def full_read_forbidden(*args, **kwargs):
        raise AssertionError("The paginated feed must not load a complete profile")

    monkeypatch.setattr(profile_db, "get_profile", full_read_forbidden)
    monkeypatch.setattr(profile_db, "_canonical", full_read_forbidden)
    path = f"/api/profiles/{profile['id']}/claims"
    first = client.get(path, params={"limit": 2}).json()
    second = client.get(path, params={"limit": 2, "offset": 2}).json()
    assert first["total"] == second["total"] == 4
    assert first["profile_id"] == profile["id"] and first["revision"] == profile["revision"]
    assert [claim["id"] for claim in first["items"] + second["items"]] == [claims[index]["id"] for index in (1, 3, 4, 5)]
    assert first["items"][1]["correction"]["reason"] == "Human rejection"
    assert second["items"][0]["correction"]["content"] == "Human correction"
    assert client.get(path, params={"offset": 100}).json()["items"] == []


def test_compact_mutation_responses_preserve_saved_evidence_and_revision_safety(client, applied):
    _, profile = applied
    path = f"/api/profiles/{profile['id']}"
    response = client.patch(path, params={"include_evidence": False}, json={"expected_revision": 1, "starred": True})
    assert response.status_code == 200
    compact = response.json()
    assert compact["claims"] == [] and compact["claim_count"] == 1 and compact["revision"] == 2
    claim_path = path + "/claims/" + profile["claims"][0]["id"]
    rejected = client.post(claim_path, params={"include_evidence": False}, json={
        "expected_revision": 2, "action": "reject", "reason": "Human rejection",
    })
    assert rejected.status_code == 200 and rejected.json()["claims"] == []
    assert rejected.json()["claim_count"] == 1 and rejected.json()["assessment"]["coverage"]["claim_count"] == 0
    assert client.patch(path, params={"include_evidence": False}, json={"expected_revision": 1, "starred": False}).status_code == 409
    full = client.get(path).json()
    assert full["claims"][0]["status"] == "rejected" and full["claims"][0]["evidence"] == profile["claims"][0]["evidence"]
    edge = full["relationships"][0]
    edited = client.patch(path + "/relationships/" + edge["id"], params={"include_evidence": False},
                          json={"expected_revision": edge["revision"], "notes": "Human relationship"})
    assert edited.status_code == 200 and edited.json()["claims"] == [] and edited.json()["claim_count"] == 1


def test_compact_create_link_relationship_and_merge_responses_keep_history_on_full_read(client):
    ids = []
    params = {"include_evidence": False}
    try:
        profiles = []
        for name in ("First", "Second", "Third"):
            response = client.post("/api/profiles", params=params, json={"display_name": name})
            assert response.status_code == 201
            profile = response.json()
            profiles.append(profile)
            ids.append(profile["id"])
            assert profile["evidence_loaded"] is False and profile["claims"] == []
        first, second, third = profiles
        path = f"/api/profiles/{first['id']}"
        linked = client.post(path + "/aliases", params=params, json={
            "expected_revision": first["revision"], "email": f"alias-{uuid4().hex}@example.test",
        })
        assert linked.status_code == 200 and "merge_history" not in linked.json()
        edge = client.post(path + "/relationships", params=params, json={
            "expected_revision": linked.json()["revision"], "target_id": second["id"],
            "target_revision": second["revision"], "label": "Colleagues",
        })
        assert edge.status_code == 201 and edge.json()["claims"] == [] and edge.json()["claim_count"] == 0
        current = client.get(path, params=params).json()
        merged = client.post(path + "/merge", params=params, json={
            "expected_revision": current["revision"], "target_id": third["id"], "target_revision": third["revision"],
        })
        assert merged.status_code == 200 and merged.json()["id"] == third["id"]
        assert "merge_history" not in merged.json() and merged.json()["evidence_loaded"] is False
        assert merged.json()["relationships"][0]["label"] == "Colleagues"
        assert len(client.get(f"/api/profiles/{third['id']}").json()["merge_history"]) == 2
    finally:
        if ids:
            with get_connection() as connection, connection.cursor() as cursor:
                cursor.execute("DELETE FROM participant_profiles WHERE merged_into IN %s", (tuple(ids),))
                cursor.execute("DELETE FROM participant_profiles WHERE id IN %s", (tuple(ids),))


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"limit": "true"}, {"limit": 1.5}, {"offset": -1}, {"offset": 0.5}])
def test_claim_feed_rejects_invalid_http_pagination(client, params):
    assert client.get(f"/api/profiles/{uuid4()}/claims", params=params).status_code == 422


@pytest.mark.parametrize("params", [{"limit": True}, {"limit": 0}, {"limit": 101}, {"offset": False}, {"offset": -1}, {"offset": 0.5}])
def test_claim_feed_rejects_invalid_service_pagination(params):
    with pytest.raises(ValueError):
        profile_db.list_claims(str(uuid4()), **params)


def test_claim_feed_resolves_aliases_and_hides_deleted_profiles(client):
    source = profile_db.create_profile("Alias source")
    target = profile_db.create_profile("Canonical target")
    try:
        merged = profile_db.merge_profiles(source["id"], target["id"], 1, 1, include_evidence=False)
        path = f"/api/profiles/{source['id']}/claims"
        assert client.get(path).json() == {"profile_id": target["id"], "revision": merged["revision"], "items": [], "total": 0}
        assert client.get(f"/api/profiles/{source['id']}", params={"include_evidence": False}).json()["id"] == target["id"]
        profile_db.delete_profile(target["id"], merged["revision"])
        assert client.get(path).status_code == 404
        assert client.get(f"/api/profiles/{uuid4()}/claims").status_code == 404
        assert client.get("/api/profiles/not-a-uuid/claims").status_code == 422
    finally:
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM participant_profiles WHERE id=%s", (source["id"],))
            cursor.execute("DELETE FROM participant_profiles WHERE id=%s", (target["id"],))


def test_default_profile_order_stars_first_then_name_with_stable_ties_across_pages(client, browse_profiles):
    marker, rows = browse_profiles
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE participant_profiles SET starred=true, display_name=%s WHERE id IN %s",
                       ("Casey " + marker, (rows[2]["id"], rows[3]["id"])))
    expected = sorted((rows[2]["id"], rows[3]["id"])) + [rows[0]["id"], rows[1]["id"]]
    first = client.get("/api/profiles", params={"q": marker, "limit": 3}).json()
    second = client.get("/api/profiles", params={"q": marker, "limit": 3, "offset": 3}).json()
    assert first["total"] == second["total"] == 4
    assert [row["id"] for row in first["items"] + second["items"]] == expected
    assert [row["id"] for row in profile_db.list_profiles(query=marker)["items"]] == expected
