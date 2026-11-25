from datetime import datetime, timezone
from uuid import UUID

import pytest

from services.db import get_connection
from services.meetings import labels_db
from services.memory import db
from tests.test_meetings_router import saved as saved
from tests.test_memory_pagination_regression import (
    catalog as catalog,
    client as client,
    forbid_listing_hydration,
)


def replace_metadata(index, id, **changes):
    index.rows[id]["metadata"].update(changes)
    meta = db.catalog_metadata(id, index.rows[id]["metadata"])
    try:
        meeting_id = str(UUID(meta["source_id"])) if meta["from_meeting"] else None
    except (ValueError, TypeError, AttributeError):
        meeting_id = None
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """UPDATE memory_catalog_entries SET tags=%s,source_type=%s,source_id=%s,
                meeting_id=%s,created_at=%s,updated_at=%s WHERE source_key=%s AND id=%s""",
            (
                meta["tags"],
                meta["source_type"],
                meta["source_id"],
                meeting_id,
                meta["created_at"],
                meta["updated_at"],
                index.source.key,
                id,
            ),
        )


def test_explicit_catalog_joins_live_meeting_labels_and_filters_mixed_own_context_tags(
    catalog,
    saved,
    monkeypatch,
):
    index = catalog(3)
    ids = list(index.rows)
    meeting_id = saved[1][0]["id"]
    labels_db.update(meeting_id, 0, ["security"])
    legacy_tags = [
        "meeting-memory",
        f"meeting:{UUID(meeting_id).hex.upper()}",
        "decision",
    ]
    replace_metadata(index, ids[0], source_type=None, source_id=None, tags=legacy_tags)
    replace_metadata(
        index, ids[1], source_type="general", source_id=meeting_id, tags=legacy_tags
    )
    replace_metadata(
        index,
        ids[2],
        source_type="meeting",
        source_id="unknown-origin",
        tags=["decision"],
    )
    forbid_listing_hydration(monkeypatch, index)
    first, total = db.list_page(tags=["decision", "security"], limit=1)
    assert total == 1
    row = first[0]
    assert row["id"] == ids[0] and row["source_id"] == meeting_id
    assert row["tags"] == ["decision"] and row["context_tags"] == ["security"]
    assert index.fetches == [[ids[0]]]

    labels_db.update(meeting_id, 1, ["product"])
    assert db.list_page(tags=["decision", "security"], limit=1) == ([], 0)
    assert index.fetches == [[ids[0]]]
    current, total = db.list_page(tags=["decision", "product"])
    assert total == 1
    assert current[0]["context_tags"] == ["product"]

    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE meeting_summaries SET available=false WHERE id=%s", (meeting_id,)
        )
    assert db.list_page(tags=["product"]) == ([], 0)
    assert index.fetches == [[ids[0]], [ids[0]]]
    assert index.pages == index.queries == index.touches == []


@pytest.mark.parametrize("field", ["created_at", "updated_at"])
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_explicit_catalog_keeps_missing_dates_and_ties_in_stable_global_order(
    catalog,
    monkeypatch,
    field,
    direction,
):
    index = catalog(4)
    ids = list(index.rows)
    tied = datetime(2026, 1, 2, tzinfo=timezone.utc).isoformat()
    replace_metadata(index, ids[0], **{field: None})
    replace_metadata(index, ids[1], **{field: tied})
    replace_metadata(index, ids[2], **{field: tied})
    replace_metadata(
        index, ids[3], **{field: datetime(2026, 1, 3, tzinfo=timezone.utc).isoformat()}
    )
    forbid_listing_hydration(monkeypatch, index)
    ordered = ids if direction == "asc" else [ids[3], ids[1], ids[2], ids[0]]
    for offset in range(4):
        rows, total = db.list_page(sort=f"{field}_{direction}", limit=1, offset=offset)
        assert total == 4
        assert [row["id"] for row in rows] == ordered[offset : offset + 1]
    assert index.fetches == [[id] for id in ordered]
    assert index.pages == index.queries == index.touches == []


def test_native_page_enriches_its_meeting_labels_without_catalog_readiness(
    catalog, client, saved, monkeypatch
):
    from services.memory import catalog as listing_catalog

    index = catalog(3, ready=False)
    index.forbid_listing = False
    ids = list(index.rows)
    meeting_id = saved[1][0]["id"]
    labels_db.update(meeting_id, 0, ["security"])
    index.rows[ids[0]]["metadata"].update(source_type="meeting", source_id=meeting_id)
    forbid_listing_hydration(monkeypatch, index)
    monkeypatch.setattr(
        listing_catalog,
        "select_page",
        lambda *a, **k: pytest.fail("Native browse read catalog"),
    )

    response = client.get("/api/memory/list", params={"limit": 2})

    assert response.status_code == 200
    assert [row["id"] for row in response.json()["items"]] == ids[:2]
    assert response.json()["items"][0]["context_tags"] == ["security"]
    assert index.fetches == [ids[:2]] and len(index.pages) == 1
    assert index.queries == index.touches == []
