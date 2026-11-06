from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from services.db import get_connection
from services.meetings import db
from services.meetings.config import SourceConfig
from services.meetings.types import MeetingSummary
from tests.conftest import clean_meeting_rows


@pytest.fixture
def sorted_meetings():
    marker = "meeting-sort-" + uuid4().hex
    config = SourceConfig(marker, "test", marker, "never-used")
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    specs = [
        ("zulu", "Zulu", "Zoom", 1, 3),
        ("alpha", "alpha", "teams", 3, 1),
        ("ALPHA", "ALPHA", "Teams", 3, 1),
        (None, "bravo", "zoom", 2, 2),
        ("bravo", "Zulu", "Other", 4, 4),
    ]
    rows = []
    try:
        db.claim_source(config, "owner")
        for index, (
            title,
            connection,
            provider,
            calendar_day,
            updated_day,
        ) in enumerate(specs):
            saved = db.save_progress(
                config,
                "owner",
                {},
                summary=MeetingSummary(
                    str(index),
                    title,
                    marker,
                    None,
                    "https://example.test",
                    stamp + timedelta(days=20 - index),
                    stamp,
                ),
            )
            row_id = saved["id"]
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "UPDATE meeting_summaries SET source_name=%s, provider=%s, meeting_start=%s, updated_at=%s, labels=%s, project=%s WHERE id=%s",
                    (
                        connection,
                        provider,
                        stamp + timedelta(days=calendar_day) if index != 4 else None,
                        stamp + timedelta(days=updated_day),
                        ["release"],
                        "allowed" if index < 4 else "other",
                        saved["id"],
                    ),
                )
            rows.append(
                {
                    "id": row_id,
                    "title": title,
                    "connection": connection,
                    "provider": provider,
                    "date": stamp
                    + timedelta(days=calendar_day if index != 4 else 20 - index),
                    "updated": stamp + timedelta(days=updated_day),
                }
            )
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM meeting_summaries WHERE account_key=%s ORDER BY id",
                (marker,),
            )
            before = cur.fetchall()
        yield marker, rows, before
    finally:
        clean_meeting_rows(marker)


PAIRS = [
    ("title", "title_desc", "title"),
    ("connection_asc", "connection_desc", "connection"),
    ("provider_asc", "provider_desc", "provider"),
    ("date_asc", "date_desc", "date"),
    ("updated_asc", "updated", "updated"),
]


def expected(rows, key, descending):
    present = [row for row in rows if row[key] is not None]
    missing = [row for row in rows if row[key] is None]

    def value(row):
        item = row[key]
        return ((item.lower() if isinstance(item, str) else item), row["id"])

    return [
        row["id"]
        for row in sorted(present, key=value, reverse=descending)
        + sorted(missing, key=lambda row: row["id"], reverse=descending)
    ]


@pytest.mark.parametrize("ascending,descending,key", PAIRS)
@pytest.mark.parametrize("reverse", [False, True])
def test_meeting_header_order_is_global_filtered_null_last_and_read_only(
    sorted_meetings, ascending, descending, key, reverse
):
    marker, rows, before = sorted_meetings
    sort = descending if reverse else ascending
    pages = [
        db.list_summaries(
            query=marker, labels=["release"], sort=sort, limit=2, offset=offset
        )
        for offset in (0, 2, 4)
    ]
    assert [item["id"] for page in pages for item in page["items"]] == expected(
        rows, key, reverse
    )
    assert [page["total"] for page in pages] == [5, 5, 5]
    assert db.list_summaries(query=marker, sort=sort, limit=2, offset=99) == {
        "items": [],
        "total": 5,
    }
    assert db.list_summaries(query=marker, labels=["missing"], sort=sort)["total"] == 0
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM meeting_summaries WHERE account_key=%s ORDER BY id",
            (marker,),
        )
        assert cur.fetchall() == before


@pytest.mark.parametrize("sort", [token for pair in PAIRS for token in pair[:2]])
def test_meeting_route_accepts_header_sort_before_paging(sorted_meetings, sort):
    from services.api.app import app

    marker, rows, _ = sorted_meetings
    ascending, descending, key = next(pair for pair in PAIRS if sort in pair[:2])
    response = TestClient(app).get(
        "/api/meetings", params={"q": marker, "sort": sort, "limit": 2, "offset": 2}
    )
    assert response.status_code == 200
    assert response.json()["total"] == 5
    assert [row["id"] for row in response.json()["items"]] == expected(
        rows, key, sort == descending
    )[2:4]


@pytest.mark.parametrize(
    "sort", ["bad", "title;DROP TABLE meeting_summaries", "", None]
)
def test_meeting_core_refuses_untrusted_sort_before_database(monkeypatch, sort):
    def forbidden():
        pytest.fail("Invalid sort reached database boundary")

    monkeypatch.setattr(db, "_cursor", forbidden)
    with pytest.raises(ValueError, match="Sort must"):
        db.list_summaries(sort=sort)


@pytest.mark.parametrize("sort", ["bad", "title;DROP TABLE meeting_summaries", ""])
def test_meeting_http_refuses_unsupported_sort(sort):
    from services.api.app import app

    assert (
        TestClient(app).get("/api/meetings", params={"sort": sort}).status_code == 422
    )


def test_meeting_legacy_aliases_keep_original_orders():
    assert (
        db.MEETING_SORTS["newest"]
        == "COALESCE(meeting_start, provider_created_at) DESC, id"
    )
    assert (
        db.MEETING_SORTS["oldest"] == "COALESCE(meeting_start, provider_created_at), id"
    )


def test_meeting_sorts_preserve_source_project_calendar_and_availability_filters(
    sorted_meetings,
):
    marker, rows, _ = sorted_meetings
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE meeting_summaries SET available=false WHERE id=%s", (rows[1]["id"],)
        )
        cur.execute(
            "SELECT * FROM meeting_summaries WHERE account_key=%s ORDER BY id",
            (marker,),
        )
        before = cur.fetchall()
    for ascending, descending, _ in PAIRS:
        for sort in (ascending, descending, "newest", "oldest"):
            page = db.list_summaries(query=marker, sort=sort)
            assert page["total"] == 4
            assert rows[1]["id"] not in [item["id"] for item in page["items"]]
            scoped = db.list_summaries(
                query=marker, source="Zulu", project="allowed", sort=sort
            )
            assert scoped["total"] == 1
            assert [item["id"] for item in scoped["items"]] == [rows[0]["id"]]
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM meeting_summaries WHERE account_key=%s ORDER BY id",
            (marker,),
        )
        assert cur.fetchall() == before
