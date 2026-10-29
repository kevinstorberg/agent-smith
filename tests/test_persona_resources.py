from uuid import uuid4

import pytest

from services.db import get_connection
from services.meetings import digestion_db, profile_db, vocabulary_db
from tests.test_meeting_profiles_db import apply, candidate, claimed as claimed, participants as participants, ready_meeting
from tests.test_meeting_sync import source as source
from tests.test_profiles_router import client as client


@pytest.fixture
def people(client):
    ids = []

    def create(name="A person", email=None):
        response = client.post("/api/profiles", json={"display_name": name, **({"email": email} if email else {})})
        assert response.status_code == 201, response.text
        result = response.json()
        ids.append(result["id"])
        return result

    yield create
    if ids:
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM participant_profiles WHERE merged_into IN %s", (tuple(ids),))
            cursor.execute("DELETE FROM participant_profiles WHERE id IN %s", (tuple(ids),))


def save(client, profile, **values):
    response = client.patch(f"/api/profiles/{profile['id']}", json={"expected_revision": profile["revision"], **values})
    assert response.status_code == 200, response.text
    return response.json()


def relationship(client, subject, target, **values):
    subject, target = profile_db.get_profile(subject["id"]), profile_db.get_profile(target["id"])
    response = client.post(f"/api/profiles/{subject['id']}/relationships", json={
        "expected_revision": subject["revision"], "target_id": target["id"], "target_revision": target["revision"], **values,
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_optional_human_fields_are_partial_searchable_and_revision_checked(client, people):
    profile = people("Alex")
    assert profile["metadata"] == profile["section_notes"] == {}
    assert profile["nicknames"] == profile["emails"] == profile["relationships"] == []
    first = save(client, profile, metadata={"company": "Example Labs", "job_role": "Engineer", "gender": "Self-described", "start_date": "2024-02-29"},
                 nicknames=[" Lex ", "LEX", "Al"], section_notes={"drivers": "Values reliability", "strengths": "Clear communicator"})
    second = save(client, first, metadata={"marital_status": "Not specified", "supervisor": "A future contact", "other": "Human context"},
                  section_notes={"development_areas": "Delegate earlier"})
    assert second["metadata"]["company"] == "Example Labs"
    assert second["section_notes"] == {"drivers": "Values reliability", "strengths": "Clear communicator", "development_areas": "Delegate earlier"}
    assert second["nicknames"] == ["Lex", "Al"]
    assert client.get("/api/profiles", params={"q": " lex "}).json()["items"][0]["id"] == profile["id"]
    assert client.get("/api/profiles", params={"q": "example labs"}).json()["items"][0]["id"] == profile["id"]
    assert client.patch(f"/api/profiles/{profile['id']}", json={"expected_revision": first["revision"], "metadata": {"company": "Stale"}}).status_code == 409
    cleared = save(client, second, metadata={"gender": ""}, section_notes={"drivers": ""})
    assert "gender" not in cleared["metadata"] and "drivers" not in cleared["section_notes"]
    assert cleared["section_notes"]["strengths"] == "Clear communicator"


@pytest.mark.parametrize("values", [
    {"metadata": None}, {"metadata": {"unknown": "x"}}, {"metadata": {"start_date": "2024-02-30"}},
    {"metadata": {"start_date": "20240229"}}, {"metadata": {"company": True}},
    {"section_notes": {"unknown": "x"}}, {"section_notes": {"drivers": None}},
    {"nicknames": [""]}, {"nicknames": ["x" * 101]}, {"nicknames": [str(index) for index in range(21)]},
])
def test_human_fields_reject_invalid_values(client, people, values):
    profile = people()
    assert client.patch(f"/api/profiles/{profile['id']}", json={"expected_revision": 1, **values}).status_code == 422
    assert profile_db.get_profile(profile["id"])["revision"] == 1


def test_primary_and_linked_emails_match_without_case_sensitivity(client, people):
    marker = uuid4().hex
    profile = people(email=f" Alex-{marker}@Example.TEST ")
    assert profile["email"] == f"alex-{marker}@example.test"
    assert client.post("/api/profiles", json={"display_name": "Duplicate", "email": profile["email"].upper()}).status_code == 409
    path = f"/api/profiles/{profile['id']}/aliases"
    alias = f"Second-{marker}@EXAMPLE.TEST"
    linked = client.post(path, json={"expected_revision": profile["revision"], "email": alias}).json()
    assert sorted(linked["emails"]) == sorted([profile["email"], alias.casefold()])
    repeated = client.post(path, json={"expected_revision": linked["revision"], "email": alias.swapcase()})
    assert repeated.status_code == 200 and repeated.json()["revision"] == linked["revision"]
    assert client.get("/api/profiles", params={"q": alias.upper()}).json()["items"][0]["id"] == profile["id"]
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE participant_profiles SET email = upper(email) WHERE id = %s", (profile["id"],))
    assert client.post("/api/profiles", json={"display_name": "Legacy duplicate", "email": profile["email"]}).status_code == 409


def test_directed_relationships_have_independent_human_edits_and_dismissals(client, people):
    alex, blair = people("Alex"), people("Blair")
    forward = relationship(client, alex, blair, label="Reports to", notes="Values clear written expectations")
    reverse = relationship(client, blair, alex, label="Supervises", notes="Appreciates careful reviews")
    assert forward["id"] != reverse["id"]
    rows = profile_db.get_profile(alex["id"])["relationships"]
    assert {(item["subject_id"], item["target_id"]) for item in rows} == {(alex["id"], blair["id"]), (blair["id"], alex["id"])}
    path = f"/api/profiles/{alex['id']}/relationships/{forward['id']}"
    response = client.patch(path, json={"expected_revision": forward["revision"], "notes": "Human refinement"})
    assert response.status_code == 200
    assert response.json()["label"] == "Reports to" and response.json()["notes"] == "Human refinement"
    assert client.patch(path, json={"expected_revision": forward["revision"], "notes": "Stale"}).status_code == 409
    assert client.request("DELETE", path, json={"expected_revision": response.json()["revision"]}).status_code == 200
    assert [item["id"] for item in profile_db.get_profile(alex["id"])["relationships"]] == [reverse["id"]]
    loaded = profile_db.load_profiles([{"id": alex["id"], "identity_key": "manual:" + alex["id"], "display_name": "Alex", "email": None,
                                       "identity_scope": "manual", "segment_ids": []}])[0]
    assert any(item["id"] == forward["id"] and item["dismissed"] for item in loaded["relationships"])


def test_relationship_merge_preserves_selected_profile_and_human_context(client, people):
    first, second, third = people("First"), people("Second"), people("Third")
    relationship(client, first, third, label="Peer", notes="First context")
    relationship(client, second, third, label="Colleague", notes="Second context")
    first, second = profile_db.get_profile(first["id"]), profile_db.get_profile(second["id"])
    merged = profile_db.merge_profiles(first["id"], second["id"], first["revision"], second["revision"])
    assert merged["id"] == second["id"]
    assert profile_db.get_profile(first["id"])["id"] == second["id"]
    assert len(merged["relationships"]) == 1
    assert merged["relationships"][0]["notes"] == "Second context"
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT history FROM profile_relationships WHERE id=%s", (merged["relationships"][0]["id"],))
        assert "First context" in str(cursor.fetchone()[0])


def test_persona_updates_reuse_people_and_preserve_human_fields_and_relationship_notes(client, source, claimed, participants):
    apply(claimed, candidate(participants), participants)
    subject = profile_db.get_profile(participants[0]["id"])
    subject = save(client, subject, metadata={"company": "Human company"}, section_notes={"drivers": "Human priority"}, nicknames=["Alias"])
    edge = subject["relationships"][0]
    response = client.patch(f"/api/profiles/{subject['id']}/relationships/{edge['id']}", json={"expected_revision": edge["revision"], "notes": "Human relationship context"})
    assert response.status_code == 200
    digestion_db.release_profile_owner(claimed[1])
    meeting_id = ready_meeting(source, "next-persona-context")
    owner = "next-persona-owner"
    record = digestion_db.claim_profile(source.name, owner)
    assert record["meeting_id"] == meeting_id
    try:
        current = profile_db.load_profiles(participants)
        artifact = candidate(participants, {row["id"]: row["revision"] for row in current})
        artifact["items"][0].update(category="strength", content="Brings reliability to collaboration")
        profile_db.apply_profiles(meeting_id, owner, record["transcript_hash"], artifact, participants)
    finally:
        digestion_db.release_profile_owner(owner)
    updated = profile_db.get_profile(subject["id"])
    assert updated["id"] == subject["id"] and updated["metadata"] == {"company": "Human company"}
    assert updated["section_notes"] == {"drivers": "Human priority"} and updated["nicknames"] == ["Alias"]
    assert len(updated["claims"]) == 2
    assert updated["relationships"][0]["notes"] == "Human relationship context"
    assert len(updated["relationships"][0]["claims"]) == 2


@pytest.fixture
def vocabulary():
    ids = []

    def add(term, definition=""):
        item = vocabulary_db.create(term, definition)
        ids.append(item["id"])
        return item

    yield add
    if ids:
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM meeting_vocabulary WHERE id IN %s", (tuple(ids),))


def test_vocabulary_crud_matching_and_snapshot_value(client, vocabulary):
    term = "Special " + uuid4().hex
    item = vocabulary(term, "An internal product")
    assert client.get("/api/meetings/vocabulary").status_code == 200
    assert vocabulary_db.relevant(f"Discussed {term.upper()} today") == [{"term": term, "definition": "An internal product"}]
    assert vocabulary_db.relevant(f"Prefix{term}suffix") == []
    assert client.post("/api/meetings/vocabulary", json={"term": term.swapcase()}).status_code == 409
    path = f"/api/meetings/vocabulary/{item['id']}"
    updated = client.patch(path, json={"expected_revision": item["revision"], "term": term, "definition": "Updated meaning"})
    assert updated.status_code == 200
    assert client.patch(path, json={"expected_revision": item["revision"], "term": term}).status_code == 409
    assert client.request("DELETE", path, json={"expected_revision": updated.json()["revision"]}).status_code == 200
    assert vocabulary_db.relevant(term) == []


def test_vocabulary_context_budget_fails_before_model_work(vocabulary):
    terms = ["Phrase" + uuid4().hex for _ in range(9)]
    for term in terms:
        vocabulary(term, "x" * 2000)
    with pytest.raises(vocabulary_db.VocabularyContextTooLargeError):
        vocabulary_db.relevant(" ".join(terms))


def test_linked_people_are_context_targets_without_claiming_their_speech(client, people):
    alex, blair = people("Alex"), people("Blair")
    relationship(client, alex, blair, label="Works with")
    participants = [{
        "id": alex["id"], "identity_key": "manual:" + alex["id"], "display_name": "Alex",
        "email": None, "identity_scope": "manual", "segment_ids": ["segment-0"],
    }]
    catalog = profile_db.include_linked_profiles(participants)
    assert {item["id"] for item in catalog} == {alex["id"], blair["id"]}
    assert next(item for item in catalog if item["id"] == blair["id"])["segment_ids"] == []
    context = profile_db.load_profiles(catalog)
    assert all("claims" not in edge and "history" not in edge for profile in context for edge in profile["relationships"])


def test_automatic_relationships_hide_withdrawn_evidence_but_human_context_survives(client, claimed, participants):
    apply(claimed, candidate(participants), participants)
    subject = profile_db.get_profile(participants[0]["id"])
    assert subject["relationships"][0]["claim_count"] == 1
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE meeting_summaries SET available=false WHERE id=%s", (claimed[0],))
    assert profile_db.get_profile(subject["id"])["relationships"] == []
    target = profile_db.get_profile(participants[1]["id"])
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT id,revision FROM profile_relationships WHERE subject_id=%s AND target_id=%s", (subject["id"], target["id"]))
        edge_id, revision = cursor.fetchone()
    response = client.patch(f"/api/profiles/{subject['id']}/relationships/{edge_id}",
                            json={"expected_revision": revision, "notes": "Human-established context"})
    assert response.status_code == 200
    assert response.json()["claims"] == [] and response.json()["human_confirmed"] is True
    assert profile_db.get_profile(subject["id"])["relationships"][0]["notes"] == "Human-established context"
