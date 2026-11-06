from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from evals.shared.db import save_result
from services.api.routers.evals import list_evals
from services.db import get_connection


ORDERS = [
    ("oldest", [1, 2, 0, 4, 5, 3]),
    ("newest", [3, 5, 4, 0, 2, 1]),
    ("category_asc", [2, 3, 1, 4, 5, 0]),
    ("category_desc", [0, 5, 4, 1, 3, 2]),
    ("scenario_asc", [1, 2, 3, 4, 0, 5]),
    ("scenario_desc", [0, 4, 3, 2, 1, 5]),
    ("model_asc", [1, 2, 3, 4, 0, 5]),
    ("model_desc", [0, 4, 3, 2, 1, 5]),
    ("threshold_asc", [3, 4, 5, 1, 2, 0]),
    ("threshold_desc", [0, 2, 1, 5, 4, 3]),
    ("score_asc", [4, 5, 1, 3, 0, 2]),
    ("score", [0, 3, 1, 5, 4, 2]),
]


@pytest.fixture
def ordered_results():
    marker = "result-sort-" + uuid4().hex
    specs = [
        ("zulu", "beta", "Zulu", "Zulu", 10, [10, 8], 2),
        ("alpha", "beta", "alpha", "alpha", 2, [2], 1),
        ("ALPHA", "alpha", "ALPHA", "ALPHA", 2, [], 1),
        ("alpha", "alpha", "Bravo", "Beta", -1, [1, 3], 3),
        ("beta", None, "bravo", "beta", 0.01, [1.23441], 2),
        ("beta", "", "", "", 0.01, [1.23449], 2),
    ]
    ids = []
    try:
        for category, sub, scenario, model, threshold, scores, day in specs:
            ids.append(
                save_result(
                    timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc)
                    + timedelta(days=day),
                    eval_type=f"{marker} {category}",
                    subcategory=sub,
                    scenario=scenario,
                    test_model=model,
                    judge_model="offline judge",
                    threshold=threshold,
                    output="Complete unchanged output" * 100,
                    results=[
                        {"rule": str(i), "score": score}
                        for i, score in enumerate(scores)
                    ],
                )
            )
        yield marker, ids
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM eval_results WHERE id=ANY(%s)", (ids,))


def read_results(**overrides):
    return list_evals(
        **{
            "scenario": "",
            "model": "",
            "eval_type": "",
            "subcategory": "",
            "date_from": "",
            "date_to": "",
            "q": "",
            "sort": "newest",
            "limit": 2,
            "offset": 0,
            **overrides,
        }
    )


@pytest.mark.parametrize("sort,positions", ORDERS)
def test_result_sort_is_global_stable_and_null_last_before_page(
    ordered_results, sort, positions
):
    marker, ids = ordered_results
    pages = [read_results(q=marker, sort=sort, offset=offset) for offset in (0, 2, 4)]
    assert [row["id"] for page in pages for row in page["items"]] == [
        ids[i] for i in positions
    ]
    assert [page["total"] for page in pages] == [6, 6, 6]
    assert read_results(q=marker, sort=sort, offset=99) == {"items": [], "total": 6}
    assert all(
        "results" not in row and "output" not in row
        for page in pages
        for row in page["items"]
    )


@pytest.mark.parametrize("sort,positions", ORDERS)
def test_result_http_accepts_all_header_directions(ordered_results, sort, positions):
    from services.api.app import app

    marker, ids = ordered_results
    response = TestClient(app).get(
        "/api/evals", params={"q": marker, "sort": sort, "limit": 2, "offset": 2}
    )
    assert response.status_code == 200
    assert response.json()["total"] == 6
    assert [row["id"] for row in response.json()["items"]] == [
        ids[i] for i in positions[2:4]
    ]


def test_sort_preserves_filters_complete_chart_and_stored_source(ordered_results):
    from services.api.app import app

    marker, ids = ordered_results
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM eval_results WHERE id=ANY(%s) ORDER BY id", (ids,))
        before = cur.fetchall()
    page = read_results(q=marker, sort="threshold_asc", scenario="alpha", limit=1)
    assert page["total"] == 1 and page["items"][0]["id"] == ids[1]
    client = TestClient(app)
    chart = client.get("/api/evals/chart", params={"q": marker})
    assert chart.status_code == 200 and len(chart.json()) == 6
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM eval_results WHERE id=ANY(%s) ORDER BY id", (ids,))
        assert cur.fetchall() == before


@pytest.mark.parametrize(
    "sort", ["threshold", "score;DROP TABLE eval_results", "scenario DESC", ""]
)
def test_result_sort_rejects_invalid_http_and_core_keys(monkeypatch, sort):
    from services.api.app import app
    from services.api.routers import evals

    assert TestClient(app).get("/api/evals", params={"sort": sort}).status_code == 422
    monkeypatch.setattr(
        evals, "get_connection", lambda: pytest.fail("Invalid sort reached SQL")
    )
    with pytest.raises(HTTPException) as error:
        read_results(sort=sort)
    assert getattr(error.value, "status_code", None) == 422
    from services.api.models.shared.listing import sort_clause

    with pytest.raises(ValueError, match="Sort must be one of"):
        sort_clause(sort, evals.RESULT_SORTS)
