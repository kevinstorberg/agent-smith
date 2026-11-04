import asyncio
import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from alembic import command
from alembic.config import Config
from psycopg2.extras import Json

from scripts.shared.local_postgres import temporary_postgres
from services import config
from services.db.create import create_database
from services.meetings import profile_analysis, profile_db


def profile_read_tools(monkeypatch, profiles):
    catalog = {row["id"]: {"id": row["id"], "segment_ids": ["segment-0"]} for row in profiles}
    rows = {row["id"]: row for row in profiles}
    monkeypatch.setattr(profile_db, "load_profiles", lambda participants: [deepcopy(rows[person["id"]]) for person in participants])
    context = profile_analysis.AnalysisContext({}, [{"id": "segment-0", "text": "Synthetic statement"}], [], require_memory_search=False)
    return {tool.name: tool for tool in profile_analysis._profile_tools(context, catalog, profiles)}


def test_agent_projection_preserves_all_authorized_history_and_constraints():
    correction = {"action": "correct", "content": "Current human correction", "reason": "Explicit feedback"}
    profile = {
        "id": "alex", "merge_history": [{"detail": "MERGE_HEAD"}, {"detail": "MERGE_TAIL"}],
        "claims": [{"content": "Original assertion", "status": "corrected", "source_unavailable": True,
                    "correction": correction, "corrections": [{"reason": "EARLIER_CORRECTION"}, correction]}],
        "relationships": [{"notes": "Human relationship context", "dismissed": True,
                           "claims": [{"content": "RELATIONSHIP_EVIDENCE"}], "history": [{"notes": "HUMAN_HISTORY"}]}],
    }
    original = deepcopy(profile)
    projected = profile_analysis._profiles_context([profile], max_chars=8000)[0]
    assert projected == profile and profile == original


def test_initial_profile_context_fails_instead_of_compacting_claims():
    constraints = [
        {"content": "Original assertion", "status": "corrected", "correction": {"content": "Human correction"}, "source_unavailable": True},
        {"content": "Rejected assertion", "status": "rejected", "correction": {"reason": "Human rejection"}},
    ]
    profile = {"id": "alex", "claims": [{"content": "old evidence " * 4000}, *constraints]}
    original = deepcopy(profile)
    with pytest.raises(profile_analysis.ProfileAnalysisError, match="Complete profile context") as caught:
        profile_analysis._profiles_context([profile], max_chars=2000)
    assert caught.value.error_type == "ProfileContextTooLarge" and profile == original


@pytest.mark.asyncio
async def test_profile_tool_bounds_complete_envelopes_and_pages_without_skips(monkeypatch):
    profile = {"id": "alex", "section_notes": {"drivers": "🙂" * 15_000},
               "claims": [{"content": f"Claim {index}: " + "e" * 12_000} for index in range(3)]}
    original = deepcopy(profile)
    tool = profile_read_tools(monkeypatch, [profile])["get_profile"]
    observed, offset = [], 0
    while offset is not None:
        response = await tool.ainvoke({"profile_id": "alex", "offset": offset, "limit": 20})
        assert len(response) <= 32_000
        payload = json.loads(response)
        assert payload["total_claims"] == 3 and len(payload["item"]["claims"]) == 1
        observed.extend(payload["item"]["claims"])
        offset = payload["next_offset"]
    assert observed == profile["claims"] and profile == original
    empty = json.loads(await tool.ainvoke({"profile_id": "alex", "offset": 10}))
    assert empty["item"]["claims"] == [] and empty["next_offset"] is None


@pytest.mark.asyncio
async def test_profile_tool_keeps_complete_history_and_current_override(monkeypatch):
    correction = {"action": "reject", "reason": "Current authoritative rejection"}
    profile = {"id": "alex", "merge_history": [{"detail": "MERGE_HISTORY_TAIL"}],
               "claims": [{"content": "Original assertion", "status": "rejected", "source_unavailable": True,
                           "correction": correction, "corrections": [{"reason": "EARLIER_FEEDBACK"}, correction]}]}
    tool = profile_read_tools(monkeypatch, [profile])["get_profile"]
    response = await tool.ainvoke({"profile_id": "alex"})
    payload = json.loads(response)
    assert payload["item"] == profile and payload["next_offset"] is None
    assert "EARLIER_FEEDBACK" in response and "MERGE_HISTORY_TAIL" in response


@pytest.mark.asyncio
@pytest.mark.parametrize("changes,diagnostic", [
    ({"section_notes": {"drivers": "x" * 32_000}}, "Human profile context"),
    ({"claims": [{"content": "x" * 32_000}]}, "A complete profile claim"),
    ({"claims": [{"status": "corrected", "correction": {"content": "x" * 32_000}}]}, "A complete profile claim"),
])
async def test_profile_tool_fails_actionably_instead_of_returning_oversized_context(monkeypatch, changes, diagnostic):
    tool = profile_read_tools(monkeypatch, [{"id": "alex", "claims": [], **changes}])["get_profile"]
    response = await tool.ainvoke({"profile_id": "alex"})
    payload = json.loads(response)
    assert len(response) <= 32_000 and payload["error_type"] == "ProfileContextTooLarge"
    assert diagnostic in payload["error"]


@pytest.mark.asyncio
async def test_profile_search_rejects_oversize_without_compacting_constraints(monkeypatch):
    correction = {"content": "Human correction"}
    profile = {"id": "alex", "claims": [{"content": "old evidence " * 4000},
               {"content": "Original assertion", "status": "corrected", "correction": correction}],
               "section_notes": {"drivers": "x" * 31_000}}
    tools = profile_read_tools(monkeypatch, [profile])
    response = await tools["search_profiles"].ainvoke({"query": "alex"})
    payload = json.loads(response)
    assert payload["error_type"] == "ProfileContextTooLarge" and "items" not in payload


def test_agent_profile_keeps_full_proofs_and_excludes_ui_derived_duplicates():
    identifier = str(uuid4())
    profile = {
        "id": identifier, "display_name": "Alex", "revision": 4, "identity_scope": "email",
        "metadata": {"job_role": "Engineering lead"}, "nicknames": ["Lex"],
        "metadata_provenance": {"job_role": {"human": False, "evidence": [{"quote": "METADATA_PROOF"}]}},
        "section_notes": {"drivers": "Human priority"},
        "section_evidence": {"drivers": {"human": True, "status": "supported", "claim_ids": ["claim"], "sources": ["source"]}},
        "claims": [{"content": "SOURCE_EVIDENCE"}],
        "relationships": [{"subject_id": identifier, "target_id": str(uuid4()), "notes": "Human relationship context",
                           "claims": [{"content": "RELATIONSHIP_PROOF"}], "history": [{"notes": "HUMAN_HISTORY"}]}],
        "relationship_cards": ["PRIVATE_UI_DUPLICATE"], "relationship_unassigned": ["PRIVATE_UI_DUPLICATE"],
    }
    result = profile_analysis._profiles_context([profile], max_chars=8000)[0]
    assert result == {key: value for key, value in profile.items() if key not in {"relationship_cards", "relationship_unassigned"}}
    assert "PRIVATE_UI_DUPLICATE" not in json.dumps(result)


def test_oversized_human_context_fails_before_model_construction(monkeypatch):
    called = []

    async def unexpected_model(*args, **kwargs):
        called.append(True)
        raise AssertionError("Model construction must not be reached")

    monkeypatch.setattr(profile_analysis, "run_analysis", unexpected_model)
    participants = [{
        "id": str(uuid4()), "identity_key": "test:" + str(index), "display_name": str(index),
        "segment_ids": ["segment-0"],
    } for index in range(18)]
    profiles = [{
        "id": person["id"], "claims": [], "section_notes": {"drivers": "x" * 4000}, "relationships": [],
    } for person in participants]
    try:
        asyncio.run(profile_analysis.analyze_profiles(
            {"id": str(uuid4())}, [{"id": "segment-0", "text": "Synthetic statement"}], [],
            participants=participants, profiles=profiles, memories=[],
        ))
    except profile_analysis.ProfileAnalysisError as error:
        assert error.error_type == "ProfileContextTooLarge"
    else:
        raise AssertionError("Oversized context was not rejected")
    assert called == []


def test_persona_migration_preserves_legacy_review_and_backfills_structured_edges(monkeypatch):
    alex, blair, meeting = str(uuid4()), str(uuid4()), str(uuid4())
    with temporary_postgres() as url:
        create_database(url)
        monkeypatch.setattr(config, "DATABASE_URL", url)
        migration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(migration, "e7f8a0b1c2d3")
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("""INSERT INTO meeting_summaries
                (id,provider,account_key,external_id,source_name,title,summary_text,source_url,provider_created_at,provider_updated_at,content_hash)
                VALUES (%s,'test','migration','legacy','migration','Synthetic','Legacy context','https://example.invalid/legacy',now(),now(),%s)""",
                           (meeting, "a" * 64))
            claim = {"id": str(uuid4()), "subject_id": alex, "target_id": blair, "category": "perception",
                     "content": "Values careful reviews", "meeting_id": meeting, "status": "active"}
            cursor.execute("""INSERT INTO participant_profiles
                (id,identity_key,display_name,email,identity_scope,claims)
                VALUES (%s,%s,'Alex','Alex@Example.invalid','email',%s),(%s,%s,'Blair',NULL,'manual','[]'::jsonb)""",
                           (alex, "email:alex@example.invalid", Json([claim]), blair, "manual:" + blair))
            cursor.execute("""INSERT INTO meeting_digestions
                (meeting_id,transcript_status,transcript_hash,transcript,memory_status,profile_status,profile_artifact)
                VALUES (%s,'ready',%s,%s,'failed','done',%s)""",
                           (meeting, "b" * 64, Json({"segments": []}), Json({"version": 1, "profile_ids": [alex], "items": []})))
        for _ in range(2):
            command.upgrade(migration, "head")
            with psycopg2.connect(url) as connection, connection.cursor() as cursor:
                cursor.execute("SELECT profile_status,profile_artifact,profile_claim_owner,profile_claim_until FROM meeting_digestions WHERE meeting_id=%s", (meeting,))
                status, artifact, owner, until = cursor.fetchone()
                assert status == "done" and artifact["profile_ids"] == [alex] and owner is until is None
                cursor.execute("SELECT subject_id::text,target_id::text FROM profile_relationships")
                assert cursor.fetchall() == [(alex, blair)]
                cursor.execute("SELECT metadata,section_notes,nicknames,email FROM participant_profiles WHERE id=%s", (alex,))
                assert cursor.fetchone() == ({}, {}, [], "Alex@Example.invalid")
            if _ == 0:
                command.downgrade(migration, "e7f8a0b1c2d3")
