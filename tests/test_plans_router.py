"""Plans router: status filter + feedback attached to get_one (tracer bullet 3)."""
from __future__ import annotations

import pytest

from services.api.models.plan import create_plan
from services.api.models.plan_feedback import create_feedback
from services.api.routers.plans import get_one, list_all
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


def test_list_filters_by_status():
    create_plan("final one", "body")
    create_plan("draft one", "body", status="draft")

    drafts = list_all(project="", status="draft", limit=10, offset=0)
    assert drafts["total"] == 1
    assert drafts["items"][0]["status"] == "draft"

    everything = list_all(project="", status="", limit=10, offset=0)
    assert everything["total"] == 2


def test_get_one_attaches_feedback():
    plan_id = create_plan("Draft", "body", status="draft")
    create_feedback(plan_id, "full critique text")

    plan = get_one(plan_id)
    assert plan["status"] == "draft"
    assert len(plan["feedback"]) == 1
    assert plan["feedback"][0]["body"] == "full critique text"


def test_get_one_empty_feedback():
    plan_id = create_plan("Plain", "body")
    assert get_one(plan_id)["feedback"] == []
