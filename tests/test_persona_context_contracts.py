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


def test_agent_projection_omits_history_without_losing_current_human_constraints():
    correction = {"action": "correct", "content": "Current human correction", "reason": "Explicit feedback"}
    profile = {
        "id": "alex", "merge_history": [{"detail": "old merge " * 4000}] * 20,
        "claims": [{"content": "Original assertion", "status": "corrected", "source_unavailable": True,
                    "correction": correction, "corrections": [{"reason": "old feedback " * 4000}] * 20 + [correction]}],
        "relationships": [{"notes": "Human relationship context", "dismissed": True,
                           "claims": [{"content": "old evidence " * 4000}], "history": [{"content": "old context " * 4000}]}],
    }
    original = deepcopy(profile)
    projected = profile_analysis._profiles_context([profile], max_chars=2000)[0]
    assert projected["merge_history_count"] == 20 and "merge_history" not in projected
    claim = projected["claims"][0]
    assert claim["correction"] == correction and claim["source_unavailable"] is True
    assert claim["correction_count"] == 21 and "corrections" not in claim
    assert projected["relationships"] == [{"notes": "Human relationship context", "dismissed": True, "claim_count": 1, "history_count": 1}]
    assert profile == original


def test_compact_initial_context_keeps_current_corrections_and_rejections():
    constraints = [
        {"content": "Original assertion", "status": "corrected", "correction": {"content": "Human correction"}, "source_unavailable": True},
        {"content": "Rejected assertion", "status": "rejected", "correction": {"reason": "Human rejection"}},
    ]
    profile = {"id": "alex", "claims": [{"content": "old evidence " * 4000}, *constraints]}
    projected = profile_analysis._profiles_context([profile], max_chars=2000)[0]
    assert projected["claim_count"] == 3 and projected["claims_available_via"] == "get_profile"
    assert projected["claims"] == constraints
    with pytest.raises(profile_analysis.ProfileAnalysisError, match="Human profile context") as caught:
        profile_analysis._profiles_context([{**profile, "claims": [*constraints] * 100}], max_chars=2000)
    assert caught.value.error_type == "ProfileContextTooLarge"


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
async def test_profile_tool_keeps_current_override_after_omitting_large_histories(monkeypatch):
    correction = {"action": "reject", "reason": "Current authoritative rejection"}
    profile = {"id": "alex", "merge_history": [{"detail": "old merge " * 4000}] * 20,
               "claims": [{"content": "Original assertion", "status": "rejected", "source_unavailable": True,
                           "correction": correction, "corrections": [{"reason": "old feedback " * 4000}] * 20 + [correction]}]}
    tool = profile_read_tools(monkeypatch, [profile])["get_profile"]
    response = await tool.ainvoke({"profile_id": "alex"})
    payload = json.loads(response)
    assert len(response) <= 32_000 and payload["item"]["merge_history_count"] == 20
    assert payload["item"]["claims"] == [{"content": "Original assertion", "status": "rejected", "source_unavailable": True,
                                          "correction": correction, "correction_count": 21}]
    assert "old feedback" not in response and "old merge" not in response


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
async def test_profile_search_budget_includes_its_envelope_and_preserves_constraints(monkeypatch):
    correction = {"content": "Human correction"}
    profile = {"id": "alex", "claims": [{"content": "old evidence " * 4000},
               {"content": "Original assertion", "status": "corrected", "correction": correction}],
               "section_notes": {"drivers": "x" * 31_000}}
    tools = profile_read_tools(monkeypatch, [profile])
    response = await tools["search_profiles"].ainvoke({"query": "alex"})
    payload = json.loads(response)
    assert len(response) <= 32_000 and payload["matched"] == 1
    assert payload["items"][0]["claims"] == [{"content": "Original assertion", "status": "corrected", "correction": correction}]


def test_agent_profile_context_keeps_human_edits_without_duplicate_relationship_evidence():
    identifier = str(uuid4())
    profile = {
        "id": identifier, "display_name": "Alex", "revision": 4, "identity_scope": "email",
        "metadata": {"job_role": "Engineering lead"}, "nicknames": ["Lex"],
        "section_notes": {"drivers": "Human priority"},
        "section_evidence": {"drivers": {"human": True, "status": "supported", "claim_ids": ["private-hash"], "sources": ["private-source"]}},
        "claims": [{"content": "source evidence " * 2000}],
        "relationships": [{"subject_id": identifier, "target_id": str(uuid4()), "notes": "Human relationship context",
                           "claims": [{"content": "duplicate evidence " * 2000}], "history": [{"content": "old context " * 2000}]}],
    }
    result = profile_analysis._profiles_context([profile], max_chars=2000)[0]
    assert result["section_notes"] == profile["section_notes"] and result["metadata"] == profile["metadata"]
    assert result["nicknames"] == ["Lex"] and result["claim_count"] == 1
    assert result["section_evidence"] == {"drivers": {"human": True, "status": "supported"}}
    assert result["relationships"][0]["notes"] == "Human relationship context"
    assert "claims" not in result["relationships"][0] and "history" not in result["relationships"][0]
    assert len(json.dumps(result)) <= 2000


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
