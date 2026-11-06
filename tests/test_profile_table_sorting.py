from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from psycopg2.extras import Json
import pytest

from services.db import get_connection
from services.meetings import digestion_db, profile_db
from tests.test_meeting_profiles_db import ready_meeting
from tests.test_meeting_sync import source as source


PAIRS = [
    ("starred_asc", "starred_desc", "starred"),
    ("name_asc", "name_desc", "display_name"),
    ("email_asc", "email_desc", "email"),
    ("identity_asc", "identity_desc", "identity_scope"),
    ("tags_asc", "tags_desc", "tags"),
    ("meeting_count_asc", "meeting_count_desc", "meeting_count"),
    ("updated_at_asc", "updated_at_desc", "updated_at"),
]


@pytest.fixture
def sorted_profiles(source):
    marker = "profile-sort-" + uuid4().hex
    meeting_ids = [ready_meeting(source, suffix) for suffix in ("one", "two", "hidden")]
    sources = [
        {
            "meeting_id": meeting_id,
            "transcript_hash": digestion_db.get_record(meeting_id)["transcript_hash"],
            "participants_revision": 0,
        }
        for meeting_id in meeting_ids
    ]
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    names = ["Zulu", "alpha", "ALPHA", "Bravo", "Charlie", "Deleted", "Merged"]
    emails = [
        "zulu@example.test",
        None,
        "Alpha@example.test",
        None,
        "bravo@example.test",
        None,
        None,
    ]
    scopes = ["email", "manual", "email", "meeting", "email", "manual", "manual"]
    tags = [["Zulu", "alpha"], ["bravo"], [], ["ALPHA", "zulu"], ["alpha"], [], []]
    ids, rows = [], []
    try:
        for index, name in enumerate(names):
            row = profile_db.create_profile(name + " " + marker)
            ids.append(row["id"])
            claims = []
            if index == 0:
                claims = [sources[0], sources[0]]
            elif index == 1:
                claims = [sources[0], sources[1]]
            elif index == 3:
                claims = [
                    sources[2],
                    {**sources[0], "transcript_hash": "wrong"},
                    {**sources[0], "superseded": True},
                ]
            elif index == 4:
                claims = [
                    {
                        key: value
                        for key, value in sources[0].items()
                        if key != "participants_revision"
                    }
                ]
            metadata = {"company": "Source metadata"} if index in (2, 4) else {}
            provenance = (
                {"company": sources[1 if index == 2 else 0]} if metadata else {}
            )
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(
                    """UPDATE participant_profiles SET email=%s, identity_scope=%s, tags=%s,
                       starred=%s, updated_at=%s, claims=%s, metadata=%s, metadata_provenance=%s
                       WHERE id=%s""",
                    (
                        emails[index],
                        scopes[index],
                        tags[index],
                        index in (0, 2),
                        stamp + timedelta(days=index % 3),
                        Json(claims),
                        Json(metadata),
                        Json(provenance),
                        row["id"],
                    ),
                )
            if index < 5:
                rows.append(
                    {
                        "id": row["id"],
                        "display_name": name + " " + marker,
                        "email": emails[index],
                        "identity_scope": scopes[index],
                        "tags": tags[index],
                        "starred": index in (0, 2),
                        "updated_at": stamp + timedelta(days=index % 3),
                        "meeting_count": (1, 2, 1, 0, 1)[index],
                        "claim_count": (2, 2, 0, 0, 1)[index],
                    }
                )
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE meeting_summaries SET available=false WHERE id=%s",
                (meeting_ids[2],),
            )
            cur.execute(
                "UPDATE participant_profiles SET deleted=true WHERE id=%s", (ids[5],)
            )
            cur.execute(
                "UPDATE participant_profiles SET merged_into=%s WHERE id=%s",
                (ids[0], ids[6]),
            )
            cur.execute(
                "SELECT * FROM participant_profiles WHERE id IN %s ORDER BY id",
                (tuple(ids),),
            )
            before = cur.fetchall()
        yield marker, rows, before, ids, meeting_ids
    finally:
        if ids:
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM participant_profiles WHERE id IN %s", (tuple(ids),)
                )


def expected(rows, key, reverse):
    def value(row):
        item = row[key]
        if key == "tags":
            return tuple(sorted(tag.lower() for tag in item)) or None
        return item.lower() if isinstance(item, str) else item

    present = [row for row in rows if value(row) is not None]
    missing = [row for row in rows if value(row) is None]
    legacy_tie = key in {"display_name", "updated_at"}
    ordered = sorted(
        present, key=lambda row: row["id"], reverse=reverse and not legacy_tie
    )
    ordered.sort(key=value, reverse=reverse)
    return [
        row["id"]
        for row in ordered + sorted(missing, key=lambda row: row["id"], reverse=reverse)
    ]


@pytest.mark.parametrize("ascending,descending,key", PAIRS)
@pytest.mark.parametrize("reverse", [False, True])
def test_profile_headers_sort_before_paging_with_exact_visible_counts_and_no_writes(
    sorted_profiles, ascending, descending, key, reverse
):
    marker, rows, before, ids, _ = sorted_profiles
    pages = [
        profile_db.list_profiles(
            query=marker,
            sort=descending if reverse else ascending,
            limit=2,
            offset=offset,
        )
        for offset in (0, 2, 4)
    ]
    actual = [item for page in pages for item in page["items"]]
    assert [item["id"] for item in actual] == expected(rows, key, reverse)
    assert [page["total"] for page in pages] == [5, 5, 5]
    assert len({item["id"] for item in actual}) == 5
    assert {
        item["id"]: (item["meeting_count"], item["claim_count"]) for item in actual
    } == {row["id"]: (row["meeting_count"], row["claim_count"]) for row in rows}
    assert all("claims" not in item for item in actual)
    assert profile_db.list_profiles(
        query=marker, sort=descending if reverse else ascending, offset=99
    ) == {"items": [], "total": 5}
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM participant_profiles WHERE id IN %s ORDER BY id",
            (tuple(ids),),
        )
        assert cur.fetchall() == before


@pytest.mark.parametrize("sort", [token for pair in PAIRS for token in pair[:2]])
def test_profile_route_accepts_global_header_sort_and_preserves_filters(
    sorted_profiles, sort
):
    from services.api.app import app

    marker, rows, _, _, _ = sorted_profiles
    ascending, descending, key = next(pair for pair in PAIRS if sort in pair[:2])
    response = TestClient(app).get(
        "/api/profiles", params={"q": marker, "sort": sort, "limit": 2, "offset": 2}
    )
    assert response.status_code == 200
    assert response.json()["total"] == 5
    assert [item["id"] for item in response.json()["items"]] == expected(
        rows, key, sort == descending
    )[2:4]
    starred = profile_db.list_profiles(query=marker, starred=True, sort=sort)
    assert starred["total"] == 2
    assert {item["id"] for item in starred["items"]} == {
        row["id"] for row in rows if row["starred"]
    }
    tagged = profile_db.list_profiles(query=marker, tags=["alpha"], sort=sort)
    assert tagged["total"] == 2


@pytest.mark.parametrize("change", ["withdrawn", "deleted", "hash", "attribution"])
def test_meeting_count_sort_never_resurrects_invalid_source_claims_or_metadata(
    sorted_profiles, change
):
    marker, rows, _, _, meetings = sorted_profiles
    from tests.test_profile_source_visibility import invalidate

    invalidate(meetings[0], change)
    listed = profile_db.list_profiles(query=marker, sort="meeting_count_desc")
    assert listed["total"] == 5
    assert {item["id"]: item["meeting_count"] for item in listed["items"]} == {
        row["id"]: (1 if index in (1, 2) else 0) for index, row in enumerate(rows)
    }
    assert (
        next(item for item in listed["items"] if item["id"] == rows[4]["id"])[
            "metadata"
        ]
        == {}
    )


@pytest.mark.parametrize(
    "sort", ["bad", "email;DROP TABLE participant_profiles", "", None]
)
def test_profile_sort_rejects_invalid_values_before_database(monkeypatch, sort):
    def forbidden():
        pytest.fail("Untrusted sort reached database")

    monkeypatch.setattr(profile_db, "_cursor", forbidden)
    with pytest.raises(ValueError):
        profile_db.list_profiles(sort=sort)


def test_profile_legacy_sort_contracts_remain_accepted():
    assert (
        profile_db.PROFILE_SORTS[profile_db.DEFAULT_PROFILE_SORT]
        == "{alias}.starred DESC, lower({alias}.display_name) ASC"
    )
    assert profile_db.PROFILE_SORTS["created_at_desc"] == "{alias}.created_at DESC"
