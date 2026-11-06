from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg2.extras import Json
import pytest

from services.api.models.shared import harness
from services.api.routers import harness_router
from services.db import get_connection


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(harness_router, prefix="/harness")
    return TestClient(app)


@pytest.fixture(params=list(harness.VALID_TABLES))
def harness_rows(request):
    kind = request.param
    table = harness.VALID_TABLES[kind]
    marker = "sort_" + uuid4().hex
    specs = [
        ("zulu", "Beta", ["gemini", "claude"], 2, True, 1, 1, 1),
        ("alpha", "Alpha", ["codex"], 1, False, 2, 3, 3),
        ("ALPHA", None, ["claude", "gemini"], 1, True, 10, 2, 1),
        ("charlie", "", [], 5, False, 2, 2, 0),
        ("bravo", "ALPHA", ["claude"], 4, True, 3, 1, 2),
        ("delta", "Beta", ["claude"], 3, False, 2, 4, 3),
    ]
    ids, all_ids, config_ids = [], [], []
    stamp = datetime(2025, 1, 1, tzinfo=timezone.utc)
    try:
        for title, project, agents, rank, enabled, version, day, count in specs:
            item_id = harness.create_item(
                kind,
                f"{marker}_{title}",
                {"body": "Full source " * 100},
                project=project,
                agents=agents,
                sort_key=rank,
                enabled=enabled,
            )
            ids.append(item_id)
            all_ids.append(item_id)
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM harness_configs WHERE item_id=%s AND item_type=%s",
                    (item_id, kind),
                )
                cur.execute(
                    f"UPDATE {table} SET agents=%s, version=%s, created_at=%s, updated_at=%s WHERE id=%s",
                    (
                        agents,
                        version,
                        stamp + timedelta(days=day),
                        stamp + timedelta(days=day),
                        item_id,
                    ),
                )
                for _ in range(count):
                    cur.execute(
                        "INSERT INTO harness_configs(item_id,item_type) VALUES(%s,%s) RETURNING id",
                        (item_id, kind),
                    )
                    config_ids.append(cur.fetchone()[0])
        with get_connection() as conn, conn.cursor() as cur:
            if kind == "rule":
                cur.execute(
                    f"UPDATE {table} SET clone_as_skill=true WHERE id=ANY(%s)",
                    ([ids[0], ids[3], ids[5]],),
                )
            cur.execute(
                f"INSERT INTO {table}(name,project,agents,content,sort_key,enabled,version) SELECT name,project,agents,%s,-999,true,9 FROM {table} WHERE id=%s RETURNING id",
                (Json({"body": "Historical version"}), ids[2]),
            )
            historical_id = cur.fetchone()[0]
            all_ids.append(historical_id)
            if kind in ("rule", "skill", "hook"):
                cur.execute(
                    f"INSERT INTO {table}(name,project,agents,content,sort_key,enabled,version,state) SELECT name,project,agents,%s,-999,true,NULL,'proposed' FROM {table} WHERE id=%s RETURNING id",
                    (Json({"body": "Proposed version"}), ids[2]),
                )
                all_ids.append(cur.fetchone()[0])
            wrong_kind = "agent" if kind != "agent" else "rule"
            for item_id, item_type in [(ids[3], wrong_kind)] * 5 + [
                (historical_id, kind)
            ] * 10:
                cur.execute(
                    "INSERT INTO harness_configs(item_id,item_type) VALUES(%s,%s) RETURNING id",
                    (item_id, item_type),
                )
                config_ids.append(cur.fetchone()[0])
        yield kind, marker, ids, all_ids, config_ids
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM harness_configs WHERE id=ANY(%s)", (config_ids,))
            cur.execute(f"DELETE FROM {table} WHERE id=ANY(%s)", (all_ids,))


_ORDERS = [
    ("manual", [1, 2, 0, 5, 4, 3]),
    ("manual_desc", [3, 4, 5, 0, 2, 1]),
    ("name", [1, 2, 4, 3, 5, 0]),
    ("name_desc", [0, 5, 3, 4, 2, 1]),
    ("project_asc", [1, 4, 0, 5, 2, 3]),
    ("project_desc", [5, 0, 4, 1, 3, 2]),
    ("enabled_asc", [1, 3, 5, 0, 2, 4]),
    ("enabled_desc", [4, 2, 0, 5, 3, 1]),
    ("agents_asc", [4, 5, 0, 2, 1, 3]),
    ("agents_desc", [1, 2, 0, 5, 4, 3]),
    ("config_count_asc", [3, 0, 2, 4, 1, 5]),
    ("config_count_desc", [5, 1, 4, 2, 0, 3]),
    ("version_asc", [0, 1, 3, 5, 4, 2]),
    ("version_desc", [2, 4, 5, 3, 1, 0]),
    ("updated_asc", [0, 4, 2, 3, 1, 5]),
    ("updated", [5, 1, 3, 2, 4, 0]),
]


def snapshot(kind, ids, config_ids):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT * FROM {harness.VALID_TABLES[kind]} WHERE id=ANY(%s) ORDER BY id",
            (ids,),
        )
        rows = cur.fetchall()
        cur.execute(
            "SELECT * FROM harness_configs WHERE id=ANY(%s) ORDER BY id", (config_ids,)
        )
        return rows, cur.fetchall()


@pytest.mark.parametrize("sort,positions", _ORDERS)
def test_all_harness_header_orders_are_global_stable_and_read_only(
    client, harness_rows, sort, positions
):
    kind, marker, ids, all_ids, config_ids = harness_rows
    before = snapshot(kind, all_ids, config_ids)
    pages = [
        client.get(
            f"/harness/items/{kind}",
            params={"name": marker, "sort": sort, "limit": 2, "offset": offset},
        )
        for offset in (0, 2, 4)
    ]
    assert all(page.status_code == 200 for page in pages), [page.text for page in pages]
    bodies = [page.json() for page in pages]
    assert [row["id"] for body in bodies for row in body["items"]] == [
        ids[index] for index in positions
    ]
    assert [body["total"] for body in bodies] == [6, 6, 6]
    by_id = {row["id"]: row for body in bodies for row in body["items"]}
    assert [len(by_id[item_id]["configs"]) for item_id in ids] == [1, 3, 1, 0, 2, 3]
    expected_keys = {
        "id",
        "name",
        "project",
        "agents",
        "sort_key",
        "enabled",
        "version",
        "created_at",
        "updated_at",
        "configs",
    }
    if kind == "rule":
        expected_keys.add("clone_as_skill")
    assert all(
        set(row) == expected_keys and type(row["version"]) is int
        for body in bodies
        for row in body["items"]
    )
    assert client.get(
        f"/harness/items/{kind}", params={"name": marker, "sort": sort, "offset": 99}
    ).json() == {"items": [], "total": 6}
    assert snapshot(kind, all_ids, config_ids) == before


def test_harness_config_count_preserves_project_agent_enabled_and_latest_filters(
    client, harness_rows
):
    kind, marker, ids, _, _ = harness_rows
    response = client.get(
        f"/harness/items/{kind}",
        params={
            "name": marker,
            "sort": "config_count_desc",
            "project": "Beta",
            "agent": "claude",
            "enabled": "true",
            "limit": 1,
            "offset": 1,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 2
    assert [row["id"] for row in response.json()["items"]] == [ids[0]]


def test_hidden_newest_harness_alias_is_retained(client, harness_rows):
    kind, marker, ids, _, _ = harness_rows
    response = client.get(
        f"/harness/items/{kind}", params={"name": marker, "sort": "newest"}
    )
    assert response.status_code == 200
    assert [row["id"] for row in response.json()["items"]] == [
        ids[index] for index in [5, 1, 3, 2, 4, 0]
    ]


@pytest.mark.parametrize(
    "sort,positions",
    [
        ("clone_as_skill_asc", [1, 2, 4, 0, 3, 5]),
        ("clone_as_skill_desc", [5, 3, 0, 4, 2, 1]),
    ],
)
def test_rule_clone_order_is_rule_only_and_has_stable_ties(
    client, harness_rows, monkeypatch, sort, positions
):
    kind, marker, ids, _, _ = harness_rows
    response = client.get(
        f"/harness/items/{kind}", params={"name": marker, "sort": sort}
    )
    if kind == "rule":
        assert response.status_code == 200, response.text
        assert [row["id"] for row in response.json()["items"]] == [
            ids[index] for index in positions
        ]
    else:
        assert response.status_code == 422, response.text

        def unexpected_connection():
            pytest.fail("A rule-only sort reached the database for another kind")

        monkeypatch.setattr(harness, "get_connection", unexpected_connection)
        with pytest.raises(ValueError):
            harness.list_items_summary(kind, sort=sort)


@pytest.mark.parametrize(
    "sort", ["id;DROP TABLE harness_rules", "name DESC", "config_count"]
)
def test_harness_invalid_sort_is_rejected_before_database(client, monkeypatch, sort):
    assert client.get("/harness/items/rule", params={"sort": sort}).status_code == 422

    def unexpected_connection():
        pytest.fail("An unknown sort reached the database")

    monkeypatch.setattr(harness, "get_connection", unexpected_connection)
    with pytest.raises(ValueError):
        harness.list_items_summary("rule", sort=sort)
