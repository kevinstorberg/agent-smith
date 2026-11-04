from __future__ import annotations

import json
from uuid import uuid4

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from services.meetings import profile_analysis, profile_db, relationship_db
from tests.test_meeting_memory_agent import call, model as model
from tests.test_meeting_profiles_db import claimed as claimed, participants as participants
from tests.test_meeting_sync import source as source
from tests.test_persona_assessments import observed as observed
from tests.test_profile_source_visibility import invalidate
from tests.test_relationship_analysis import directed as directed, publish


def quoted(messages):
    return json.loads(next(message.content for message in messages if isinstance(message, HumanMessage)).split("\n", 1)[1])


@pytest.mark.asyncio
@pytest.mark.parametrize("withdrawn", [False, True])
async def test_native_profile_histories_reach_initial_and_fresh_model_requests(directed, participants, claimed, model, withdrawn):
    current = publish(directed[0])
    edge = current["relationships"][0]
    generated = edge["notes"]
    first = relationship_db.update(current["id"], edge["id"], edge["revision"], notes="HUMAN_HISTORY_HEAD previous explicit direction HUMAN_HISTORY_TAIL")
    relationship_db.update(current["id"], edge["id"], first["revision"], notes="CURRENT_HUMAN_CONSTRAINT")
    if withdrawn:
        invalidate(claimed[0], "withdrawn")
    profiles = profile_db.load_profiles(participants)
    visible = profiles[0]["relationships"][0]
    assert "HUMAN_HISTORY_TAIL" in json.dumps(visible["history"])
    assert (generated in json.dumps(visible)) is not withdrawn
    if not withdrawn:
        assert any(item["analysis_evidence"].get("claim_signatures") for item in visible["history"])
    assert "raw_analysis_evidence" not in json.dumps(visible)

    instance, _ = model([call("get_profile", profile_id=current["id"]), call("stage_profiles", items=[], reason="No new observation.")])
    await profile_analysis.analyze_profiles(
        {"id": str(uuid4())}, [{"id": "segment-0", "text": "A separate current statement."}], [],
        participants=participants, profiles=profiles, memories=[],
    )

    initial = quoted(instance.seen[0])["canonical_profiles"][0]
    fresh = json.loads(next(message.content for message in instance.seen[1] if isinstance(message, ToolMessage) and message.name == "get_profile"))["item"]
    for record in (initial, fresh):
        serialized = json.dumps(record)
        assert "HUMAN_HISTORY_HEAD" in serialized and "HUMAN_HISTORY_TAIL" in serialized
        assert "CURRENT_HUMAN_CONSTRAINT" in serialized and "raw_analysis_evidence" not in serialized
        assert (generated in serialized) is not withdrawn
        if withdrawn:
            assert "I prioritize reliability" not in serialized
            stale = next(item for item in record["relationships"][0]["history"] if item["analysis_evidence"].get("status") == "supported")
            assert stale["analysis_stale"] and stale["notes"] == ""


@pytest.mark.asyncio
async def test_full_directory_metadata_reaches_actual_tool_response(observed, participants, model):
    name = "Full directory " + uuid4().hex
    metadata = {field: f"{field}:" + "x" * 700 + f" {field.upper()}_TAIL" for field in ("company", "job_role", "supervisor")}
    current = profile_db.update_metadata(observed["id"], observed["revision"], display_name=name, metadata=metadata)
    instance, _ = model([
        call("list_profile_names", query=name),
        call("stage_profiles", items=[], reason="No new observation."),
    ])
    await profile_analysis.analyze_profiles(
        {"id": str(uuid4())}, [{"id": "segment-0", "text": "Current statement."}], [],
        participants=participants, profiles=profile_db.load_profiles(participants), memories=[],
    )
    response = json.loads(next(message.content for message in instance.seen[1] if isinstance(message, ToolMessage) and message.name == "list_profile_names"))
    item = next(row for row in response["items"] if row["id"] == current["id"])
    assert item["metadata"] == metadata


def test_history_opt_in_never_enables_raw_card_state(directed, participants):
    current = publish(directed[0])
    edge = current["relationships"][0]
    relationship_db.update(current["id"], edge["id"], edge["revision"], notes="Human current context")
    standard = profile_db.get_profile(current["id"])["relationships"][0]
    full = profile_db.get_profile(current["id"], include_history=True)["relationships"][0]
    assert "history" not in standard and full["history"]
    assert "raw_analysis_evidence" not in full and "source_version" not in full
