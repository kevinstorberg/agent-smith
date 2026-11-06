from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from functools import cmp_to_key
from typing import get_args
from uuid import uuid4

from psycopg2.extras import Json
import pytest

from services.db import get_connection
from services.meetings import digestion_db, profile_db
from services.meetings.outputs import ProfileCategory, ProfileClaimSort
from tests.test_meeting_profiles_db import (
    claimed as claimed,
    participants as participants,
    ready_meeting,
)
from tests.test_meeting_profiles_router import applied as applied
from tests.test_meeting_sync import source as source
from tests.test_profiles_router import client as client


PAIRS = [
    (f"{key}_asc", f"{key}_desc", key)
    for key in ("observation", "type", "confidence", "review", "source")
]
CATEGORY_LABELS = {
    "driver": "Drivers",
    "priority": "Priorities",
    "communication": "Communication",
    "decision_pattern": "Decision patterns",
    "perception": "Perceptions",
    "interaction": "Interactions",
    "uncertainty": "Uncertainties",
    "strength": "Strengths",
    "development_area": "Development areas",
    "relationship": "Relationship evidence",
    "role": "Roles and organizations",
}
EPISTEMIC_LABELS = {
    "self_report": "Self-reported",
    "observed": "Observed",
    "inference": "Hypothesis",
}
REVIEW_LABELS = {
    "active": "Active",
    "corrected": "Corrected by you",
    "rejected": "Rejected by you",
}


@pytest.fixture
def sortable_evidence(applied, source):
    first_meeting, profile = applied
    meetings = [
        first_meeting,
        *(ready_meeting(source, f"sort-{i}") for i in range(1, 5)),
    ]
    sources = [
        {
            "meeting_id": meeting,
            "transcript_hash": digestion_db.get_record(meeting)["transcript_hash"],
            "participants_revision": 0,
        }
        for meeting in meetings
    ]
    titles = ["Zulu", "alpha", "ALPHA", None, "Hidden source"]
    dates = [
        datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=day)
        for day in (2, 3, 1, 4, 0)
    ]
    categories = get_args(ProfileCategory)
    original = profile["claims"][0]
    claims = []
    for index in range(45):
        status = ("active", "corrected", "rejected", "active")[index % 4]
        item = {
            **deepcopy(original),
            **sources[index % 5],
            "id": str(uuid4()),
            "content": f"Original observation {44 - index:02d}",
            "category": categories[index % len(categories)],
            "epistemic": ("observed", "self_report", "inference")[index % 3],
            "confidence": ("high", "medium", "low")[index % 3],
            "status": status,
            "source_url": f"https://example.test/source-{index % 5}",
        }
        item["correction"] = (
            {
                "action": "correct" if status == "corrected" else "reject",
                "content": f"Corrected observation {index:02d}"
                if status == "corrected"
                else None,
                "reason": "Human clarification",
            }
            if status != "active"
            else None
        )
        if index == 3:
            item["transcript_hash"] = "withdrawn"
        if index == 6:
            item["superseded"] = True
        if index == 7:
            item.pop("participants_revision")
        claims.append(item)
    with get_connection() as conn, conn.cursor() as cur:
        for index, meeting in enumerate(meetings):
            cur.execute(
                "UPDATE meeting_summaries SET title=%s, provider_created_at=%s, available=%s WHERE id=%s",
                (titles[index], dates[index], index != 4, meeting),
            )
        cur.execute(
            "UPDATE participant_profiles SET claims=%s WHERE id=%s",
            (Json(claims), profile["id"]),
        )
        cur.execute("SELECT * FROM participant_profiles WHERE id=%s", (profile["id"],))
        before = cur.fetchone()
    visible = [
        {
            **item,
            "meeting_title": titles[index % 5],
            "meeting_date": dates[index % 5],
            "ordinality": index + 1,
        }
        for index, item in enumerate(claims)
        if index not in (3, 6) and index % 5 != 4
    ]
    yield profile, claims, visible, before


def visible_keys(item, key):
    if key == "observation":
        return (
            (
                item["correction"]["content"]
                if item["status"] == "corrected"
                else item["content"]
            ).lower(),
        )
    if key == "type":
        return (
            CATEGORY_LABELS[item["category"]].lower(),
            EPISTEMIC_LABELS[item["epistemic"]].lower(),
        )
    if key == "confidence":
        return ({"low": 0, "medium": 1, "high": 2}[item["confidence"]],)
    if key == "review":
        return (REVIEW_LABELS[item["status"]].lower(),)
    return (
        item["meeting_title"].lower() if item["meeting_title"] else None,
        item["meeting_date"],
    )


def expected(items, key, reverse):
    def compare(a, b):
        for left, right in zip(
            (*visible_keys(a, key), a["id"]), (*visible_keys(b, key), b["id"])
        ):
            if (left is None) != (right is None):
                return 1 if left is None else -1
            if left != right:
                return ((left > right) - (left < right)) * (-1 if reverse else 1)
        return 0

    return [item["id"] for item in sorted(items, key=cmp_to_key(compare))]


@pytest.mark.parametrize("ascending,descending,key", PAIRS)
@pytest.mark.parametrize("reverse", [False, True])
def test_evidence_headers_order_visible_values_globally_before_paging_without_writes(
    sortable_evidence, ascending, descending, key, reverse
):
    profile, claims, visible, before = sortable_evidence
    sort = descending if reverse else ascending
    pages = [
        profile_db.list_claims(profile["id"], sort=sort, limit=7, offset=offset)
        for offset in range(0, len(visible), 7)
    ]
    assert [item["id"] for page in pages for item in page["items"]] == expected(
        visible, key, reverse
    )
    assert all(
        page["profile_id"] == profile["id"]
        and page["revision"] == profile["revision"]
        and page["total"] == len(visible)
        for page in pages
    )
    assert len({item["id"] for page in pages for item in page["items"]}) == len(visible)
    assert profile_db.list_claims(profile["id"], sort=sort, offset=99)["items"] == []
    filtered = profile_db.list_claims(
        profile["id"], sort=sort, status="corrected", limit=3, offset=3
    )
    corrected = [item for item in visible if item["status"] == "corrected"]
    assert filtered["total"] == len(corrected)
    assert [item["id"] for item in filtered["items"]] == expected(
        corrected, key, reverse
    )[3:6]
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM participant_profiles WHERE id=%s", (profile["id"],))
        assert cur.fetchone() == before


@pytest.mark.parametrize("sort", [token for pair in PAIRS for token in pair[:2]])
def test_evidence_http_header_pairs_keep_source_filters_counts_and_identity(
    client, sortable_evidence, sort
):
    profile, _, visible, _ = sortable_evidence
    ascending, descending, key = next(pair for pair in PAIRS if sort in pair[:2])
    selected = [item for item in visible if item["epistemic"] == "observed"]
    response = client.get(
        f"/api/profiles/{profile['id']}/claims",
        params={"sort": sort, "epistemic": "observed", "limit": 4, "offset": 4},
    )
    assert response.status_code == 200
    result = response.json()
    assert (
        result["profile_id"] == profile["id"]
        and result["revision"] == profile["revision"]
        and result["total"] == len(selected)
    )
    assert [item["id"] for item in result["items"]] == expected(
        selected, key, sort == descending
    )[4:8]


@pytest.mark.parametrize("sort,reverse", [("oldest", False), ("newest", True)])
def test_evidence_legacy_saved_order_remains_ordinal_not_timestamp(
    sortable_evidence, sort, reverse
):
    profile, _, visible, _ = sortable_evidence
    result = profile_db.list_claims(profile["id"], sort=sort, limit=100)
    assert [item["id"] for item in result["items"]] == [
        item["id"] for item in (visible[::-1] if reverse else visible)
    ]


def test_evidence_sort_contract_is_complete_and_matches_display_categories():
    assert set(get_args(ProfileClaimSort)) == {
        "oldest",
        "newest",
        *(token for pair in PAIRS for token in pair[:2]),
    }
    assert set(CATEGORY_LABELS) == set(get_args(ProfileCategory))


@pytest.mark.parametrize(
    "sort", ["bad", "source;DROP TABLE participant_profiles", "", None]
)
def test_evidence_header_sort_rejects_untrusted_values_before_storage(
    monkeypatch, sort
):
    def forbidden():
        pytest.fail("Untrusted evidence order reached database")

    monkeypatch.setattr(profile_db, "_cursor", forbidden)
    with pytest.raises(ValueError):
        profile_db.list_claims(str(uuid4()), sort=sort)
