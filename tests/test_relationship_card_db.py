from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg2.errors import LockNotAvailable
from psycopg2.extras import Json

from services.api.routers.profiles import router
from services.db import get_connection
from services.meetings import profile_db, relationship_card_db as db, relationship_db
from services.personas import assessment, assessment_db, sections
from tests.test_meeting_profiles_db import claimed as claimed, participants as participants
from tests.test_meeting_sync import source as source
from tests.test_persona_assessments import observed as observed
from tests.test_profile_source_visibility import invalidate


@pytest.fixture
def people():
    suffix = uuid4().hex
    rows = [profile_db.create_profile(f"{name} {suffix}") for name in ("CardOwner", "CardJordan", "CardCasey")]
    yield rows
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM participant_profiles WHERE id IN %s", (tuple(row["id"] for row in rows),))


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/api/profiles")
    return TestClient(app)


def legacy(owner, text, proof=None):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE participant_profiles SET section_notes=%s,section_evidence=%s WHERE id=%s", (
            Json({"relationships": text}), Json({"relationships": proof or {"human": True}}), owner["id"]))
    return profile_db.get_profile(owner["id"])


def one(row):
    assert len(row["relationship_cards"]) == 1
    return row["relationship_cards"][0]


def test_relationship_card_legacy_edit_is_structured_and_keeps_original_prose_and_other_person(people):
    owner, jordan, casey = people
    text = f"{owner['display_name']} → {jordan['display_name']}: Saved Jordan analysis.\n\n{owner['display_name']} → {casey['display_name']}: Saved Casey analysis."
    current = legacy(owner, text)
    card = next(card for card in current["relationship_cards"] if card["profile_id"] == jordan["id"])
    changed = db.update(owner["id"], card["id"], card["version"], notes="My individual update.")
    assert changed["section_notes"]["relationships"] == text
    assert [(card["name"], card["notes"]) for card in changed["relationship_cards"]] == [
        (casey["display_name"], "Saved Casey analysis."), (jordan["display_name"], "My individual update.")]
    assert next(card for card in changed["relationship_cards"] if card["profile_id"] == jordan["id"])["human"]
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT history FROM profile_relationships WHERE subject_id=%s AND target_id=%s", (owner["id"], jordan["id"]))
        assert any(entry["action"] == "legacy_import" for entry in cur.fetchone()[0])


def test_relationship_card_named_creation_rename_link_unlink_clear_and_delete(people):
    owner, jordan, _ = people
    created = db.create(owner["id"], owner["revision"], "Untracked person", notes="A useful relationship assessment.")
    card = one(created)
    assert card["profile_id"] is None and card["human"]
    renamed = db.update(owner["id"], card["id"], card["version"], name="Known person")
    card = one(renamed)
    assert card["name"] == "Known person"
    linked = db.update(owner["id"], card["id"], card["version"], profile_id_target=jordan["id"], target_revision=jordan["revision"])
    card = one(linked)
    assert card["profile_id"] == jordan["id"]
    assert card["notes"] == "A useful relationship assessment."
    unlinked = db.update(owner["id"], card["id"], card["version"], profile_id_target=None, name="Named again")
    card = one(unlinked)
    cleared = db.update(owner["id"], card["id"], card["version"], notes="")
    assert one(cleared)["notes"] == "" and one(cleared)["human"]
    db.delete(owner["id"], one(cleared)["id"], one(cleared)["version"])
    assert profile_db.get_profile(owner["id"])["relationship_cards"] == []
    assert profile_db.get_profile(jordan["id"])["relationship_cards"] == []


def test_relationship_card_edit_of_incoming_preserves_other_persons_human_notes(people):
    owner, jordan, _ = people
    incoming = relationship_db.create(jordan["id"], owner["id"], jordan["revision"], owner["revision"], notes="Jordan’s protected assessment.")
    current = profile_db.get_profile(owner["id"])
    card = one(current)
    changed = db.update(owner["id"], card["id"], card["version"], notes="Owner’s new assessment.")
    assert one(changed)["notes"] == "Owner’s new assessment."
    assert one(profile_db.get_profile(jordan["id"]))["notes"] == "Jordan’s protected assessment."
    db.delete(owner["id"], one(changed)["id"], one(changed)["version"])
    assert profile_db.get_profile(owner["id"])["relationship_cards"] == []
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT notes,dismissed FROM profile_relationships WHERE id=%s", (incoming["id"],))
        assert cur.fetchone() == ("Jordan’s protected assessment.", True)


def test_relationship_card_removal_keeps_receipts_after_legacy_only_conversion(people):
    owner, jordan, _ = people
    text = f"{owner['display_name']} → {jordan['display_name']}: Existing relationship analysis."
    current = legacy(owner, text)
    card = one(current)
    db.delete(owner["id"], card["id"], card["version"])
    current = profile_db.get_profile(owner["id"])
    assert current["section_notes"]["relationships"] == text
    assert current["relationship_cards"] == []


def test_relationship_card_unstructured_assignment_copies_into_a_named_row_without_losing_input(people):
    owner, _, _ = people
    text = "An existing assessment that does not have a safe person boundary."
    current = legacy(owner, text)
    assert current["relationship_cards"] == []
    assigned = db.create(owner["id"], current["revision"], "Explicitly chosen person",
                         assignment_version=current["relationship_unassigned"]["version"])
    assert one(assigned)["notes"] == text
    assert assigned["relationship_unassigned"] is None
    assert assigned["section_notes"]["relationships"] == text


def test_relationship_card_versions_target_revisions_and_atomic_rollback(people, monkeypatch):
    owner, jordan, _ = people
    current = db.create(owner["id"], owner["revision"], "Named person", notes="Initial assessment.")
    card = one(current)
    with pytest.raises(profile_db.ProfileRevisionConflict):
        db.update(owner["id"], card["id"], card["version"], profile_id_target=jordan["id"], target_revision=999)
    original = relationship_db._touch_profiles
    def failed(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Receipt failed")
    monkeypatch.setattr(relationship_db, "_touch_profiles", failed)
    with pytest.raises(RuntimeError, match="Receipt failed"):
        db.update(owner["id"], card["id"], card["version"], notes="Must roll back.")
    assert one(profile_db.get_profile(owner["id"])) == card
    monkeypatch.setattr(relationship_db, "_touch_profiles", original)
    changed = db.update(owner["id"], card["id"], card["version"], notes="Changed.")
    with pytest.raises(profile_db.ProfileRevisionConflict):
        db.update(owner["id"], card["id"], card["version"], notes="Stale edit.")
    assert one(changed)["notes"] == "Changed."


def test_relationship_card_source_validated_copy_stays_generated_and_hides_withdrawn_evidence(observed):
    owner = observed
    target = owner["relationships"][0]
    claims = owner["claims"]
    proof = {"human": False, "status": "supported", "generated_at": "2026-10-30T00:00:00+00:00",
             "claim_ids": [claim["id"] for claim in claims], "claim_signatures": {claim["id"]: sections.claim_signature(claim) for claim in claims},
             "sources": [{key: claims[0][key] for key in ("meeting_id", "transcript_hash", "participants_revision")}],
             "coverage": {"claim_count": len(claims), "meeting_count": 1}}
    current = legacy(owner, f"{owner['display_name']} → {target['target_name']}: Source-backed prior analysis.", proof)
    card = one(current)
    changed = db.update(owner["id"], card["id"], card["version"], label="Colleague")
    assert one(changed)["notes"] == "Source-backed prior analysis."
    assert not one(changed)["human"]
    invalidate(claims[0]["meeting_id"], "withdrawn")
    withdrawn = profile_db.get_profile(owner["id"])
    assert one(withdrawn)["notes"] == "" and one(withdrawn)["status"] == "stale"
    stale_version = one(withdrawn)["version"]
    invalidate(claims[0]["meeting_id"], "hash")
    assert one(profile_db.get_profile(owner["id"]))["version"] != stale_version
    with pytest.raises(profile_db.ProfileRevisionConflict):
        db.update(owner["id"], card["id"], one(changed)["version"], notes="Must not copy withdrawn context.")


def test_relationship_card_converted_release_keeps_text_and_allows_only_that_linked_target(people):
    owner, jordan, _ = people
    current = legacy(owner, f"{owner['display_name']} → {jordan['display_name']}: Protected legacy analysis.")
    released = db.update(owner["id"], one(current)["id"], one(current)["version"], allow_agent_notes=True)
    assert one(released)["notes"] == "Protected legacy analysis."
    assert not one(released)["human"]
    snapshot = assessment_db.claim("converted-release", owner["id"])
    assert [edge["target_id"] for edge in assessment.editable_relationships(snapshot["profile"])] == [jordan["id"]]
    assessment_db.release_owner("converted-release")
    unlinked = db.create(owner["id"], released["revision"], "Unlinked", notes="Named-only context.")
    snapshot = assessment_db.claim("named-exclusion", owner["id"])
    assert all(edge["target_id"] is not None for edge in assessment.editable_relationships(snapshot["profile"]))
    assert len(unlinked["relationship_cards"]) == 2
    assessment_db.release_owner("named-exclusion")


def test_relationship_card_rest_boundary_reads_edits_clears_and_deletes_the_same_resource(client, people):
    owner, jordan, _ = people
    base = f"/api/profiles/{owner['id']}"
    response = client.post(base + "/relationship-cards", json={"expected_revision": owner["revision"], "name": jordan["display_name"],
        "profile_id": jordan["id"], "target_revision": jordan["revision"], "notes": "Shared resource."})
    assert response.status_code == 201, response.text
    card = one(response.json())
    path = base + "/relationship-cards/" + card["id"]
    assert one(client.get(base, params={"include_evidence": False}).json()) == card
    for payload in ({"version": card["version"], "notes": None}, {"version": card["version"], "revision": 2}, {"version": "bad", "notes": "No"}):
        assert client.patch(path, json=payload).status_code == 422
    changed = client.patch(path, json={"version": card["version"], "notes": ""})
    assert changed.status_code == 200 and one(changed.json())["notes"] == ""
    assert client.patch(path, json={"version": card["version"], "notes": "Stale"}).status_code == 409
    assert client.request("DELETE", path, json={"version": one(changed.json())["version"]}).status_code == 200
    assert client.get(base).json()["relationship_cards"] == []


def test_relationship_card_mutation_holds_source_fence_through_history_commit(observed, monkeypatch):
    owner = observed
    target = owner["relationships"][0]
    current = legacy(owner, f"{owner['display_name']} → {target['target_name']}: Protected existing analysis.")
    entered, resume = threading.Event(), threading.Event()
    original = db._write
    def paused(*args, **kwargs):
        entered.set()
        assert resume.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(db, "_write", paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        saving = pool.submit(db.update, owner["id"], one(current)["id"], one(current)["version"], notes="An explicit edit.")
        assert entered.wait(5)
        try:
            with pytest.raises(LockNotAvailable):
                with get_connection() as conn, conn.cursor() as cur:
                    cur.execute("SET LOCAL lock_timeout='100ms'")
                    cur.execute("UPDATE meeting_summaries SET available=false WHERE id=%s", (owner["claims"][0]["meeting_id"],))
        finally:
            resume.set()
        assert one(saving.result(timeout=5))["notes"] == "An explicit edit."


def test_relationship_card_can_be_explicitly_readded_after_both_directions_were_removed(people):
    owner, jordan, _ = people
    relationship_db.create(jordan["id"], owner["id"], jordan["revision"], owner["revision"], notes="A protected reverse perspective.")
    current = profile_db.get_profile(owner["id"])
    db.delete(owner["id"], one(current)["id"], one(current)["version"])
    owner = profile_db.get_profile(owner["id"])
    jordan = profile_db.get_profile(jordan["id"])
    created = db.create(owner["id"], owner["revision"], jordan["display_name"], profile_id_target=jordan["id"],
                        target_revision=jordan["revision"], notes="An explicit new relationship.")
    assert one(created)["notes"] == "An explicit new relationship."


def test_relationship_card_link_reconciles_an_existing_target_without_duplicate_cards(people):
    owner, jordan, _ = people
    linked = db.create(owner["id"], owner["revision"], jordan["display_name"], profile_id_target=jordan["id"],
                       target_revision=jordan["revision"], notes="Earlier linked context.")
    current = db.create(owner["id"], linked["revision"], "Named person", notes="The selected named assessment.")
    selected = next(card for card in current["relationship_cards"] if card["profile_id"] is None)
    jordan = profile_db.get_profile(jordan["id"])
    linked = db.update(owner["id"], selected["id"], selected["version"], profile_id_target=jordan["id"], target_revision=jordan["revision"])
    assert one(linked)["notes"] == "The selected named assessment."
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT history FROM profile_relationships WHERE subject_id=%s AND target_id=%s", (owner["id"], jordan["id"]))
        assert "Earlier linked context." in str(cur.fetchone()[0])


def test_relationship_card_label_only_edit_preserves_released_human_ownership(people):
    owner, jordan, _ = people
    current = legacy(owner, f"{owner['display_name']} → {jordan['display_name']}: Protected legacy analysis.")
    current = db.update(owner["id"], one(current)["id"], one(current)["version"], allow_agent_notes=True)
    updated = db.update(owner["id"], one(current)["id"], one(current)["version"], label="Collaborator")
    assert one(updated)["notes"] == "Protected legacy analysis."
    assert not one(updated)["human"]


def test_relationship_card_import_receipts_survive_profile_merge_and_current_generation(people):
    owner, jordan, casey = people
    text = f"{owner['display_name']} → {jordan['display_name']}: Imported old analysis."
    current = legacy(owner, text)
    edited = db.update(owner["id"], one(current)["id"], one(current)["version"], notes="The retained individual analysis.")
    merged = profile_db.merge_profiles(owner["id"], casey["id"], edited["revision"], casey["revision"])
    assert one(merged)["notes"] == "The retained individual analysis."
    assert merged["relationship_unassigned"] is None
    card = one(merged)
    db.delete(merged["id"], card["id"], card["version"])
    assert profile_db.get_profile(merged["id"])["relationship_cards"] == []


def test_relationship_card_named_relationships_survive_merge_and_stay_out_of_model_targets(people):
    owner, _, casey = people
    current = db.create(owner["id"], owner["revision"], "No profile yet", notes="Named context.")
    merged = profile_db.merge_profiles(owner["id"], casey["id"], current["revision"], casey["revision"])
    assert one(merged)["profile_id"] is None and one(merged)["notes"] == "Named context."
    snapshot = assessment_db.claim("named-after-merge", merged["id"])
    assert assessment.editable_relationships(snapshot["profile"]) == []
    assessment_db.release_owner("named-after-merge")


def test_relationship_card_later_global_clear_requires_a_new_explicit_card_edit(people):
    owner, jordan, _ = people
    current = db.create(owner["id"], owner["revision"], jordan["display_name"], profile_id_target=jordan["id"],
                        target_revision=jordan["revision"], notes="An earlier individual assessment.")
    cleared = profile_db.update_metadata(owner["id"], current["revision"], section_notes={"relationships": ""})
    assert one(cleared)["notes"] == ""
    updated = db.update(owner["id"], one(cleared)["id"], one(cleared)["version"], notes="A new explicit individual assessment.")
    assert one(updated)["notes"] == "A new explicit individual assessment."


def test_relationship_card_legacy_target_alias_is_one_linked_card_after_target_merge(people):
    owner, jordan, casey = people
    current = legacy(owner, f"{owner['display_name']} → {jordan['display_name']}: Existing relationship analysis.")
    relationship_db.create(owner["id"], jordan["id"], current["revision"], jordan["revision"])
    jordan = profile_db.get_profile(jordan["id"])
    profile_db.merge_profiles(jordan["id"], casey["id"], jordan["revision"], casey["revision"])
    card = one(profile_db.get_profile(owner["id"]))
    assert card["profile_id"] == casey["id"] and card["notes"] == "Existing relationship analysis."


@pytest.mark.parametrize("named", [False, True])
@pytest.mark.parametrize("merge_owner", [False, True])
def test_relationship_card_released_human_text_survives_owner_and_target_merges(people, named, merge_owner):
    owner, jordan, casey = people
    if named:
        current = db.create(owner["id"], owner["revision"], "Literal person", notes="A released human assessment.")
    else:
        current = db.create(owner["id"], owner["revision"], jordan["display_name"], profile_id_target=jordan["id"],
                            target_revision=jordan["revision"], notes="A released human assessment.")
    current = db.update(owner["id"], one(current)["id"], one(current)["version"], allow_agent_notes=True)
    if merge_owner:
        after = profile_db.merge_profiles(owner["id"], casey["id"], current["revision"], casey["revision"])
    else:
        jordan = profile_db.get_profile(jordan["id"])
        profile_db.merge_profiles(jordan["id"], casey["id"], jordan["revision"], casey["revision"])
        after = profile_db.get_profile(owner["id"])
    assert one(after)["notes"] == "A released human assessment."
    assert not one(after)["human"]


def test_relationship_card_named_rename_cannot_overwrite_a_different_current_card(people):
    owner, _, _ = people
    current = db.create(owner["id"], owner["revision"], "Person A", notes="A’s assessment.")
    current = db.create(owner["id"], current["revision"], "Person B", notes="B’s assessment.")
    first = next(card for card in current["relationship_cards"] if card["name"] == "Person A")
    second = next(card for card in current["relationship_cards"] if card["name"] == "Person B")
    db.update(owner["id"], second["id"], second["version"], notes="B’s concurrent edit.")
    with pytest.raises(profile_db.ProfileRevisionConflict, match="already has a relationship"):
        db.update(owner["id"], first["id"], first["version"], name="Person B")
    assert [card["notes"] for card in profile_db.get_profile(owner["id"])["relationship_cards"]] == ["A’s assessment.", "B’s concurrent edit."]


def test_relationship_card_legacy_release_remains_an_editable_model_target_after_owner_merge(people):
    owner, jordan, casey = people
    current = legacy(owner, f"{owner['display_name']} → {jordan['display_name']}: A protected saved analysis.")
    released = db.update(owner["id"], one(current)["id"], one(current)["version"], allow_agent_notes=True)
    merged = profile_db.merge_profiles(owner["id"], casey["id"], released["revision"], casey["revision"])
    snapshot = assessment_db.claim("released-after-merge", merged["id"])
    assert [edge["target_id"] for edge in assessment.editable_relationships(snapshot["profile"])] == [jordan["id"]]
    assessment_db.release_owner("released-after-merge")
