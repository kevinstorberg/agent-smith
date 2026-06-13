"""Plan feedback persistence and the opinion-review recorder (tracer bullet 1)."""
from __future__ import annotations

import pytest

from services.api.models.plan import create_plan, delete_plan, get_plan
from services.api.models.plan_feedback import (
    _derive_title,
    create_feedback,
    list_feedback_for_plan,
    record_opinion_review,
)
from services.db import get_connection


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM plan_feedback")
                cur.execute("DELETE FROM plans")
    _wipe()
    yield
    _wipe()


def test_create_and_list_feedback():
    plan_id = create_plan("Plan", "body", status="draft")
    fid = create_feedback(plan_id, "Looks solid, one risk...", source="opinion")
    assert fid > 0
    rows = list_feedback_for_plan(plan_id)
    assert len(rows) == 1
    assert rows[0]["body"] == "Looks solid, one risk..."
    assert rows[0]["source"] == "opinion"


def test_feedback_cascade_on_plan_delete():
    plan_id = create_plan("Plan", "body", status="draft")
    create_feedback(plan_id, "feedback")
    delete_plan(plan_id)
    assert list_feedback_for_plan(plan_id) == []


def test_record_opinion_review_creates_draft_and_feedback_untruncated():
    proposal = "# My Plan Title\n\n" + ("x" * 50000)  # oversized: must not truncate
    feedback = "y" * 40000
    plan_id, feedback_id = record_opinion_review(proposal, feedback)

    plan = get_plan(plan_id)
    assert plan["status"] == "draft"
    assert plan["title"] == "My Plan Title"
    assert plan["body"] == proposal  # byte-for-byte, no truncation

    rows = list_feedback_for_plan(plan_id)
    assert len(rows) == 1
    assert rows[0]["id"] == feedback_id
    assert rows[0]["body"] == feedback


def test_record_opinion_review_rejects_empty():
    with pytest.raises(AssertionError):
        record_opinion_review("", "feedback")
    with pytest.raises(AssertionError):
        record_opinion_review("proposal", "   ")


@pytest.mark.parametrize(
    ("proposal", "expected"),
    [
        ("# Heading\nbody", "Heading"),
        ("   \n\n## Second\nmore", "Second"),
        ("plain first line\nrest", "plain first line"),
        ("   \n\n   ", "Untitled draft"),
    ],
)
def test_derive_title(proposal, expected):
    assert _derive_title(proposal) == expected
