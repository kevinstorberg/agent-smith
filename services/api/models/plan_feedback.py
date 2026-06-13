"""Feedback returned by a graph (e.g. the opinion graph) for a plan.

A ``plan_feedback`` row holds the full, untruncated critique linked by FK to the
draft ``plans`` row that was reviewed. ``record_opinion_review`` is the single
persistence entry point the opinion graph delegates to, keeping the graph node
free of storage details.
"""
from __future__ import annotations

from psycopg2.extras import RealDictCursor

from services.api.models.base import BaseModel
from services.api.models.plan import PlanModel
from services.db import get_connection


class PlanFeedbackModel(BaseModel):
    table = "plan_feedback"


def create_feedback(plan_id: int, body: str, source: str = "opinion", conn=None) -> int:
    PlanFeedbackModel._validate_required({"body": body}, ["body"])
    return PlanFeedbackModel.create(conn=conn, plan_id=plan_id, body=body, source=source)


def list_feedback_for_plan(plan_id: int) -> list[dict]:
    PlanFeedbackModel._validate_id(plan_id)
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM plan_feedback WHERE plan_id = %s ORDER BY created_at",
                (plan_id,),
            )
            return [PlanFeedbackModel.serialize_timestamps(dict(r)) for r in cur.fetchall()]


def _derive_title(proposal: str) -> str:
    for line in proposal.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped
    return "Untitled draft"


def record_opinion_review(proposal: str, feedback: str, source: str = "opinion") -> tuple[int, int]:
    """Persist an opinion review: a draft plan (full proposal) plus its linked
    feedback (full critique), atomically. Returns (plan_id, feedback_id).

    Nothing is truncated — the proposal becomes the draft body verbatim and the
    feedback becomes the plan_feedback body verbatim.
    """
    assert isinstance(proposal, str) and proposal.strip(), "proposal must be a non-empty string"
    assert isinstance(feedback, str) and feedback.strip(), "feedback must be a non-empty string"

    with get_connection() as conn:
        plan_id = PlanModel.create(
            conn=conn,
            title=_derive_title(proposal),
            body=proposal,
            project=None,
            status="draft",
        )
        assert plan_id > 0, "draft plan insert returned no id"
        feedback_id = create_feedback(plan_id, feedback, source=source, conn=conn)
    return plan_id, feedback_id
