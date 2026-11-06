from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from services.api.models.evals import create_suite, create_scenario, list_suites
from services.db import get_connection

ORDERS = [
    ("name", [1, 2, 4, 3, 5, 0]),
    ("name_desc", [0, 5, 3, 4, 2, 1]),
    ("type_asc", [2, 3, 1, 5, 4, 0]),
    ("type_desc", [0, 4, 5, 1, 3, 2]),
    ("scenario_count_asc", [2, 5, 4, 1, 3, 0]),
    ("scenario_count_desc", [0, 3, 1, 4, 5, 2]),
    ("enabled_asc", [1, 3, 5, 0, 2, 4]),
    ("enabled_desc", [4, 2, 0, 5, 3, 1]),
    ("updated_asc", [0, 4, 2, 3, 1, 5]),
    ("updated", [5, 1, 3, 2, 4, 0]),
    ("newest", [5, 1, 3, 2, 4, 0]),
]


@pytest.fixture
def ordered_suites():
    marker = "suite-sort-" + uuid4().hex
    specs = [
        ("zulu", "zulu", "beta", True, 10, 1),
        ("alpha", "alpha", "beta", False, 2, 3),
        ("ALPHA", "ALPHA", "alpha", True, 0, 2),
        ("charlie", "alpha", "alpha", False, 2, 2),
        ("bravo", "beta", "beta", True, 1, 1),
        ("delta", "beta", "alpha", False, 0, 4),
    ]
    ids = []
    try:
        for name, category, sub, enabled, count, day in specs:
            item_id = create_suite(
                f"{marker} {name}",
                category,
                sub,
                "Complete unchanged judge prompt" * 100,
                enabled=enabled,
            )
            ids.append(item_id)
            for index in range(count):
                create_scenario(
                    item_id,
                    f"child {index}",
                    "Full scenario prompt" * 100,
                    enabled=index % 2 == 0,
                )
            stamp = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=day)
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "UPDATE eval_suites SET created_at=%s,updated_at=%s WHERE id=%s",
                    (stamp, stamp, item_id),
                )
        yield marker, ids
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM eval_suites WHERE id=ANY(%s)", (ids,))


@pytest.mark.parametrize("sort,positions", ORDERS)
def test_suite_sort_is_global_and_stable_before_page(ordered_suites, sort, positions):
    marker, ids = ordered_suites
    pages = [
        list_suites(enabled_only=False, q=marker, sort=sort, limit=2, offset=offset)
        for offset in (0, 2, 4)
    ]
    assert [row["id"] for rows, _ in pages for row in rows] == [
        ids[i] for i in positions
    ]
    assert [total for _, total in pages] == [6, 6, 6]
    assert list_suites(enabled_only=False, q=marker, sort=sort, limit=2, offset=99) == (
        [],
        6,
    )
    assert all(
        "judge_prompt" not in row and "scenarios" not in row
        for rows, _ in pages
        for row in rows
    )


@pytest.mark.parametrize("sort,positions", ORDERS)
def test_suite_http_accepts_all_header_directions(ordered_suites, sort, positions):
    from services.api.app import app

    marker, ids = ordered_suites
    response = TestClient(app).get(
        "/api/eval-configs/suites",
        params={
            "enabled_only": False,
            "q": marker,
            "sort": sort,
            "limit": 2,
            "offset": 2,
        },
    )
    assert response.status_code == 200
    assert response.json()["total"] == 6
    assert [row["id"] for row in response.json()["items"]] == [
        ids[i] for i in positions[2:4]
    ]


def test_suite_order_preserves_filters_zero_counts_disabled_children_and_sources(
    ordered_suites,
):
    marker, ids = ordered_suites
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM eval_suites WHERE id=ANY(%s) ORDER BY id", (ids,))
        before = cur.fetchall()
        cur.execute(
            "SELECT * FROM eval_scenarios WHERE suite_id=ANY(%s) ORDER BY id", (ids,)
        )
        children = cur.fetchall()
    page, total = list_suites(
        enabled_only=False,
        enabled=False,
        q=marker,
        sort="scenario_count_desc",
        limit=2,
        offset=1,
    )
    assert total == 3 and [row["id"] for row in page] == [ids[1], ids[5]]
    all_rows, _ = list_suites(enabled_only=False, q=marker, sort="scenario_count_asc")
    assert [row["scenario_count"] for row in all_rows] == [0, 0, 1, 2, 2, 10]
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM eval_suites WHERE id=ANY(%s) ORDER BY id", (ids,))
        assert cur.fetchall() == before
        cur.execute(
            "SELECT * FROM eval_scenarios WHERE suite_id=ANY(%s) ORDER BY id", (ids,)
        )
        assert cur.fetchall() == children


@pytest.mark.parametrize(
    "sort", ["type", "scenario_count;DROP TABLE eval_suites", "name DESC", ""]
)
def test_suite_sort_rejects_untrusted_http_and_core_keys(monkeypatch, sort):
    from services.api.app import app
    from services.api.models import evals

    assert (
        TestClient(app)
        .get("/api/eval-configs/suites", params={"sort": sort})
        .status_code
        == 422
    )
    monkeypatch.setattr(
        evals, "get_connection", lambda: pytest.fail("Invalid sort reached SQL")
    )
    with pytest.raises(ValueError, match="Sort must be one of"):
        list_suites(sort=sort)


@pytest.mark.parametrize(
    "sort,positions",
    [("type_asc", [2, 3, 4, 5, 1, 0]), ("type_desc", [5, 1, 3, 2, 4, 0])],
)
def test_suite_type_empty_components_sort_last_in_both_directions(
    ordered_suites, sort, positions
):
    marker, ids = ordered_suites
    pairs = [
        ("", "x"),
        ("beta", ""),
        ("alpha", "a"),
        ("alpha", "z"),
        ("alpha", ""),
        ("beta", "b"),
    ]
    with get_connection() as conn, conn.cursor() as cur:
        for item_id, (category, subcategory) in zip(ids, pairs):
            cur.execute(
                "UPDATE eval_suites SET eval_type=%s,subcategory=%s WHERE id=%s",
                (category, subcategory, item_id),
            )
    pages = [
        list_suites(enabled_only=False, q=marker, sort=sort, limit=2, offset=offset)
        for offset in (0, 2, 4)
    ]
    assert [row["id"] for rows, _ in pages for row in rows] == [
        ids[i] for i in positions
    ]
    assert [total for _, total in pages] == [6, 6, 6]
