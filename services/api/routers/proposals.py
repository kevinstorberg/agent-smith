"""REST API for improvement proposals: review queue + manual generation trigger."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query

from services.api.models.proposal import (
    PROPOSAL_STATUSES,
    count_by_status,
    get_proposal,
    list_proposals,
)
from services.api.routers.base import delete_response, list_response, require_found
from services.jobs.models.job import get_job_by_name
from services.jobs.scheduler import execute_job
from services.proposals.service import (
    ProposalConflictError,
    current_target,
    delete_proposal,
    promote_proposal,
    proposed_item,
    reject_proposal,
)

log = logging.getLogger("proposals.router")

router = APIRouter()

# The seeded background job the "Generate now" button triggers (see docs in
# the improve graph / plan §8: job_create(name="improvement-proposals", ...)).
GENERATE_JOB_NAME = "improvement-proposals"


def _require_pending(proposal_id: int) -> dict:
    proposal = require_found(get_proposal(proposal_id), "Proposal", proposal_id)
    if proposal["status"] != "pending":
        raise HTTPException(
            status_code=409, detail=f"Proposal {proposal_id} is {proposal['status']}, not pending"
        )
    return proposal


@router.get("")
def list_all(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    if status is not None and status not in PROPOSAL_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {PROPOSAL_STATUSES}")
    items, total = list_proposals(status=status, limit=limit, offset=offset)
    return list_response(items, total)


@router.get("/counts")
def counts():
    return count_by_status()


@router.get("/{proposal_id}")
def get_one(proposal_id: int):
    proposal = require_found(get_proposal(proposal_id), "Proposal", proposal_id)
    # One response powers the diff UI: the proposed row and the live target.
    proposal["proposed_item"] = proposed_item(proposal)
    proposal["current_target"] = current_target(proposal)
    return proposal


@router.post("/{proposal_id}/approve")
def approve(proposal_id: int):
    _require_pending(proposal_id)
    try:
        return promote_proposal(proposal_id)
    except ProposalConflictError as exc:
        # The proposal stays pending; the user decides whether to reject it.
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/{proposal_id}/reject")
def reject(proposal_id: int):
    _require_pending(proposal_id)
    return reject_proposal(proposal_id)


@router.delete("/{proposal_id}")
def remove(proposal_id: int):
    require_found(get_proposal(proposal_id), "Proposal", proposal_id)
    delete_proposal(proposal_id)
    return delete_response(proposal_id)


@router.post("/generate", status_code=202)
async def generate():
    """Manually trigger the improvement-proposals job.

    Runs as a background task — a graph run can take minutes, so awaiting it
    here (like jobs run-now does) would hang the browser. The execution record
    created by execute_job provides durable status in the Jobs UI.
    """
    job = get_job_by_name(GENERATE_JOB_NAME)
    if job is None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"No background job named '{GENERATE_JOB_NAME}'. Create it first, e.g. "
                f"job_create(name='{GENERATE_JOB_NAME}', schedule_config={{'hours': 4}}, "
                "input_params={'graph_type': 'improve', 'graph_inputs': "
                "{'project': '', 'lookback_days': 7, 'max_proposals': 5}})"
            ),
        )

    task = asyncio.create_task(execute_job(job), name=f"proposals-generate-{job['id']}")
    task.add_done_callback(_log_generate_outcome)
    return {"started": True, "job_id": job["id"]}


def _log_generate_outcome(task: asyncio.Task) -> None:
    # execute_job records its own execution row; this only surfaces task-level
    # surprises (e.g. cancellation) in the server log.
    if task.cancelled():
        log.warning("manual proposal generation cancelled")
    elif task.exception() is not None:
        log.error("manual proposal generation crashed", exc_info=task.exception())
