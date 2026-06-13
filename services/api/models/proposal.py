"""Improvement proposal master records.

A proposal row holds reasoning and review state only; the proposed content
itself lives as a state='proposed' row in the target table (harness_* or
background_jobs) referenced by ``proposed_item_id``.
"""
from __future__ import annotations

from services.api.models.base import BaseModel
from services.db import get_connection

PROPOSAL_STATUSES = ("pending", "approved", "rejected")


class ProposalModel(BaseModel):
    table = "improvement_proposals"
    json_fields = {"evidence", "applied_ref"}


def list_proposals(status: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
    where, params = "", ()
    if status:
        assert status in PROPOSAL_STATUSES, f"Invalid status: {status}"
        where, params = "WHERE status = %s", (status,)
    return ProposalModel.list(
        where=where, params=params, order_by="created_at DESC", limit=limit, offset=offset
    )


def count_by_status() -> dict[str, int]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status, COUNT(*) FROM improvement_proposals GROUP BY status")
            counts = dict(cur.fetchall())
    return {status: counts.get(status, 0) for status in PROPOSAL_STATUSES}


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
