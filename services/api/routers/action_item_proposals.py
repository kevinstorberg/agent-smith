from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query

from services.action_items import proposals
from services.api.models.action_item_proposal import (
    PROPOSAL_SORTS,
    ACTION_ITEM_PROPOSAL_STATUSES,
    count_by_status,
    get_proposal,
    list_proposals,
)
from services.api.models.shared.listing import sort_pattern
from services.api.routers.base import (
    delete_response,
    query_result,
    require_found,
    resolve_proposal,
)

router = APIRouter()


@router.get("")
def list_all(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    q: Annotated[str, Query(max_length=1000)] = "",
    sort: Annotated[str, Query(pattern=sort_pattern(PROPOSAL_SORTS))] = "newest",
):
    if status is not None and status not in ACTION_ITEM_PROPOSAL_STATUSES:
        raise HTTPException(
            422, f"status must be one of {ACTION_ITEM_PROPOSAL_STATUSES}"
        )
    items, total = query_result(
        list_proposals, status=status, limit=limit, offset=offset, q=q, sort=sort
    )
    return {"items": proposals.review_details(items), "total": total}


@router.get("/counts")
def counts():
    return count_by_status()


@router.get("/{proposal_id}")
def get_one(proposal_id: int = Path(gt=0)):
    proposal = require_found(
        get_proposal(proposal_id), "Action Item proposal", proposal_id
    )
    return {
        **proposals.review_details([proposal])[0],
        "current_target": proposals.current_target(proposal),
    }


@router.post("/{proposal_id}/approve")
def approve(proposal_id: int = Path(gt=0)):
    return resolve_proposal(proposals.promote_proposal, proposal_id)


@router.post("/{proposal_id}/reject")
def reject(proposal_id: int = Path(gt=0)):
    return resolve_proposal(proposals.reject_proposal, proposal_id)


@router.delete("/{proposal_id}")
def remove(proposal_id: int = Path(gt=0)):
    resolve_proposal(proposals.delete_proposal, proposal_id)
    return delete_response(proposal_id)
