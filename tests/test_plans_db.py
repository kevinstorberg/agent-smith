from __future__ import annotations

import pytest

from services.api.models.plan import (
    create_plan, get_plan, list_plans, search_plans, search_documents,
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


def test_status_defaults_to_final():
    plan = get_plan(create_plan("Final Plan", "body"))
    assert plan["status"] == "final"


def test_create_draft_status():
    plan = get_plan(create_plan("Draft Plan", "body", status="draft"))
    assert plan["status"] == "draft"


def test_list_filters_by_status():
    create_plan("a final", "body")
    create_plan("a draft", "body", status="draft")
    drafts, total = list_plans(status="draft")
    assert total == 1 and drafts[0]["status"] == "draft"
    finals, ftotal = list_plans(status="final")
    assert ftotal == 1 and finals[0]["status"] == "final"
    _, all_total = list_plans()
    assert all_total == 2


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


def test_search_combines_title_project_and_status_before_limit():
    target = create_plan("Security follow-up", "body", project="paralign", status="draft")
    create_plan("Security approved", "body", project="paralign", status="final")
    create_plan("Security elsewhere", "body", project="other", status="draft")
    rows = search_plans("security", "paralign", 1, status="draft")
    assert [row["id"] for row in rows] == [target]


def test_document_search_matches_all_keywords_across_title_and_body():
    target = create_plan("Security rollout", "Require MFA for administrators", project="Paralign")
    create_plan("Security only", "No second matching keyword", project="Paralign")
    create_plan("Unrelated title", "MFA only", project="Paralign")
    result = search_documents("  SECURITY\tMFA  ", project="Paralign")
    assert [row["id"] for row in result["items"]] == [target]
    assert result["has_more"] is False and result["next_offset"] is None
    assert result["items"][0]["excerpt"] == "Require MFA for administrators"
    assert set(result["items"][0]) == {"id", "title", "project", "status", "created_at", "updated_at", "excerpt"}
    assert get_plan(target)["body"] == "Require MFA for administrators"


@pytest.mark.parametrize("keyword", ["50%", "schema_name", r"path\name", "'", ".*", "' OR TRUE --"])
def test_document_search_treats_sql_and_regex_characters_as_literal_keywords(keyword):
    target = create_plan("Literal document", f"The literal search token is {keyword} and it matters")
    create_plan("Unrelated document", "The rate is 500; schemaXname; pathXname; OR TRUE")
    assert [row["id"] for row in search_documents(keyword)["items"]] == [target]


def test_document_search_scope_filters_run_before_pagination():
    first = create_plan("Review", "security", project="Paralign", status="draft")
    second = create_plan("Review", "security", project="Paralign", status="draft")
    create_plan("Review", "security", project="paralign", status="draft")
    create_plan("Review", "security", project="Paralign", status="final")
    first_page = search_documents("security", project="Paralign", status="draft", limit=1)
    assert [row["id"] for row in first_page["items"]] == [second]
    assert first_page["has_more"] is True and first_page["next_offset"] == 1
    second_page = search_documents("security", project="Paralign", status="draft", limit=1, offset=first_page["next_offset"])
    assert [row["id"] for row in second_page["items"]] == [first]
    assert second_page["has_more"] is False and second_page["next_offset"] is None


def test_document_search_order_is_stable_for_equal_update_times():
    from services.db import get_connection

    ids = [create_plan(f"Plan {index}", "shared keyword") for index in range(3)]
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE plans SET updated_at='2026-01-01T00:00:00Z' WHERE id IN %s", (tuple(ids),))
    assert [row["id"] for row in search_documents("shared")["items"]] == ids[::-1]
    assert [row["id"] for row in search_documents("shared", limit=1, offset=1)["items"]] == [ids[1]]


def test_document_search_excerpt_reaches_matches_beyond_the_prefix_without_returning_full_body():
    body = "prefix " * 1000 + "UNIQUE_NEEDLE" + " suffix" * 1000
    target = create_plan("Long document", body)
    result = search_documents("unique_needle")
    assert result["items"][0]["id"] == target
    excerpt = result["items"][0]["excerpt"]
    assert len(excerpt) == 600 and "UNIQUE_NEEDLE" in excerpt and excerpt in body
    assert "body" not in result["items"][0]
    assert get_plan(target)["body"] == body


def test_document_search_excerpt_includes_a_long_keyword_and_title_only_matches():
    keyword = "k" * 500
    body = "before " * 1000 + keyword + " after" * 1000
    target = create_plan("Long keyword", body)
    assert keyword in search_documents(keyword)["items"][0]["excerpt"]
    assert search_documents("  " + keyword + "  ")["items"][0]["id"] == target
    prefix = "Opening context. " * 100
    title_only = create_plan("TitleOnlyKeyword", prefix)
    assert search_documents("titleonlykeyword")["items"][0] == {
        **{key: value for key, value in get_plan(title_only).items() if key != "body"}, "excerpt": prefix[:600]}


def test_document_search_sees_edits_and_deletions_without_a_cache():
    target = create_plan("Original document", "Initial unique keyword")
    assert search_documents("unique")["items"][0]["id"] == target
    update_plan(target, body="Replacement fresh context")
    assert search_documents("unique")["items"] == []
    assert search_documents("fresh")["items"][0]["id"] == target
    delete_plan(target)
    assert search_documents("fresh") == {"items": [], "has_more": False, "next_offset": None, "pagination_capped": False}


def test_document_search_does_not_change_legacy_title_search_or_full_body_shape():
    target = create_plan("Legacy visible", "Body-only secret")
    assert search_plans("secret") == []
    assert search_plans("Legacy") == [get_plan(target)]
    assert search_plans("%") == [get_plan(target)]
    assert search_documents("secret")["items"][0]["id"] == target
    assert search_documents("%")["items"] == []


@pytest.mark.parametrize("arguments,message", [
    ({"query": ""}, "query"), ({"query": " \t\n "}, "query"), ({"query": None}, "query"),
    ({"query": 1}, "query"), ({"query": "x" * 501}, "query"),
    ({"query": " ".join(["keyword"] * 11)}, "10 whitespace-separated keywords"),
    ({"project": " "}, "project"), ({"project": "x" * 201}, "project"), ({"project": 1}, "project"),
    ({"status": "approved"}, "status"), ({"status": True}, "status"),
    ({"limit": 0}, "limit"), ({"limit": 21}, "limit"), ({"limit": True}, "limit"),
    ({"limit": "10"}, "limit"), ({"limit": 1.0}, "limit"),
    ({"offset": -1}, "offset"), ({"offset": 10001}, "offset"), ({"offset": True}, "offset"),
    ({"offset": "0"}, "offset"), ({"offset": 0.0}, "offset"),
])
def test_document_search_rejects_invalid_boundaries_before_opening_a_connection(monkeypatch, arguments, message):
    def forbidden():
        pytest.fail("Invalid search input must fail before accessing the database")

    monkeypatch.setattr("services.api.models.plan.get_connection", forbidden)
    with pytest.raises(ValueError, match=message):
        search_documents(**{"query": "keyword", **arguments})


def test_document_search_accepts_maximum_keywords_limits_and_offset():
    assert search_documents(" ".join(["keyword"] * 10), project="x" * 200, status="final", limit=20, offset=10000) == {
        "items": [], "has_more": False, "next_offset": None, "pagination_capped": False}


def test_document_search_reports_more_results_beyond_the_pagination_cap():
    from services.db import get_connection

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO plans(title,body) SELECT 'Capped document', 'unique capped keyword' FROM generate_series(1,10002)")
    before_cap = search_documents("capped", limit=1, offset=9999)
    assert before_cap["has_more"] is True and before_cap["next_offset"] == 10000
    assert before_cap["pagination_capped"] is False
    at_cap = search_documents("capped", limit=1, offset=10000)
    assert len(at_cap["items"]) == 1 and at_cap["has_more"] is True
    assert at_cap["next_offset"] is None and at_cap["pagination_capped"] is True
