from __future__ import annotations

import pytest

from services.api.models.plan import (
    create_plan, get_plan, list_plans, search_plans,
    update_plan, delete_plan,
)


@pytest.fixture(autouse=True)
def _clean_plans():
    from services.db import get_connection
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM plans")
    yield
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM plans")


def test_create_and_get():
    plan_id = create_plan("My Plan", "Some body text")
    plan = get_plan(plan_id)
    assert plan is not None
    assert plan["title"] == "My Plan"
    assert plan["body"] == "Some body text"
    assert plan["project"] is None


def test_create_with_project():
    plan_id = create_plan("Proj Plan", "body", project="my-project")
    plan = get_plan(plan_id)
    assert plan["project"] == "my-project"


def test_get_returns_none_for_missing():
    assert get_plan(99999) is None


def test_create_rejects_empty_title():
    with pytest.raises(AssertionError):
        create_plan("", "body")


def test_create_rejects_empty_body():
    with pytest.raises(AssertionError):
        create_plan("title", "")


def test_list_plans_pagination():
    for i in range(5):
        create_plan(f"Plan {i}", f"Body {i}")
    items, total = list_plans(limit=2, offset=0)
    assert total == 5
    assert len(items) == 2

    items2, _ = list_plans(limit=2, offset=2)
    assert len(items2) == 2
    assert items[0]["id"] != items2[0]["id"]


def test_list_plans_project_filter():
    create_plan("A", "body", project="alpha")
    create_plan("B", "body", project="beta")
    items, total = list_plans(project="alpha")
    assert total == 1
    assert items[0]["title"] == "A"


def test_search_plans():
    create_plan("Search Target", "body")
    create_plan("Other Plan", "body")
    results = search_plans("target")
    assert len(results) == 1
    assert results[0]["title"] == "Search Target"


def test_search_plans_case_insensitive():
    create_plan("Case Test", "body")
    results = search_plans("case test")
    assert len(results) == 1


def test_search_rejects_empty_query():
    with pytest.raises(AssertionError):
        search_plans("")


def test_update_plan_title():
    plan_id = create_plan("Original", "body")
    update_plan(plan_id, title="Updated")
    plan = get_plan(plan_id)
    assert plan["title"] == "Updated"
    assert plan["body"] == "body"


def test_update_plan_project():
    plan_id = create_plan("P", "body")
    update_plan(plan_id, project="new-proj")
    assert get_plan(plan_id)["project"] == "new-proj"


def test_update_plan_clear_project():
    plan_id = create_plan("P", "body", project="old")
    update_plan(plan_id, project=None)
    assert get_plan(plan_id)["project"] is None


def test_delete_plan():
    plan_id = create_plan("To Delete", "body")
    delete_plan(plan_id)
    assert get_plan(plan_id) is None
