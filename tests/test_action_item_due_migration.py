from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg2.extras import Json

from scripts.shared.local_postgres import temporary_postgres
from services import config
from services.db.create import create_database

PARENT = "e7c4b9d2a6f1"


def test_due_migration_preserves_every_old_field_and_roundtrips_global_profile_and_tombstones(
    monkeypatch,
):
    migration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    head = ScriptDirectory.from_config(migration).get_current_head()
    assert head != PARENT, "A deadline migration must extend the project catalog schema"
    with temporary_postgres() as url:
        create_database(url)
        monkeypatch.setattr(config, "DATABASE_URL", url)
        command.upgrade(migration, PARENT)
        profile_id = str(uuid4())
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO participant_profiles(id,identity_key,display_name,identity_scope) VALUES(%s,%s,'Deadline migration profile','manual')",
                (profile_id, f"manual:{profile_id}"),
            )
            cursor.execute(
                "INSERT INTO action_item_projects(name) VALUES('  Exact legacy name  ') RETURNING id"
            )
            project_id = cursor.fetchone()[0]
            for index, (owner, status, deleted, position) in enumerate(
                [
                    (None, "open", False, 1),
                    (None, "completed", False, None),
                    (None, "open", True, None),
                    (profile_id, "open", False, 1),
                    (profile_id, "completed", False, None),
                    (profile_id, "open", True, None),
                ]
            ):
                receipt = {
                    "title": f"Legacy {index}",
                    "description": "Exact original",
                    "project": "  Exact legacy name  ",
                    "tags": ["separate"],
                    "status": status,
                }
                cursor.execute(
                    """INSERT INTO action_items(title,description,project_id,tags,status,completed_at,sort_key,revision,request_id,create_payload,deleted_at,profile_id)
                VALUES(%s,'Exact original',%s,ARRAY['separate'],%s,CASE WHEN %s='completed' THEN '2026-01-01T01:02:03Z'::timestamptz END,%s,7,%s,%s,CASE WHEN %s THEN '2026-01-02T01:02:03Z'::timestamptz END,%s)""",
                    (
                        receipt["title"],
                        project_id,
                        status,
                        status,
                        position,
                        str(uuid4()),
                        Json(receipt),
                        deleted,
                        owner,
                    ),
                )
            cursor.execute(
                "SELECT to_jsonb(action_items) FROM action_items ORDER BY id"
            )
            before = [row[0] for row in cursor.fetchall()]
        command.upgrade(migration, head)
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT to_jsonb(action_items)-'due_at',due_at FROM action_items ORDER BY id"
            )
            rows = cursor.fetchall()
            assert [row[0] for row in rows] == before and all(
                row[1] is None for row in rows
            )
            cursor.execute(
                "SELECT data_type FROM information_schema.columns WHERE table_name='action_items' AND column_name='due_at'"
            )
            assert cursor.fetchone()[0] == "timestamp with time zone"
            cursor.execute(
                "UPDATE action_items SET due_at='2026-07-01T09:15:30.123456-04:00' WHERE profile_id IS NULL"
            )
        with pytest.raises(psycopg2.errors.CheckViolation):
            with psycopg2.connect(url) as connection, connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE action_items SET due_at=CURRENT_TIMESTAMP WHERE profile_id=%s",
                    (profile_id,),
                )
        command.downgrade(migration, PARENT)
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT to_jsonb(action_items) FROM action_items ORDER BY id"
            )
            assert [row[0] for row in cursor.fetchall()] == before
        command.upgrade(migration, head)
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT to_jsonb(action_items)-'due_at',due_at FROM action_items ORDER BY id"
            )
            rows = cursor.fetchall()
            assert [row[0] for row in rows] == before and all(
                row[1] is None for row in rows
            )
