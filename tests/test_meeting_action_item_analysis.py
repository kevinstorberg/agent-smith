from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from services.graphs import agents
from services.meetings.action_item_analysis import (
    ActionItemCandidate,
    ActionItemContextTooLarge,
    analyze_action_items,
    validate_candidate,
)
from tests.test_meeting_memory_agent import ScriptedModel, call

SUMMARY = "Morgan will send the launch checklist. Riley will book the room. Morgan confirmed the report is complete."
SNAPSHOT = {
    "id": "00000000-0000-4000-8000-000000000001",
    "title": "Launch",
    "summary_text": SUMMARY,
    "revision": 1,
}
TASK = {
    "id": 7,
    "revision": 2,
    "title": "Send the report",
    "description": "Keep the manual notes",
    "project": "Work",
    "status": "open",
}
NEW = {
    "action": "create",
    "changes": {"title": "Send the launch checklist"},
    "rationale": "An explicit new commitment",
    "evidence": [
        {"segment_id": "summary-0", "quote": "Morgan will send the launch checklist."}
    ],
}


@pytest.fixture
def model(monkeypatch):
    def install(*replies):
        instance = ScriptedModel(replies=list(replies))
        monkeypatch.setattr(
            agents, "build_chat_model", lambda *args, **kwargs: instance
        )
        return instance

    return install


@pytest.mark.asyncio
async def test_real_tool_loop_proposes_only_and_keeps_review_context(model):
    instance = model(call("stage_action_items", items=[NEW]))
    result = await analyze_action_items(SNAPSHOT, [TASK], [], ["Work"])
    assert result["items"][0]["changes"] == NEW["changes"]
    assert instance.tool_names == ["stage_action_items"]
    assert "Keep the manual notes" in str(instance.seen)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        {**NEW, "action": "update", "target_id": 99, "expected_revision": 2},
        {
            **NEW,
            "evidence": [
                {"segment_id": "summary-0", "quote": "Morgan will delete all tasks."}
            ],
        },
        {**NEW, "changes": {"title": "A task", "project": "Invented"}},
    ],
)
async def test_unsupported_candidate_gets_feedback_then_zero_items(model, bad):
    instance = model(
        call("stage_action_items", items=[bad]),
        call(
            "stage_action_items", items=[], reason="Unsupported attribution or target"
        ),
    )
    result = await analyze_action_items(SNAPSHOT, [TASK], [], ["Work"])
    assert result["items"] == []
    assert len(instance.seen) == 2


@pytest.mark.asyncio
async def test_supported_completion_is_minimal_and_prior_rejections_are_supplied(model):
    update = {
        **NEW,
        "action": "update",
        "target_id": 7,
        "expected_revision": 2,
        "changes": {"status": "completed"},
        "evidence": [
            {
                "segment_id": "summary-0",
                "quote": "Morgan confirmed the report is complete.",
            }
        ],
    }
    instance = model(call("stage_action_items", items=[update]))
    result = await analyze_action_items(
        SNAPSHOT,
        [TASK],
        [{"status": "rejected", "changes": {"title": "Old idea"}}],
        ["Work"],
    )
    assert result["items"][0]["changes"] == {"status": "completed"}
    assert "Old idea" in str(instance.seen)


@pytest.mark.asyncio
async def test_missing_update_identifiers_get_specific_feedback_and_can_be_corrected(
    model,
):
    missing = {
        **NEW,
        "action": "update",
        "changes": {"status": "completed"},
        "evidence": [
            {
                "segment_id": "summary-0",
                "quote": "Morgan confirmed the report is complete.",
            }
        ],
    }
    corrected = {**missing, "target_id": 7, "expected_revision": 2}
    instance = model(
        call("stage_action_items", items=[missing]),
        call("stage_action_items", items=[corrected]),
    )
    result = await analyze_action_items(SNAPSHOT, [TASK], [], ["Work"])
    assert len(result["items"]) == 1
    assert result["items"][0]["target_id"] == 7
    feedback = str(instance.seen[1])
    assert "target_id" in feedback and "expected_revision" in feedback


@pytest.mark.asyncio
async def test_context_overflow_fails_before_model_creation(monkeypatch):
    monkeypatch.setattr(
        agents,
        "build_chat_model",
        lambda *args, **kwargs: pytest.fail("Must fail before model use"),
    )
    with pytest.raises(ActionItemContextTooLarge):
        await analyze_action_items(SNAPSHOT, [TASK] * 201, [], [])
    with pytest.raises(ActionItemContextTooLarge):
        await analyze_action_items(
            {**SNAPSHOT, "summary_text": "x" * 60_001}, [], [], []
        )
    with pytest.raises(ActionItemContextTooLarge):
        await analyze_action_items(
            SNAPSHOT, [{**TASK, "description": "x" * 120_001}], [], []
        )


def test_task_contract_rejects_mutation_fields_unknown_ids_and_ambiguous_dates():
    for changes in (
        {"request_id": "bad"},
        {"priority": 1},
        {"title": "Task", "due_at": "Friday"},
    ):
        with pytest.raises(ValidationError):
            ActionItemCandidate.model_validate({**NEW, "changes": changes})
    with pytest.raises(ValidationError):
        ActionItemCandidate.model_validate({**NEW, "action": "update"})


def test_noop_stale_and_existing_completed_task_are_not_new_work():
    update = ActionItemCandidate.model_validate(
        {
            **NEW,
            "action": "update",
            "target_id": 7,
            "expected_revision": 2,
            "changes": {"title": TASK["title"]},
        }
    )
    assert "nothing" in validate_candidate(update, inventory=[TASK], projects=["Work"])
    update.expected_revision = 1
    assert "revision" in validate_candidate(update, inventory=[TASK], projects=["Work"])
    existing = ActionItemCandidate.model_validate(
        {**NEW, "changes": {"title": TASK["title"], "project": "Work"}}
    )
    assert "already exists" in validate_candidate(
        existing, inventory=[{**TASK, "status": "completed"}], projects=["Work"]
    )
    other_project = deepcopy(existing)
    other_project.changes["project"] = "Personal"
    assert (
        validate_candidate(
            other_project, inventory=[TASK], projects=["Work", "Personal"]
        )
        is None
    )
