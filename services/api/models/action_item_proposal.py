from __future__ import annotations

from functools import partial

from services.api.models.base import BaseModel
from services.api.models.shared.listing import bidirectional_sorts
from services.api.models.shared.proposal_reviews import (
    PROPOSAL_STATUSES,
    count_reviews,
    list_reviews,
)

ACTION_ITEM_PROPOSAL_STATUSES = (*PROPOSAL_STATUSES, "superseded")

PROPOSAL_SORTS = bidirectional_sorts(
    {
        ("title", "title_desc"): ("lower(title)",),
        ("action_asc", "action_desc"): ("lower(action)",),
        ("target_asc", "target_desc"): ("lower(target_name)",),
        ("oldest", "newest"): ("created_at",),
    }
)


class ActionItemProposalModel(BaseModel):
    table = "action_item_proposals"
    json_fields = {"evidence", "applied_ref"}


get_proposal = ActionItemProposalModel.read
list_proposals = partial(
    list_reviews,
    ActionItemProposalModel,
    PROPOSAL_SORTS,
    statuses=ACTION_ITEM_PROPOSAL_STATUSES,
)
count_by_status = partial(
    count_reviews, ActionItemProposalModel, statuses=ACTION_ITEM_PROPOSAL_STATUSES
)
