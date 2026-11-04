from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.messages import ToolMessage

from services.db import get_connection
from services.meetings import profile_db, profile_directory, speaker_analysis, speaker_context, speaker_db, speaker_profiles, speaker_runtime
from tests.test_meeting_memory_agent import call
from tests.test_speaker_context import request_data, speaker_model as speaker_model, statement


@pytest.mark.asyncio
async def test_actual_speaker_request_keeps_all_candidates_context_and_summary(speaker_model):
    segments = [statement(f"SOURCE_{index}_TAIL", index=index) for index in range(52)]
    candidates = [{"name": f"Candidate {index}"} for index in range(205)]
    candidates[-1]["name"] = "Long supplied name " + "n" * 220 + " NAME_TAIL"
    snapshot = {"id": str(uuid4()), "summary_text": "SUMMARY_HEAD " + "s" * 4500 + " SUMMARY_TAIL",
                "identity_candidates": candidates,
                "manual_participants": [{"name": "Human identity", "segment_id": "segment-0"}]}
    original = deepcopy((snapshot, segments))
    context, anchors = speaker_context.window_context(snapshot, segments, 51, [])
    instance = speaker_model([call("stage_speakers", assignments=[], reason="No new grounded identity.")])

    await speaker_analysis.identify_statements(snapshot, segments[51:], context=context, anchors=anchors,
                                               deadline=asyncio.get_running_loop().time() + 20)

    data = request_data(instance.seen[0])
    assert data["meeting"]["summary_text"] == snapshot["summary_text"]
    assert [row["text"] for row in data["read_only_context"]] == [row["text"] for row in segments[:51]]
    assert data["candidates"][-1]["name"] == candidates[-1]["name"]
    assert len(data["candidates"]) == 206
    assert data["read_only_identity_anchors"][0]["source"] == "human"
    assert (snapshot, segments) == original


@pytest.mark.asyncio
async def test_complete_oversize_speaker_context_fails_before_model(speaker_model):
    segments = [statement("🙂" * 500, index=index) for index in range(50)]
    context, anchors = speaker_context.window_context({}, segments, 40, [])
    instance = speaker_model([call("stage_speakers", assignments=[], reason="Must not infer from partial input")])
    with pytest.raises(speaker_analysis.SpeakerAnalysisError, match="context") as caught:
        await speaker_analysis.identify_statements({}, segments[40:42], context=context, anchors=anchors,
                                                   deadline=asyncio.get_running_loop().time() + 20)
    assert caught.value.error_type == "SpeakerContextTooLarge" and instance.seen == []


def test_oversized_statement_is_never_skipped_or_advanced():
    segments = [statement("A complete first statement."), statement("x" * 12_001, index=1)]
    original = deepcopy(segments)
    assert speaker_analysis.target_window(segments, 0) == (segments[:1], 1)
    with pytest.raises(speaker_analysis.SpeakerAnalysisError, match="complete speaker statement"):
        speaker_analysis.target_window(segments, 1)
    assert segments == original


def test_profile_identity_context_keeps_complete_aliases_metadata_and_relationships():
    raw = {"id": str(uuid4()), "display_name": "Alex", "revision": 1,
           "nicknames": [f"Nickname {index}" for index in range(8)],
           "aliases": [{"display_name": f"Alias {index}"} for index in range(8)],
           "emails": [f"address{index}@example.test" for index in range(8)],
           "metadata": {"company": "c" * 350 + " COMPANY_TAIL", "other": "o" * 1100 + " OTHER_TAIL"},
           "section_notes": {"overview": "v" * 1600 + " OVERVIEW_TAIL"},
           "relationships": [{"notes": "r" * 250 + f" RELATIONSHIP_{index}_TAIL"} for index in range(7)]}
    original = deepcopy(raw)
    context = speaker_profiles._context(raw)
    assert context["nicknames"] == raw["nicknames"] and len(context["aliases"]) == 8
    assert context["emails"] == raw["emails"] and context["metadata"] == raw["metadata"]
    assert context["overview"] == raw["section_notes"]["overview"]
    assert [row["notes"] for row in context["relationships"]] == [row["notes"] for row in raw["relationships"]]
    assert raw == original


@pytest.fixture
def known_profiles():
    prefix = "Complete speaker " + uuid4().hex
    profiles = [profile_db.create_profile(f"{prefix} {index}") for index in range(8)]
    profiles[-1] = profile_db.update_metadata(profiles[-1]["id"], profiles[-1]["revision"],
        metadata={"job_role": "r" * 350 + " ROLE_TAIL"}, nicknames=[f"Nickname {index}" for index in range(8)])
    yield prefix, profiles
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("DELETE FROM participant_profiles WHERE id IN %s", (tuple(row["id"] for row in profiles),))


def test_native_profile_lookup_pages_and_attached_identities_have_no_hidden_caps(known_profiles):
    prefix, profiles = known_profiles
    rows, offset = [], 0
    while offset is not None:
        page = speaker_profiles.read_contexts(prefix, None, set(), offset=offset, limit=2)
        rows.extend(page["items"])
        offset = page["next_offset"]
    assert {row["profile_id"] for row in rows} == {row["id"] for row in profiles}
    assert next(row for row in rows if row["profile_id"] == profiles[-1]["id"])["metadata"]["job_role"].endswith("ROLE_TAIL")
    attached = speaker_profiles.attached_candidates({"identity_candidates": [
        {"profile_id": row["id"], "name": row["display_name"]} for row in profiles
    ]})
    assert {row["profile_id"] for row in attached} == {row["id"] for row in profiles}


@pytest.mark.asyncio
async def test_actual_speaker_lookup_response_keeps_eighth_profile_and_long_metadata(known_profiles, speaker_model):
    prefix, profiles = known_profiles
    instance = speaker_model([call("search_known_profiles", query=prefix, limit=100),
                              call("stage_speakers", assignments=[], reason="Directory entries are context, not speaker proof.")])
    await speaker_analysis.identify_statements({}, [statement()], context=[], anchors=[],
                                               deadline=asyncio.get_running_loop().time() + 20)
    response = next(message.content for message in instance.seen[1] if isinstance(message, ToolMessage) and message.name == "search_known_profiles")
    assert profiles[-1]["id"] in response and "ROLE_TAIL" in response and "Nickname 7" in response


@pytest.mark.asyncio
async def test_dormant_runtime_exhausts_directory_pages_without_model_activation(monkeypatch):
    people = [{"id": str(uuid4()), "display_name": f"Person {index}"} for index in range(105)]
    calls, saved = [], []
    artifact = {"offset": 0, "manual_snapshot": {}, "draft_assignments": []}

    def names(*, offset, limit):
        calls.append(offset)
        return {"items": people[offset:offset + limit], "next_offset": offset + limit if offset + limit < len(people) else None}

    monkeypatch.setattr(profile_directory, "names", names)
    monkeypatch.setattr(speaker_db, "prepare", lambda *args: ({"transcript": {"segments": []}}, artifact))
    monkeypatch.setattr(speaker_db, "context_snapshot", lambda *args, **kwargs: {})
    monkeypatch.setattr(speaker_profiles, "attached_candidates", lambda *args: [])
    monkeypatch.setattr(speaker_db, "save_progress", lambda *args: saved.append(deepcopy(args[-1])))
    monkeypatch.setattr(speaker_db, "apply", lambda *args: 0)
    run = SimpleNamespace(owner="test", speaker_report={})
    await speaker_runtime.identify(run, {"meeting_id": str(uuid4()), "transcript_hash": "a" * 64}, deadline=asyncio.get_running_loop().time() + 20)
    assert calls == [0, 100]
    assert len(saved[-1]["canonical_candidates"]) == len(people)
