import copy
import json
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from psycopg2.extras import Json

from services.db import get_connection
from services.graphs.runtime import dispatch
from services.meetings import profile_db, relationship_db
from services.personas import assessment, assessment_db, revisions
from tests.test_meeting_memory_agent import call, model as model
from tests.test_meeting_profiles_db import claimed as claimed, participants as participants
from tests.test_meeting_sync import source as source
from tests.test_persona_assessments import observed as observed


@pytest.fixture
def directed(observed):
    third = profile_db.create_profile("Kevin")
    claims = []
    for target in (observed["relationships"][0]["target_id"], third["id"]):
        for original in observed["claims"]:
            claims.append({**copy.deepcopy(original), "id": str(uuid4()), "target_id": target})
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE participant_profiles SET display_name='Aaron',claims=%s WHERE id=%s", (Json(claims), observed["id"]))
        relationship_db.ensure_claim_links(cursor, claims)
    yield observed["id"], claims
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("DELETE FROM participant_profiles WHERE id=%s", (third["id"],))


def proposals(snapshot):
    return [{"target_id": edge["target_id"], "status": "supported", "text": f"Values clear collaboration with {edge['target_name']}.",
             "claim_ids": [claim["id"] for claim in snapshot["claims"] if claim["canonical_target_id"] == edge["target_id"]]}
            for edge in assessment.editable_relationships(snapshot["profile"])]


def publish(profile_id):
    snapshot = assessment_db.claim("relationship-test", profile_id)
    return assessment_db.apply("relationship-test", snapshot, assessment_db.insufficient(snapshot["profile"]), proposals(snapshot))


@pytest.mark.asyncio
async def test_real_react_service_publishes_two_directed_entries_and_stable_inputs(directed, model):
    profile_id, claims = directed
    row = profile_db.get_profile(profile_id)
    targets = {claim["target_id"] for claim in claims}
    payload = [{"target_id": target, "status": "supported", "text": "Encourages careful decisions and clear communication.",
                "claim_ids": [claim["id"] for claim in claims if claim["target_id"] == target]} for target in targets]
    _, roles = model([call("stage_assessment", sections=assessment_db.insufficient(row), relationships=payload), AIMessage(content="Done")])
    result = json.loads(await dispatch("persona", {"profile_id": profile_id}))
    assert result["assessments"]["outcome"] == "done" and roles == [("persona", "curator")]
    current = profile_db.get_profile(profile_id)
    assert {edge["target_id"] for edge in current["relationships"]} == targets
    assert all(edge["notes"].startswith("Encourages") and edge["analysis_evidence"]["claim_count"] == 2 for edge in current["relationships"])
    assert "relationships" not in current["section_notes"]
    assessment_db.request(profile_id, current["revision"])
    assert assessment_db.claim("unchanged", profile_id)["skipped"]


@pytest.mark.asyncio
async def test_model_reads_relationship_ownership_without_duplicating_storage_proofs(directed, model):
    current = publish(directed[0])
    profile_db.update_metadata(current["id"], current["revision"], nicknames=["Aaron S"])
    snapshot = assessment_db.claim("proof-context", current["id"])
    assert all(edge["analysis_evidence"].get("claim_signatures") for edge in snapshot["profile"]["relationships"])
    instance, _ = model([call("stage_assessment", sections=assessment_db.insufficient(snapshot["profile"]),
                              relationships=proposals(snapshot)), AIMessage(content="Done")])
    try:
        await assessment.synthesize(snapshot["profile"], snapshot["claims"])
        payload = json.loads(instance.seen[0][-1].content.split("\n", 1)[1])
        for edge in payload["relationships"]:
            proof = edge["analysis_evidence"]
            assert proof["human"] is False and proof["claim_ids"]
            assert not set(proof) & {"claim_signatures", "sources", "subject_id", "target_id", "generated_at"}
    finally:
        assessment_db.release_owner("proof-context")


def test_human_clear_label_only_and_release_preserve_field_ownership(directed):
    profile_id, _ = directed
    current = publish(profile_id)
    edge = current["relationships"][0]
    renamed = relationship_db.update(profile_id, edge["id"], edge["revision"], label="Colleague")
    assert renamed["notes"] == edge["notes"] and not renamed["analysis_evidence"]["human"]
    cleared = relationship_db.update(edge["target_id"], edge["id"], renamed["revision"], notes="")
    assert cleared["notes"] == "" and cleared["analysis_evidence"]["human"]
    snapshot = assessment_db.claim("protected", profile_id)
    assert edge["target_id"] not in {item["target_id"] for item in proposals(snapshot)}
    assessment_db.release_owner("protected")
    released = relationship_db.update(profile_id, edge["id"], cleared["revision"], allow_agent_notes=True)
    assert not released["analysis_evidence"]["human"] and released["notes"] == ""
    with pytest.raises(ValueError):
        relationship_db.update(profile_id, edge["id"], released["revision"], notes="", allow_agent_notes=True)


def test_releasing_human_analysis_preserves_text_in_reads_history_and_model_until_replaced(directed):
    profile_id, _ = directed
    current = profile_db.get_profile(profile_id)
    edge = current["relationships"][0]
    human = relationship_db.update(profile_id, edge["id"], edge["revision"], notes="Human working relationship context.")
    released = relationship_db.update(profile_id, edge["id"], human["revision"], allow_agent_notes=True)
    assert released["notes"] == human["notes"] and not released["analysis_evidence"]["human"]
    current = profile_db.get_profile(profile_id)
    assert next(item for item in current["relationships"] if item["id"] == edge["id"])["notes"] == human["notes"]
    history = revisions.list_history(profile_id)
    assert history["items"][0]["changes"]["relationships"]["after"][0]["notes"] == human["notes"]
    snapshot = assessment_db.claim("release-preserves-text", profile_id)
    existing = next(item for item in snapshot["profile"]["relationships"] if item["id"] == edge["id"])
    assert existing["notes"] == human["notes"] and existing["analysis_evidence"]["origin"] == "human"
    updated = assessment_db.apply("release-preserves-text", snapshot, assessment_db.insufficient(snapshot["profile"]), proposals(snapshot))
    generated = next(item for item in updated["relationships"] if item["id"] == edge["id"])
    assert generated["notes"].startswith("Values") and not generated["analysis_evidence"]["human"]
    assessment_db.request(profile_id, updated["revision"])
    assert assessment_db.claim("release-output-stable", profile_id)["skipped"]


def test_source_withdrawal_redacts_current_and_history_without_erasing_raw(directed):
    profile_id, claims = directed
    current = publish(profile_id)
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE meeting_summaries SET available=false WHERE id=%s", (claims[0]["meeting_id"],))
    public = profile_db.get_profile(profile_id)
    assert not public["relationships"]
    history = revisions.list_history(profile_id)
    entries = [edge for event in history["items"] for edge in event["changes"].get("relationships", {}).get("after", [])]
    assert entries and all(edge["notes"] == "" for edge in entries)
    assert any(event["source_restricted"] for event in history["items"])
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT notes FROM profile_relationships WHERE subject_id=%s", (profile_id,))
        assert all(row[0].startswith("Values") for row in cursor.fetchall())
    assert assessment_db.has_requested_work(current["id"])
    snapshot = assessment_db.claim("withdrawn-refresh", profile_id)
    assessment_db.apply("withdrawn-refresh", snapshot, assessment_db.insufficient(snapshot["profile"]))
    assert not assessment_db.has_requested_work(profile_id)


def test_target_validation_rejects_cross_target_duplicate_and_missing_outputs(directed):
    snapshot = assessment_db.claim("validation", directed[0])
    items = proposals(snapshot)
    for invalid in ([items[0]], [items[0], items[0]], [{**items[0], "claim_ids": items[1]["claim_ids"]}, items[1]]):
        with pytest.raises(ValueError):
            assessment.validate_relationships(snapshot["profile"], snapshot["claims"], invalid)
    assessment_db.release_owner("validation")


def test_incoming_human_perspective_is_independent_and_edge_edit_fences_publish(directed):
    profile_id, _ = directed
    profile = profile_db.get_profile(profile_id)
    target = profile_db.get_profile(profile["relationships"][0]["target_id"])
    reverse = relationship_db.create(target["id"], profile_id, target["revision"], profile["revision"], notes="Independent incoming perspective")
    snapshot = assessment_db.claim("concurrent", profile_id)
    outgoing = assessment.editable_relationships(snapshot["profile"])[0]
    relationship_db.update(outgoing["target_id"], outgoing["id"], outgoing["revision"], notes="Human clarification")
    with pytest.raises(profile_db.ProfileRevisionConflict):
        assessment_db.apply("concurrent", snapshot, assessment_db.insufficient(snapshot["profile"]), proposals(snapshot))
    assessment_db.release_owner("concurrent")
    current = publish(profile_id)
    incoming = next(edge for edge in current["relationships"] if edge["id"] == reverse["id"])
    assert incoming["notes"] == "Independent incoming perspective" and incoming["subject_id"] == target["id"]
    assert next(edge for edge in current["relationships"] if edge["id"] == outgoing["id"])["notes"] == "Human clarification"


def test_canonical_alias_claims_keep_original_signature_and_target_group(directed):
    profile_id, claims = directed
    target_id = claims[0]["target_id"]
    target = profile_db.get_profile(target_id)
    linked = profile_db.link_alias(target_id, f"known-{uuid4().hex}@example.test", target["revision"])
    alias = linked["aliases"][0]["id"]
    for claim in claims:
        if claim["target_id"] == target_id:
            claim["target_id"] = alias
    try:
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE participant_profiles SET claims=%s WHERE id=%s", (Json(claims), profile_id))
        from services.personas import sections

        snapshot = assessment_db.claim("aliases", profile_id)
        for claim in snapshot["claims"]:
            assert claim["signature"] == sections.claim_signature(claim)
            if claim["target_id"] == alias:
                assert claim["canonical_target_id"] == target_id
        assessment_db.apply("aliases", snapshot, assessment_db.insufficient(snapshot["profile"]), proposals(snapshot))
        current = profile_db.get_profile(profile_id)
        assert next(edge for edge in current["relationships"] if edge["target_id"] == target_id)["analysis_evidence"]["claim_count"] == 2
    finally:
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM participant_profiles WHERE id=%s", (alias,))


def test_relationship_context_cap_fails_before_model_construction():
    row = {"id": "source", "relationships": [{"id": str(index), "subject_id": "source", "target_id": str(index),
                                                "analysis_evidence": {"human": False}} for index in range(31)]}
    with pytest.raises(assessment.AssessmentError, match="30 editable"):
        assessment.editable_relationships(row)


@pytest.mark.parametrize("legacy_text", ["Human relationship boundaries remain authoritative.", ""])
def test_legacy_human_relationship_text_or_clear_blocks_ai_until_explicit_release(directed, legacy_text):
    profile_id, _ = directed
    current = profile_db.get_profile(profile_id)
    protected = profile_db.update_metadata(profile_id, current["revision"], section_notes={"relationships": legacy_text})
    snapshot = assessment_db.claim("legacy-protected", profile_id)
    assert assessment.editable_relationships(snapshot["profile"]) == []
    with pytest.raises(ValueError, match="editable known outgoing target"):
        assessment.validate_relationships(snapshot["profile"], snapshot["claims"], [{
            "target_id": current["relationships"][0]["target_id"], "status": "insufficient_evidence", "text": "", "claim_ids": [],
        }])
    applied = assessment_db.apply("legacy-protected", snapshot, assessment_db.insufficient(snapshot["profile"]), [])
    assert all(edge["notes"] == "" and not edge["analysis_evidence"]["human"] for edge in applied["relationships"])
    assert applied["section_notes"].get("relationships", "") == legacy_text
    released = profile_db.update_metadata(profile_id, applied["revision"], allow_agent_sections=["relationships"])
    assert not released["section_evidence"]["relationships"]["human"]
    refreshed = publish(profile_id)
    assert all(edge["notes"].startswith("Values") for edge in refreshed["relationships"])
    assert protected["section_evidence"]["relationships"]["human"]
