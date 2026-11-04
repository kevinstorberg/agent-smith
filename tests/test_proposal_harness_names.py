from __future__ import annotations

import pytest

from scripts.shared.validation import MAX_NAME_LENGTH
from services.graphs.tools.improve_tools import build_file_proposal_tool
from services.proposals.service import stage_proposal


def proposal(kind: str, name: object, action: str = "create") -> dict:
    return {
        "target_kind": kind,
        "action": action,
        "target_name": name,
        "title": "Improve the fixture",
        "rationale": "An isolated fixture establishes the naming contract.",
        "body": "Complete proposed harness body.",
    }


@pytest.mark.parametrize("kind", ["rule", "skill", "hook"])
@pytest.mark.parametrize("action", ["create", "update"])
@pytest.mark.parametrize(
    "name",
    [
        "../outside",
        "/tmp/outside",
        "C:\\outside",
        "nested/item",
        "UpperCase",
        "has space",
        "x" * (MAX_NAME_LENGTH + 1),
        42,
        ["fixture"],
    ],
)
def test_harness_proposal_rejects_invalid_names_before_target_lookup(
    kind, action, name
):
    with pytest.raises(ValueError, match="name must|target_name must"):
        stage_proposal(proposal(kind, name, action))


@pytest.mark.parametrize("kind", ["rule", "skill", "hook"])
@pytest.mark.parametrize(
    "name", ["../outside", "/tmp/outside", "C:\\outside", "x" * (MAX_NAME_LENGTH + 1)]
)
def test_file_proposal_tool_returns_name_feedback_without_collecting(kind, name):
    collector = {}
    tool = build_file_proposal_tool(collector, max_proposals=1)

    result = tool.invoke(proposal(kind, name))

    assert result.startswith("Proposal rejected:")
    assert "name must" in result
    assert collector == {}


@pytest.mark.parametrize("kind", ["rule", "skill", "hook"])
def test_harness_proposal_accepts_a_name_at_the_existing_limit(kind):
    name = "x" * MAX_NAME_LENGTH

    staged = stage_proposal(proposal(kind, name))

    assert staged["target_name"] == name
    assert staged["target_kind"] == kind


def test_job_proposal_keeps_its_existing_free_form_name_contract():
    staged = stage_proposal(
        {
            "target_kind": "job",
            "action": "create",
            "target_name": "GP B1 Free Form Job",
            "title": "Add a fixture job",
            "rationale": "Verify the existing job naming contract.",
            "schedule_config": {"hours": 1},
            "input_params": {"command": "never executed"},
        }
    )

    assert staged["target_name"] == "GP B1 Free Form Job"
