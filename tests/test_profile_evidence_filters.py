import copy
from typing import get_args
from uuid import uuid4

import pytest
from psycopg2.extras import Json

from services.db import get_connection
from services.meetings import profile_db
from services.meetings.outputs import ProfileCategory
from tests.test_meeting_profiles_db import claimed as claimed, participants as participants
from tests.test_meeting_profiles_router import applied as applied
from tests.test_meeting_sync import source as source
from tests.test_profiles_router import client as client


@pytest.fixture
def observations(applied):
    meeting_id, profile = applied
    original = profile["claims"][0]
    claims = []
    for index in range(42):
        item = {**copy.deepcopy(original), "id": str(uuid4()), "content": f"Original observation {index}",
                "category": "driver" if index % 2 else "strength",
                "epistemic": ("observed", "self_report", "inference")[index % 3],
                "confidence": ("high", "medium", "low")[index % 3],
                "status": ("active", "corrected", "rejected", "active")[index % 4],
                "target_id": original["target_id"] if index % 4 else None,
                "target_name": original["target_name"] if index % 4 else None}
        if item["status"] != "active":
            item["correction"] = {"action": "correct" if item["status"] == "corrected" else "reject",
                                  "content": f"Updated assessment {index}" if item["status"] == "corrected" else None,
                                  "reason": "Human review"}
        claims.append(item)
    claims[3]["transcript_hash"] = "withdrawn"
    claims[6]["superseded"] = True
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE participant_profiles SET claims=%s WHERE id=%s", (Json(claims), profile["id"]))
    return meeting_id, profile, claims


@pytest.mark.parametrize("filters", [
    {"category": "driver"}, {"epistemic": "observed"}, {"confidence": "low"}, {"status": "corrected"},
    {"category": "strength", "epistemic": "self_report", "confidence": "medium", "status": "active"},
])
def test_evidence_filters_count_and_page_only_matching_visible_observations(client, observations, filters):
    _, profile, claims = observations
    expected = [item for index, item in enumerate(claims) if index not in (3, 6)
                and all(item[key] == value for key, value in filters.items())]
    path = f"/api/profiles/{profile['id']}/claims"
    first = client.get(path, params={**filters, "limit": 5}).json()
    second = client.get(path, params={**filters, "limit": 5, "offset": 5}).json()
    assert first["total"] == second["total"] == len(expected)
    assert [item["id"] for item in first["items"] + second["items"]] == [item["id"] for item in expected[:10]]
    assert all(item["meeting_title"] is not None and item["meeting_date"] for item in first["items"])


def test_evidence_sort_is_stable_across_pages_and_preserves_legacy_default(client, observations):
    _, profile, claims = observations
    expected = [item["id"] for index, item in enumerate(claims) if index not in (3, 6)]
    path = f"/api/profiles/{profile['id']}/claims"
    assert [item["id"] for item in client.get(path).json()["items"]] == expected[:20]
    actual = []
    for offset in (0, 20):
        page = client.get(path, params={"sort": "newest", "offset": offset}).json()
        assert page["total"] == len(expected)
        actual.extend(item["id"] for item in page["items"])
    assert actual == expected[::-1]


def test_evidence_search_finds_corrections_sources_and_quotes_without_exposing_withdrawn_text(client, observations):
    meeting_id, profile, claims = observations
    path = f"/api/profiles/{profile['id']}/claims"
    corrected = client.get(path, params={"q": "  UPDATED ASSESSMENT 5  "}).json()
    assert [item["id"] for item in corrected["items"]] == [claims[5]["id"]]
    assert client.get(path, params={"q": "Original observation 3", "limit": 100}).json()["total"] == 10
    assert client.get(path, params={"q": "' OR true --"}).json()["total"] == 0
    quote = client.get(path, params={"q": claims[0]["evidence"][0]["quote"]}).json()
    assert quote["total"] == 40
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE meeting_summaries SET title='Reliability planning' WHERE id=%s", (meeting_id,))
    assert client.get(path, params={"q": "reliability planning"}).json()["total"] == 40
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE meeting_summaries SET available=false WHERE id=%s", (meeting_id,))
    response = client.get(path, params={"q": "reliability planning"}).json()
    assert response["total"] == 0 and response["items"] == []


def test_evidence_target_filter_resolves_aliases_and_returns_current_profile_links(client, observations):
    _, profile, claims = observations
    target_id = next(item["target_id"] for item in claims if item["target_id"])
    target = profile_db.get_profile(target_id)
    linked = profile_db.link_alias(target_id, f"related-{uuid4().hex}@example.test", target["revision"])
    alias_id = linked["aliases"][-1]["id"]
    try:
        claims[1]["target_id"] = alias_id
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE participant_profiles SET claims=%s WHERE id=%s", (Json(claims), profile["id"]))
        path = f"/api/profiles/{profile['id']}/claims"
        canonical = client.get(path, params={"target_id": target_id, "limit": 100}).json()
        alias = client.get(path, params={"target_id": alias_id, "limit": 100}).json()
        assert canonical == alias
        expected = [item for index, item in enumerate(claims) if index not in (3, 6) and item["target_id"]]
        assert canonical["total"] == len(expected)
        assert {item["target_id"] for item in canonical["items"]} == {target_id}
        assert client.get(path, params={"target_id": str(uuid4())}).json()["total"] == 0
    finally:
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM participant_profiles WHERE id=%s", (alias_id,))


def test_evidence_retains_source_observations_without_links_to_deleted_people(client, observations):
    _, profile, claims = observations
    target_id = next(item["target_id"] for item in claims if item["target_id"])
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE participant_profiles SET deleted=true WHERE id=%s", (target_id,))
    path = f"/api/profiles/{profile['id']}/claims"
    page = client.get(path).json()
    assert page["total"] == 40
    assert not any(item.get("target_id") or item.get("target_name") for item in page["items"])
    assert client.get(path, params={"target_id": target_id}).json()["total"] == 0


@pytest.mark.parametrize("params", [
    {"category": "unknown"}, {"epistemic": "guessed"}, {"confidence": "certain"},
    {"status": "approved"}, {"sort": "created_at"}, {"target_id": "unknown"}, {"q": "x" * 1001},
])
def test_evidence_rejects_invalid_http_filters(client, params):
    assert client.get(f"/api/profiles/{uuid4()}/claims", params=params).status_code == 422


@pytest.mark.parametrize("params", [
    {"category": False}, {"epistemic": "guessed"}, {"confidence": "certain"}, {"status": "approved"},
    {"sort": "descending"}, {"target_id": "unknown"}, {"query": "x" * 1001}, {"query": " "}, {"query": 1},
])
def test_evidence_rejects_invalid_core_filters(params):
    with pytest.raises(ValueError):
        profile_db.list_claims(str(uuid4()), **params)


def test_category_query_schema_uses_the_agent_claim_enum(client):
    schema = client.get("/openapi.json").json()
    category = next(item for item in schema["paths"]["/api/profiles/{profile_id}/claims"]["get"]["parameters"]
                    if item["name"] == "category")
    assert category["schema"]["anyOf"][0]["enum"] == list(get_args(ProfileCategory))
