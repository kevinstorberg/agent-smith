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


def test_pinecone_pages_join_live_meeting_labels_and_filter_mixed_own_context_tags(
    catalog,
    client,
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
    params = [("tags", "decision"), ("tags", "security"), ("limit", 1)]

    first = client.get("/api/memory/list", params=params)
    assert first.status_code == 200
    assert first.json()["total"] == 1
    row = first.json()["items"][0]
    assert row["id"] == ids[0] and row["source_id"] == meeting_id
    assert row["tags"] == ["decision"] and row["context_tags"] == ["security"]
    assert index.fetches == [[ids[0]]]

    labels_db.update(meeting_id, 1, ["product"])
    old_topic = client.get("/api/memory/list", params=params)
    assert old_topic.json() == {"items": [], "total": 0}
    assert index.fetches == [[ids[0]]]
    current = client.get("/api/memory/list", params={"tags": ["decision", "product"]})
    assert current.json()["total"] == 1
    assert current.json()["items"][0]["context_tags"] == ["product"]

    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE meeting_summaries SET available=false WHERE id=%s", (meeting_id,)
        )
    hidden = client.get("/api/memory/list", params={"tags": "product"})
    assert hidden.json() == {"items": [], "total": 0}
    assert index.fetches == [[ids[0]], [ids[0]]]
    assert index.pages == index.queries == index.touches == []


@pytest.mark.parametrize("field", ["created_at", "updated_at"])
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_pinecone_pages_keep_missing_dates_and_ties_in_stable_global_order(
    catalog,
    client,
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
        response = client.get(
            "/api/memory/list",
            params={"sort": f"{field}_{direction}", "limit": 1, "offset": offset},
        )
        assert response.status_code == 200
        assert response.json()["total"] == 4
        assert [row["id"] for row in response.json()["items"]] == ordered[
            offset : offset + 1
        ]
    assert index.fetches == [[id] for id in ordered]
    assert index.pages == index.queries == index.touches == []
