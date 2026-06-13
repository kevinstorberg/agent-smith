"""Stage/persist/promote/reject lifecycle for improvement proposals (tracer bullet 2)."""
from __future__ import annotations

import pytest

from services.api.models.proposal import count_by_status, get_proposal, list_proposals
from services.api.models.shared.harness import (
    get_item,
    get_item_by_id,
    get_version_history,
    update_content,
    upsert_item,
)
from services.config import ALL_AGENTS
from services.db import get_connection
from services.jobs.models.job import get_job, get_job_by_name
from services.jobs.service import create_job_with_default_config
from services.proposals.service import (
    DuplicateProposalError,
    ProposalConflictError,
    current_target,
    delete_proposal,
    persist_proposal,
    promote_proposal,
    proposed_item,
    reject_proposal,
    stage_proposal,
)
from tests.conftest import harness_cleanup, jobs_cleanup

RULE_CONTENT = {"body": "## Original body", "metadata": {"k": "v"}}

_clean_harness = harness_cleanup("propsvc_%")
_clean_jobs = jobs_cleanup("PROPSVC %")


@pytest.fixture(autouse=True)
def _clean_proposals():
    yield
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM improvement_proposals WHERE target_name LIKE 'propsvc_%' OR target_name LIKE 'PROPSVC %'"
            )


def rule_update_proposal(name: str, body: str = "## Improved body") -> dict:
    return {
        "target_kind": "rule",
        "action": "update",
        "target_name": name,
        "title": f"Improve {name}",
        "rationale": "Plans show this rule is repeatedly misread.",
        "evidence": [{"source": "plan", "id": "12", "note": "plan 12 discusses it"}],
        "body": body,
    }


def file_proposal(raw: dict) -> int:
    return persist_proposal(stage_proposal(raw))


# --- staging validation ---------------------------------------------------


def test_stage_rejects_bad_enums_and_empty_fields():
    base = rule_update_proposal("propsvc_x")
    for mutation in (
        {"target_kind": "tool"},
        {"action": "delete"},
        {"target_name": ""},
        {"title": ""},
        {"rationale": ""},
        {"body": ""},
        {"body": 42},
    ):
        with pytest.raises(ValueError):
            stage_proposal({**base, **mutation})


def test_stage_update_requires_existing_target():
    with pytest.raises(ValueError, match="does not exist"):
        stage_proposal(rule_update_proposal("propsvc_missing"))


def test_stage_create_requires_absent_target():
    upsert_item("rule", "propsvc_taken", content=RULE_CONTENT, agents=ALL_AGENTS)
    with pytest.raises(ValueError, match="already exists"):
        stage_proposal(
            {**rule_update_proposal("propsvc_taken"), "action": "create"}
        )


def test_stage_rejects_noop_update():
    upsert_item("rule", "propsvc_noop", content=RULE_CONTENT, agents=ALL_AGENTS)
    with pytest.raises(ValueError, match="changes nothing"):
        stage_proposal(rule_update_proposal("propsvc_noop", body=RULE_CONTENT["body"]))


def test_stage_drops_malformed_evidence():
    upsert_item("rule", "propsvc_evidence", content=RULE_CONTENT, agents=ALL_AGENTS)
    raw = rule_update_proposal("propsvc_evidence")
    raw["evidence"] = [
        {"source": "plan", "id": "1"},
        {"source": "twitter", "id": "2"},
        "garbage",
        {"source": "memory"},
    ]
    staged = stage_proposal(raw)
    assert [e["source"] for e in staged["evidence"]] == ["plan"]


def test_stage_dedups_against_pending():
    upsert_item("rule", "propsvc_dup", content=RULE_CONTENT, agents=ALL_AGENTS)
    file_proposal(rule_update_proposal("propsvc_dup"))
    with pytest.raises(DuplicateProposalError):
        stage_proposal(rule_update_proposal("propsvc_dup"))


# --- harness lifecycle ----------------------------------------------------


def test_harness_update_proposal_full_lifecycle():
    upsert_item("rule", "propsvc_life", content=RULE_CONTENT, agents=ALL_AGENTS)
    proposal_id = file_proposal(rule_update_proposal("propsvc_life"))

    proposal = get_proposal(proposal_id)
    assert proposal["status"] == "pending"
    assert proposal["base_version"] == 1

    # Proposed row exists, carries metadata/agents from the target, invisible to listings.
    row = proposed_item(proposal)
    assert row["state"] == "proposed" and row["version"] is None
    assert row["content"]["metadata"] == {"k": "v"}
    assert get_item("rule", "propsvc_life")["version"] == 1

    promoted = promote_proposal(proposal_id)
    assert promoted["status"] == "approved"
    assert promoted["applied_ref"] == {"item_type": "rule", "item_id": proposal["proposed_item_id"]}

    live = get_item("rule", "propsvc_life")
    assert live["id"] == proposal["proposed_item_id"]
    assert live["version"] == 2
    assert live["content"]["body"] == "## Improved body"
    assert len(get_version_history("rule", "propsvc_life")) == 2

    # Configs copied from the previous version.
    assert get_item_by_id("rule", live["id"])["configs"]


def test_harness_create_proposal_promotes_to_v1_with_default_config():
    proposal_id = file_proposal(
        {
            "target_kind": "skill",
            "action": "create",
            "target_name": "propsvc_newskill",
            "title": "Add skill",
            "rationale": "Memories show a recurring manual workflow.",
            "evidence": [],
            "body": "---\nname: propsvc_newskill\n---\nDo the thing.",
        }
    )
    assert get_item("skill", "propsvc_newskill") is None

    promote_proposal(proposal_id)
    live = get_item("skill", "propsvc_newskill")
    assert live["version"] == 1
    configs = get_item_by_id("skill", live["id"])["configs"]
    assert len(configs) == 1 and configs[0]["device"] == "*"


def test_promote_conflicts_when_target_version_bumped():
    upsert_item("rule", "propsvc_race", content=RULE_CONTENT, agents=ALL_AGENTS)
    proposal_id = file_proposal(rule_update_proposal("propsvc_race"))

    item = get_item("rule", "propsvc_race")
    update_content("rule", item["id"], {"body": "## Someone else edited", "metadata": {}})

    with pytest.raises(ProposalConflictError, match="changed"):
        promote_proposal(proposal_id)
    assert get_proposal(proposal_id)["status"] == "pending"


def test_promote_conflicts_when_target_deleted():
    upsert_item("rule", "propsvc_gone", content=RULE_CONTENT, agents=ALL_AGENTS)
    proposal_id = file_proposal(rule_update_proposal("propsvc_gone"))

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM harness_rules WHERE name = 'propsvc_gone' AND state = 'active'")

    with pytest.raises(ProposalConflictError, match="deleted"):
        promote_proposal(proposal_id)
    assert current_target(get_proposal(proposal_id)) is None


def test_reject_keeps_rows_and_blocks_refiling():
    upsert_item("rule", "propsvc_rej", content=RULE_CONTENT, agents=ALL_AGENTS)
    proposal_id = file_proposal(rule_update_proposal("propsvc_rej"))

    rejected = reject_proposal(proposal_id)
    assert rejected["status"] == "rejected"
    assert proposed_item(rejected)["state"] == "rejected"
    assert get_item("rule", "propsvc_rej")["version"] == 1

    with pytest.raises(DuplicateProposalError):
        stage_proposal(rule_update_proposal("propsvc_rej"))


def test_promote_requires_pending():
    upsert_item("rule", "propsvc_twice", content=RULE_CONTENT, agents=ALL_AGENTS)
    proposal_id = file_proposal(rule_update_proposal("propsvc_twice"))
    promote_proposal(proposal_id)
    with pytest.raises(ValueError, match="not pending"):
        promote_proposal(proposal_id)


def test_delete_pending_removes_both_rows():
    upsert_item("rule", "propsvc_del", content=RULE_CONTENT, agents=ALL_AGENTS)
    proposal_id = file_proposal(rule_update_proposal("propsvc_del"))
    proposed_id = get_proposal(proposal_id)["proposed_item_id"]

    delete_proposal(proposal_id)
    assert get_proposal(proposal_id) is None
    assert get_item_by_id("rule", proposed_id) is None


def test_delete_approved_keeps_promoted_content():
    upsert_item("rule", "propsvc_keep", content=RULE_CONTENT, agents=ALL_AGENTS)
    proposal_id = file_proposal(rule_update_proposal("propsvc_keep"))
    promote_proposal(proposal_id)

    delete_proposal(proposal_id)
    assert get_item("rule", "propsvc_keep")["version"] == 2


# --- job lifecycle ----------------------------------------------------------


def job_update_proposal(name: str, **fields) -> dict:
    return {
        "target_kind": "job",
        "action": "update",
        "target_name": name,
        "title": f"Tune {name}",
        "rationale": "Execution history shows the interval is too aggressive.",
        "evidence": [{"source": "memory", "id": "abc", "note": "noted repeatedly"}],
        **fields,
    }


def test_job_update_proposal_lifecycle():
    job_id = create_job_with_default_config("PROPSVC tune", {"hours": 1}, {"command": "echo hi"})
    proposal_id = file_proposal(job_update_proposal("PROPSVC tune", schedule_config={"hours": 8}))

    proposal = get_proposal(proposal_id)
    assert proposal["base_version"] == 1
    # Proposed row is the complete end-state: unspecified fields carried over.
    row = proposed_item(proposal)
    assert row["schedule_config"] == {"hours": 8}
    assert row["input_params"] == {"command": "echo hi"}

    promoted = promote_proposal(proposal_id)
    assert promoted["applied_ref"] == {"job_id": job_id}
    live = get_job(job_id)
    assert live["schedule_config"] == {"hours": 8}
    assert live["version"] == 2
    # Proposed row cleaned up after applying onto the target.
    assert get_job(proposal["proposed_item_id"]) is None


def test_job_update_conflicts_on_version_bump():
    from services.jobs.models.job import update_job

    create_job_with_default_config("PROPSVC race", {"hours": 1}, {"command": "echo hi"})
    proposal_id = file_proposal(job_update_proposal("PROPSVC race", schedule_config={"hours": 8}))

    update_job(get_job_by_name("PROPSVC race")["id"], description="bumped elsewhere")

    with pytest.raises(ProposalConflictError, match="changed"):
        promote_proposal(proposal_id)


def test_job_create_proposal_lifecycle():
    proposal_id = file_proposal(
        {
            "target_kind": "job",
            "action": "create",
            "target_name": "PROPSVC new",
            "title": "Add cleanup job",
            "rationale": "Plans mention recurring manual cleanup.",
            "evidence": [],
            "schedule_config": {"days": 1},
            "input_params": {"command": "echo cleanup"},
            "description": "proposed by improve graph",
        }
    )
    assert get_job_by_name("PROPSVC new") is None

    promoted = promote_proposal(proposal_id)
    live = get_job_by_name("PROPSVC new")
    assert live is not None
    assert promoted["applied_ref"] == {"job_id": live["id"]}


def test_job_create_requires_schedule_and_inputs():
    with pytest.raises(ValueError, match="requires schedule_config and input_params"):
        stage_proposal(
            {
                "target_kind": "job",
                "action": "create",
                "target_name": "PROPSVC partial",
                "title": "t",
                "rationale": "r",
                "schedule_config": {"days": 1},
            }
        )


def test_job_proposal_validates_graph_input_params():
    create_job_with_default_config("PROPSVC graphval", {"hours": 1}, {"command": "echo hi"})
    with pytest.raises(ValueError):
        stage_proposal(
            job_update_proposal(
                "PROPSVC graphval", input_params={"graph_type": "no_such_graph", "graph_inputs": {}}
            )
        )


# --- listings ---------------------------------------------------------------


def test_list_and_counts():
    upsert_item("rule", "propsvc_lists", content=RULE_CONTENT, agents=ALL_AGENTS)
    proposal_id = file_proposal(rule_update_proposal("propsvc_lists"))

    items, total = list_proposals(status="pending", limit=100)
    assert any(i["id"] == proposal_id for i in items) and total >= 1
    assert count_by_status()["pending"] >= 1

    with pytest.raises(AssertionError):
        list_proposals(status="bogus")
