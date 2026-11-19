"""Harness and job improvement review records."""

from __future__ import annotations

from functools import partial

from services.api.models.base import BaseModel
from services.db import get_connection
from services.api.models.shared.listing import (
    bidirectional_sorts,
)

from services.api.models.shared.proposal_reviews import (
    PROPOSAL_STATUSES as PROPOSAL_STATUSES,
    count_reviews,
    list_reviews,
)

PROPOSAL_SORTS = bidirectional_sorts(
    {
        ("title", "title_desc"): ("lower(title)",),
        ("kind_asc", "kind_desc"): ("lower(target_kind)",),
        ("action_asc", "action_desc"): ("lower(action)",),
        ("target_asc", "target_desc"): ("lower(target_name)",),
        ("oldest", "newest"): ("created_at",),
    }
)


class ProposalModel(BaseModel):
    table = "improvement_proposals"
    json_fields = {"evidence", "applied_ref"}


list_proposals = partial(list_reviews, ProposalModel, PROPOSAL_SORTS)
count_by_status = partial(count_reviews, ProposalModel)


def existing_fingerprints(rejected_within_days: int = 30) -> set[str]:
    """Fingerprints the graph must not re-file: anything pending, plus
    recently rejected proposals so a dismissed idea doesn't reappear next run."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT fingerprint FROM improvement_proposals
                WHERE status = 'pending'
                   OR (status = 'rejected' AND created_at > now() - make_interval(days => %s))
                """,
                (rejected_within_days,),
            )
            return {row[0] for row in cur.fetchall()}


def recent_proposal_titles(rejected_within_days: int = 30) -> list[tuple[str, str]]:
    """(title, status) pairs fed to the agent prompt as dedup context."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT title, status FROM improvement_proposals
                WHERE status = 'pending'
                   OR (status = 'rejected' AND created_at > now() - make_interval(days => %s))
                ORDER BY created_at DESC
                """,
                (rejected_within_days,),
            )
            return [(row[0], row[1]) for row in cur.fetchall()]


# Convenience exports
get_proposal = ProposalModel.read
