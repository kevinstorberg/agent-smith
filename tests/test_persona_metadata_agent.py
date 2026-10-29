import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from services.meetings import profile_analysis
from tests.test_meeting_memory_agent import backend as backend, call, model as model
from tests.test_meeting_profile_agent import ALICE, BOB, PARTICIPANTS, canonical as canonical, profile

TEXT = "I work at Example Co as security lead. I started on 2025-01-02 and report to Morgan."
SEGMENTS = [{"id": "segment-0", "text": TEXT, "speaker": {"name": "Alice"}}]
PATCH = {"subject_id": ALICE, "fields": {"company": "Example Co", "job_role": "security lead", "start_date": "2025-01-02"},
         "evidence": [{"segment_id": "segment-0", "quote": TEXT}]}


async def analyze(**kwargs):
    return await profile_analysis.analyze_profiles(
        {"id": "synthetic", "title": "Synthetic metadata"}, SEGMENTS, [], participants=PARTICIPANTS,
        profiles=kwargs.pop("profiles", []), memories=[], **kwargs,
    )


@pytest.mark.asyncio
async def test_real_react_loop_stages_explicit_metadata_only_and_quotes_prior_updates(backend, model):
    instance, roles = model([
        call("stage_profiles", items=[], metadata_updates=[PATCH]), AIMessage(content="Done"),
    ])
    result = await analyze(previous_metadata=[PATCH])
    assert result == {"items": [], "metadata_updates": [PATCH], "reason": ""}
    assert roles == [("persona", "curator")]
    prompt = next(message.content for message in instance.seen[0] if isinstance(message, HumanMessage))
    data = json.loads(prompt.split("\n", 1)[1])
    assert data["earlier_metadata_updates"] == [PATCH] and data["earlier_metadata_count"] == 1
    assert backend[2] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"subject_id": "unknown"}, {"subject_id": BOB},
    {"fields": {"unexpected": "field"}}, {"fields": {"company": " "}}, {"fields": {}},
    {"fields": {"start_date": "October 2025"}},
    {"evidence": [{"segment_id": "not-in-window", "quote": TEXT}]},
    {"evidence": [{"segment_id": "segment-0", "quote": "A fabricated statement"}]},
])
async def test_metadata_staging_enforces_catalog_fields_dates_and_exact_speaker_quotes(backend, model, changes):
    model([call("stage_profiles", items=[], metadata_updates=[{**PATCH, **changes}]), AIMessage(content="Done")])
    with pytest.raises(profile_analysis.ProfileAnalysisError, match="without a valid staged"):
        await analyze()


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata,provenance", [
    ({"company": "Existing company"}, {}),
    ({}, {"company": {"human": True}}),
    ({"company": "Known company"}, {"company": {"meeting_id": "prior-source"}}),
])
async def test_existing_values_and_human_clears_are_not_replaced_by_metadata_staging(backend, model, metadata, provenance):
    instance, _ = model([
        call("stage_profiles", items=[], metadata_updates=[PATCH]),
        call("stage_profiles", items=[], reason="Existing or human-protected values remain unchanged."),
        AIMessage(content="Done"),
    ])
    result = await analyze(profiles=[profile(PARTICIPANTS[0], metadata=metadata, metadata_provenance=provenance)])
    assert result["items"] == [] and "metadata_updates" not in result
    assert any(isinstance(message, ToolMessage) and "Only fill missing metadata" in message.content for message in instance.seen[1])


@pytest.mark.asyncio
async def test_fresh_profile_read_protects_human_clear_before_metadata_staging(backend, canonical, model):
    rows, _ = canonical
    rows[ALICE].update(metadata={}, metadata_provenance={"company": {"human": True}})
    instance, _ = model([
        call("get_profile", profile_id=ALICE), call("stage_profiles", items=[], metadata_updates=[PATCH]),
        call("stage_profiles", items=[], reason="Respect the refreshed human clear"), AIMessage(content="Done"),
    ])
    assert (await analyze())["items"] == []
    assert any(isinstance(message, ToolMessage) and "Only fill missing metadata" in message.content for message in instance.seen[-1])


@pytest.mark.asyncio
async def test_initial_agent_context_redacts_deleted_profile_fields(backend, model):
    deleted = profile(PARTICIPANTS[0], deleted=True, revision=7,
                      metadata={"company": "Private tombstoned company"},
                      metadata_provenance={"company": {"human": True}},
                      section_notes={"drivers": "Private tombstoned notes"}, nicknames=["Private tombstoned nickname"],
                      claims=[{"content": "Private tombstoned claim"}])
    instance, _ = model([
        call("stage_profiles", items=[], reason="Deleted identities remain deleted"), AIMessage(content="Done"),
    ])
    await analyze(profiles=[deleted])
    prompt = next(message.content for message in instance.seen[0] if isinstance(message, HumanMessage))
    data = json.loads(prompt.split("\n", 1)[1])
    assert data["canonical_profiles"] == [{"id": ALICE, "revision": 7, "deleted": True}]
    assert "Private tombstoned" not in prompt
