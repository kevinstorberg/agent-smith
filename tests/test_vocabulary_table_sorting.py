from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from services.db import get_connection
from services.meetings import vocabulary_db as db


@pytest.fixture
def terms():
    marker = uuid4().hex
    rows = [
        db.create(f"{name} {marker}", meaning)
        for name, meaning in [
            ("Zulu", "bravo"),
            ("alpha", "Alpha"),
            ("Éclair", "alpha"),
            ("Bravo", ""),
            ("charlie", "zulu"),
        ]
    ]
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM meeting_vocabulary WHERE id IN %s ORDER BY id",
                (tuple(row["id"] for row in rows),),
            )
            before = cur.fetchall()
        yield marker, rows, before
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM meeting_vocabulary WHERE id IN %s",
                (tuple(row["id"] for row in rows),),
            )


PAIRS = [
    ("term", "term_desc", "normalized_term"),
    ("definition_asc", "definition_desc", "definition"),
]


def expected(rows, key, reverse):
    present = [row for row in rows if row[key].strip()]
    missing = [row for row in rows if not row[key].strip()]
    ordered = sorted(
        present, key=lambda row: (row[key].lower(), row["id"]), reverse=reverse
    )
    return [
        row["id"]
        for row in ordered + sorted(missing, key=lambda row: row["id"], reverse=reverse)
    ]


@pytest.mark.parametrize("ascending,descending,key", PAIRS)
@pytest.mark.parametrize("reverse", [False, True])
def test_vocabulary_headers_sort_complete_filtered_rows_before_paging_without_writes(
    terms, ascending, descending, key, reverse
):
    marker, rows, before = terms
    sort = descending if reverse else ascending
    pages = [
        db.list_terms(query=marker, sort=sort, limit=2, offset=offset)
        for offset in (0, 2, 4)
    ]
    assert [item["id"] for page in pages for item in page["items"]] == expected(
        rows, key, reverse
    )
    assert [page["total"] for page in pages] == [5, 5, 5]
    assert db.list_terms(query=marker, sort=sort, limit=2, offset=99) == {
        "items": [],
        "total": 5,
    }
    defined = db.list_terms(query=marker, sort=sort, definition="defined")
    assert defined["total"] == 4
    assert [row["id"] for row in defined["items"]] == expected(
        [row for row in rows if row["definition"]], key, reverse
    )
    undefined = db.list_terms(query=marker, sort=sort, definition="undefined")
    assert undefined["total"] == 1 and undefined["items"][0]["id"] == rows[3]["id"]
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM meeting_vocabulary WHERE id IN %s ORDER BY id",
            (tuple(row["id"] for row in rows),),
        )
        assert cur.fetchall() == before


@pytest.mark.parametrize("sort", [token for pair in PAIRS for token in pair[:2]])
def test_vocabulary_route_accepts_header_pairs_and_keeps_legacy_updated(terms, sort):
    from services.api.routers.meeting_vocabulary import router

    app = FastAPI()
    app.include_router(router, prefix="/api/meetings/vocabulary")
    marker, rows, _ = terms
    ascending, descending, key = next(pair for pair in PAIRS if sort in pair[:2])
    response = TestClient(app).get(
        "/api/meetings/vocabulary",
        params={"q": marker, "sort": sort, "limit": 2, "offset": 2},
    )
    assert response.status_code == 200
    assert response.json()["total"] == 5
    assert [row["id"] for row in response.json()["items"]] == expected(
        rows, key, sort == descending
    )[2:4]
    assert db.list_terms(query=marker, sort="updated")["total"] == 5


@pytest.mark.parametrize(
    "sort", ["bad", "term;DROP TABLE meeting_vocabulary", "", None]
)
def test_vocabulary_invalid_sort_never_reaches_database(monkeypatch, sort):
    def forbidden():
        pytest.fail("Untrusted order reached database")

    monkeypatch.setattr(db, "_cursor", forbidden)
    with pytest.raises(ValueError):
        db.list_terms(sort=sort)
