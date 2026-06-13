"""REST router tests for improvement proposals (tracer bullet 6).

Follows the repo convention of calling route handlers directly rather than
booting the app through a TestClient.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from services.api.models.shared.harness import get_item, update_content, upsert_item
from services.api.routers.proposals import (
    GENERATE_JOB_NAME,
    approve,
    counts,
    generate,
    get_one,
    list_all,
    reject,
    remove,
)
from services.config import ALL_AGENTS
from services.db import get_connection
from services.jobs.models.job import delete_job
from services.jobs.service import create_job_with_default_config
from services.proposals.service import persist_proposal, stage_proposal
from tests.conftest import harness_cleanup

RULE_CONTENT = {"body": "## Router test rule", "metadata": {}}

_clean = harness_cleanup("proprouter_%")


@pytest.fixture(autouse=True)
def _clean_proposals():
    yield
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM improvement_proposals WHERE target_name LIKE 'proprouter_%'")


def _file_rule_update(name: str) -> int:
    upsert_item("rule", name, content=RULE_CONTENT, agents=ALL_AGENTS)
    return persist_proposal(
        stage_proposal(
            {
                "target_kind": "rule",
                "action": "update",
                "target_name": name,
                "title": f"Improve {name}",
                "rationale": "Recent plans show confusion.",
                "evidence": [{"source": "plan", "id": "9", "note": "see plan 9"}],
                "body": "## Router test rule, clarified",
            }
        )
    )


def test_list_filters_by_status_and_validates_enum():
    proposal_id = _file_rule_update("proprouter_list")

    pending = list_all(status="pending", limit=100, offset=0)
    assert any(i["id"] == proposal_id for i in pending["items"])

    approved = list_all(status="approved", limit=100, offset=0)
    assert not any(i["id"] == proposal_id for i in approved["items"])

    with pytest.raises(HTTPException) as err:
        list_all(status="bogus", limit=50, offset=0)
    assert err.value.status_code == 422


def test_counts_shape():
    _file_rule_update("proprouter_counts")
    result = counts()
    assert set(result) == {"pending", "approved", "rejected"}
    assert result["pending"] >= 1


def test_get_one_includes_diff_payloads():
    proposal_id = _file_rule_update("proprouter_diff")

    proposal = get_one(proposal_id)

    assert proposal["proposed_item"]["content"]["body"] == "## Router test rule, clarified"
    assert proposal["current_target"]["content"]["body"] == "## Router test rule"
    assert proposal["current_target"]["version"] == 1


def test_get_one_404():
    with pytest.raises(HTTPException) as err:
        get_one(99999999)
    assert err.value.status_code == 404


def test_approve_applies_and_blocks_double_review():
    proposal_id = _file_rule_update("proprouter_approve")

    approved = approve(proposal_id)
    assert approved["status"] == "approved"
    assert get_item("rule", "proprouter_approve")["version"] == 2

    for action in (approve, reject):
        with pytest.raises(HTTPException) as err:
            action(proposal_id)
        assert err.value.status_code == 409


def test_approve_conflict_returns_409_and_stays_pending():
    proposal_id = _file_rule_update("proprouter_conflict")
    item = get_item("rule", "proprouter_conflict")
    update_content("rule", item["id"], {"body": "## Edited elsewhere", "metadata": {}})

    with pytest.raises(HTTPException) as err:
        approve(proposal_id)
    assert err.value.status_code == 409
    assert get_one(proposal_id)["status"] == "pending"


def test_reject_records_status():
    proposal_id = _file_rule_update("proprouter_reject")
    assert reject(proposal_id)["status"] == "rejected"


def test_remove_deletes():
    proposal_id = _file_rule_update("proprouter_remove")
    assert remove(proposal_id) == {"deleted": True, "id": proposal_id}
    with pytest.raises(HTTPException):
        get_one(proposal_id)


def test_generate_409_when_job_missing():
    with pytest.raises(HTTPException) as err:
        asyncio.run(generate())
    assert err.value.status_code == 409
    assert GENERATE_JOB_NAME in err.value.detail


@pytest.mark.asyncio
async def test_generate_starts_background_execution():
    # A command job under the reserved name keeps this test independent of the
    # LLM stack; generate only resolves the job and fires execute_job.
    job_id = create_job_with_default_config(
        GENERATE_JOB_NAME, {"hours": 4}, {"command": "echo generated"}
    )
    try:
        response = await generate()
        assert response == {"started": True, "job_id": job_id}

        from services.jobs.models.execution import list_executions_for_job

        for _ in range(50):
            items, total = list_executions_for_job(job_id, limit=5)
            if total and items[0]["status"] == "success":
                break
            await asyncio.sleep(0.1)
        assert total == 1
        assert items[0]["status"] == "success"
        assert "generated" in items[0]["result"]["output"]
    finally:
        delete_job(job_id)
