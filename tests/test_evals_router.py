from __future__ import annotations

import pytest
from datetime import datetime, timezone

from services.api.routers.evals import _build_filters


class TestBuildFilters:
    def test_no_args_returns_empty(self):
        where, params = _build_filters()
        assert where == ""
        assert params == []

    def test_single_filter(self):
        where, params = _build_filters(scenario="login")
        assert "scenario = %s" in where
        assert params == ["login"]

    def test_multiple_filters(self):
        where, params = _build_filters(scenario="login", model="claude")
        assert "scenario = %s" in where
        assert "test_model = %s" in where
        assert params == ["login", "claude"]

    def test_all_filters(self):
        where, params = _build_filters(
            scenario="s", model="m", eval_type="e",
            subcategory="sub", date_from="2026-01-01", date_to="2026-12-31",
        )
        assert where.startswith("WHERE ")
        assert len(params) == 6

    def test_date_filters(self):
        where, params = _build_filters(date_from="2026-01-01")
        assert "timestamp >= %s" in where
        assert params == ["2026-01-01"]


@pytest.fixture
def seed_eval_results():
    from evals.shared.db import save_result
    from services.db import get_connection

    ids = []
    for i, (etype, sub, scenario, model) in enumerate([
        ("harness", "rules", "login_flow", "claude"),
        ("harness", "rules", "login_flow", "codex"),
        ("harness", "skills", "search", "claude"),
    ]):
        eid = save_result(
            timestamp=datetime(2026, 1, i + 1, tzinfo=timezone.utc),
            eval_type=etype,
            subcategory=sub,
            scenario=scenario,
            test_model=model,
            judge_model="gpt-5.4",
            threshold=0.8,
            output="test output",
            results=[{"rule": f"rule_{i}", "score": 0.9 - i * 0.1}],
        )
        ids.append(eid)

    yield ids

    with get_connection() as conn:
        with conn.cursor() as cur:
            for eid in ids:
                cur.execute("DELETE FROM eval_results WHERE id = %s", (eid,))


class TestListEvals:
    def test_returns_items_and_total(self, seed_eval_results):
        from services.api.routers.evals import list_evals
        result = list_evals(scenario="", model="", eval_type="", subcategory="", date_from="", date_to="", limit=10, offset=0)
        assert "items" in result
        assert "total" in result
        assert result["total"] >= 3

    def test_items_have_score_avg(self, seed_eval_results):
        from services.api.routers.evals import list_evals
        result = list_evals(scenario="", model="", eval_type="", subcategory="", date_from="", date_to="", limit=10, offset=0)
        for item in result["items"]:
            assert "score_avg" in item
            assert "score_count" in item

    def test_filters_by_model(self, seed_eval_results):
        from services.api.routers.evals import list_evals
        result = list_evals(scenario="", model="claude", eval_type="", subcategory="", date_from="", date_to="", limit=10, offset=0)
        assert result["total"] >= 2
        for item in result["items"]:
            assert item["test_model"] == "claude"


class TestListCategories:
    def test_returns_list_of_strings(self, seed_eval_results):
        from services.api.routers.evals import list_categories
        result = list_categories()
        assert isinstance(result, list)
        assert "harness" in result


class TestListSubcategories:
    def test_returns_subcategories(self, seed_eval_results):
        from services.api.routers.evals import list_subcategories
        result = list_subcategories(eval_type="harness")
        assert "rules" in result

    def test_unfiltered_returns_all(self, seed_eval_results):
        from services.api.routers.evals import list_subcategories
        result = list_subcategories(eval_type="")
        assert "rules" in result
        assert "skills" in result


class TestChartData:
    def test_returns_scores_dict(self, seed_eval_results):
        from services.api.routers.evals import chart_data
        result = chart_data(eval_type="harness", scenario="login_flow", model="claude", subcategory="")
        assert len(result) >= 1
        item = result[0]
        assert "id" in item
        assert "timestamp" in item
        assert "scores" in item
        assert isinstance(item["scores"], dict)


class TestChartAverage:
    def test_returns_score_float(self, seed_eval_results):
        from services.api.routers.evals import chart_average
        result = chart_average(eval_type="harness", scenario="login_flow", model="claude", subcategory="")
        assert len(result) >= 1
        item = result[0]
        assert "score" in item
        assert isinstance(item["score"], float)


class TestGetEval:
    def test_found(self, seed_eval_results):
        from services.api.routers.evals import get_eval
        result = get_eval(seed_eval_results[0])
        assert result["id"] == seed_eval_results[0]

    def test_not_found(self):
        from fastapi import HTTPException
        from services.api.routers.evals import get_eval
        with pytest.raises(HTTPException) as exc_info:
            get_eval(999999)
        assert exc_info.value.status_code == 404


class TestDeleteEval:
    def test_deletes_row(self, seed_eval_results):
        from services.api.routers.evals import delete_eval
        eid = seed_eval_results[-1]
        result = delete_eval(eid)
        assert result["deleted"] is True
        seed_eval_results.pop()

    def test_not_found(self):
        from fastapi import HTTPException
        from services.api.routers.evals import delete_eval
        with pytest.raises(HTTPException) as exc_info:
            delete_eval(999999)
        assert exc_info.value.status_code == 404
