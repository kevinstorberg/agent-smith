from __future__ import annotations

from contextlib import contextmanager
from uuid import uuid4

from psycopg2.extras import Json, RealDictCursor
import pytest

from services.api.models.shared import harness
from services.db import get_connection


@pytest.fixture(params=list(harness.VALID_TABLES))
def versioned_rows(request):
    kind = request.param
    table = harness.VALID_TABLES[kind]
    marker = "summary-latest-" + uuid4().hex
    specs = [
        ("Core", None, 1, True, ["claude"], "active"),
        ("Core", None, 5, False, ["codex"], "active"),
        ("Core", "", 1, True, ["claude"], "active"),
        ("Core", "", 3, True, ["claude"], "active"),
        ("Core", "Team", 1, True, ["claude"], "active"),
        ("Core", "Team", 2, True, ["gemini"], "active"),
        ("Core", "team", 4, True, ["claude"], "active"),
        ("Case", None, 1, True, ["claude"], "active"),
        ("case", None, 9, True, ["claude"], "active"),
    ]
    if kind in ("rule", "skill", "hook"):
        specs += [
            ("Core", None, None, True, ["claude"], "proposed"),
            ("Unversioned", None, None, True, ["claude"], "proposed"),
            ("Unversioned", None, None, True, ["claude"], "rejected"),
            ("Tied", None, 6, True, ["claude"], "active"),
            ("Tied", None, 6, True, ["claude"], "proposed"),
            ("Tied", None, 6, True, ["claude"], "rejected"),
        ]
    ids = []
    try:
        with get_connection() as conn, conn.cursor() as cur:
            for index, (name, project, version, enabled, agents, state) in enumerate(
                specs
            ):
                columns = "name,project,version,enabled,agents,sort_key,content"
                values = [
                    f"{marker}-{name}",
                    project,
                    version,
                    enabled,
                    agents,
                    index % 3,
                    Json({"body": f"Complete source {index}" * 100}),
                ]
                if kind in ("rule", "skill", "hook"):
                    columns += ",state"
                    values.append(state)
                placeholders = ",".join(["%s"] * len(values))
                cur.execute(
                    f"INSERT INTO {table}({columns}) VALUES({placeholders}) RETURNING id",
                    values,
                )
                ids.append(cur.fetchone()[0])
        yield kind, marker, specs, ids
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(f"DELETE FROM {table} WHERE id=ANY(%s)", (ids,))


def original_summary(kind, *, project=None, agent=None, enabled=None, sort="manual"):
    table = harness.VALID_TABLES[kind]
    columns = "id,name,project,agents,sort_key,enabled,version,created_at,updated_at"
    if kind == "rule":
        columns += ",clone_as_skill"
    project_clause, params = harness._project_filter(project)
    sql = f"SELECT {columns} FROM {table} WHERE {harness._LATEST_VERSION_CLAUSE.format(table=table)} {project_clause}"
    if agent:
        sql += " AND %s=ANY(agents)"
        params.append(agent)
    if enabled is not None:
        sql += " AND enabled=%s"
        params.append(enabled)
    sql += " ORDER BY " + harness.HARNESS_SORTS[sort]
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return [harness._row_to_dict(row) for row in cur.fetchall()]


@pytest.mark.parametrize("sort", ["manual", "name", "newest", "updated"])
@pytest.mark.parametrize(
    "filters",
    [
        {},
        {"project": "Team"},
        {"project": ""},
        {"agent": "claude"},
        {"enabled": True},
        {"project": "Team", "agent": "claude", "enabled": True},
    ],
)
def test_summary_preserves_original_latest_identity_order_filters_and_projection(
    versioned_rows, sort, filters
):
    kind, marker, specs, ids = versioned_rows
    table = harness.VALID_TABLES[kind]
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT * FROM {table} WHERE id=ANY(%s) ORDER BY id", (ids,))
        before = cur.fetchall()
    actual = harness.list_items_summary(kind, sort=sort, **filters)
    assert actual == original_summary(kind, sort=sort, **filters)
    ours = [row for row in actual if row["name"].startswith(marker)]
    expected_columns = {
        "id",
        "name",
        "project",
        "agents",
        "sort_key",
        "enabled",
        "version",
        "created_at",
        "updated_at",
    }
    if kind == "rule":
        expected_columns.add("clone_as_skill")
    assert all(set(row) == expected_columns for row in ours)
    actual_ids = {row["id"] for row in ours}
    assert (
        ids[0] not in actual_ids
        and ids[2] not in actual_ids
        and ids[4] not in actual_ids
    )
    if filters.get("enabled") or filters.get("agent") == "claude":
        assert ids[1] not in actual_ids
    if filters.get("agent") == "claude":
        assert ids[5] not in actual_ids
    if not filters:
        assert {ids[index] for index in (1, 3, 5, 6, 7, 8)} <= actual_ids
        if kind in ("rule", "skill", "hook"):
            assert set(ids[9:12]).isdisjoint(actual_ids)
            assert set(ids[12:15]) <= actual_ids
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT * FROM {table} WHERE id=ANY(%s) ORDER BY id", (ids,))
        assert cur.fetchall() == before


def test_summary_returns_complete_twenty_thousand_latest_rows_under_existing_timeout(
    monkeypatch,
):
    marker = "summary-volume-" + uuid4().hex + "-"
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO harness_rules(name,project,agents,content,sort_key,enabled,version)
                SELECT %s||n,NULL,ARRAY['claude'],'{"body":"Full synthetic source"}'::jsonb,n,true,2
                FROM generate_series(1,20000) n""",
                (marker,),
            )
            cur.execute(
                """INSERT INTO harness_rules(name,project,agents,content,sort_key,enabled,version)
                SELECT name,project,agents,content,sort_key,enabled,1 FROM harness_rules
                WHERE name LIKE %s AND mod(sort_key,5)=0""",
                (marker + "%",),
            )
            cur.execute("ANALYZE harness_rules")

        @contextmanager
        def bounded_connection():
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SET LOCAL statement_timeout='5s'")
                yield conn

        monkeypatch.setattr(harness, "get_connection", bounded_connection)
        rows = harness.list_items_summary("rule")
        ours = [row for row in rows if row["name"].startswith(marker)]
        assert len(ours) == 20000
        assert {row["version"] for row in ours} == {2}
        assert [row["sort_key"] for row in ours] == list(range(1, 20001))
        assert all("content" not in row and "latest_version" not in row for row in ours)
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM harness_rules WHERE name LIKE %s", (marker + "%",))
