from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import psycopg2
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg2.extras import Json

from scripts.shared.local_postgres import temporary_postgres
from services import config
from services.db.create import create_database


PARENT = "d4a7e2c9f6b1"


def test_project_catalog_migration_backfills_every_exact_legacy_name_and_roundtrips(
    monkeypatch,
):
    migration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    head = ScriptDirectory.from_config(migration).get_current_head()
    assert head != PARENT, (
        "Project catalog migration must extend the actual profile-topic schema"
    )
    with temporary_postgres() as url:
        create_database(url)
        monkeypatch.setattr(config, "DATABASE_URL", url)
        command.upgrade(migration, PARENT)
        profile_id = str(uuid4())
        samples = [
            (None, None, "open", 1, False),
            ("Work", None, "open", 2, False),
            ("work", None, "completed", None, False),
            ("  Work  ", None, "open", None, True),
            (" ", profile_id, "open", 1, False),
            ("Legacy\nName", profile_id, "completed", None, False),
            ("\t", profile_id, "open", None, True),
            ("Work", profile_id, "open", 2, False),
        ]
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO participant_profiles(id,identity_key,display_name,identity_scope) VALUES(%s,%s,'Legacy project owner','manual')",
                (profile_id, f"manual:{profile_id}"),
            )
            for index, (name, owner, status, position, deleted) in enumerate(samples):
                payload = {
                    "title": f"Legacy {index}",
                    "description": "Preserved details",
                    "project": "Work" if name == "  Work  " else name,
                    "tags": ["independent"],
                    "status": status,
                }
                cursor.execute(
                    """INSERT INTO action_items(title,description,project,tags,status,completed_at,sort_key,
                    revision,created_at,updated_at,request_id,create_payload,deleted_at,profile_id)
                    VALUES(%s,%s,%s,%s,%s,CASE WHEN %s='completed' THEN '2026-01-02T03:04:05Z'::timestamptz END,%s,
                    7,'2026-01-01T01:02:03Z','2026-01-02T03:04:05Z',%s,%s,CASE WHEN %s THEN '2026-01-03T04:05:06Z'::timestamptz END,%s)""",
                    (
                        payload["title"],
                        payload["description"],
                        name,
                        payload["tags"],
                        status,
                        status,
                        position,
                        str(uuid4()),
                        Json(payload),
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
            cursor.execute("SELECT name FROM action_item_projects")
            assert {row[0] for row in cursor.fetchall()} == {
                sample[0] for sample in samples if sample[0] is not None
            }
            cursor.execute("""SELECT to_jsonb(a)-'project_id'||jsonb_build_object('project',p.name)
                FROM action_items a LEFT JOIN action_item_projects p ON p.id=a.project_id ORDER BY a.id""")
            assert [row[0] for row in cursor.fetchall()] == before
            cursor.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name='action_items'"
            )
            columns = {row[0] for row in cursor.fetchall()}
            assert "project_id" in columns and "project" not in columns
            cursor.execute(
                "SELECT COUNT(*) FROM action_items WHERE project_id IS NOT NULL"
            )
            assert cursor.fetchone()[0] == len(samples) - 1
            cursor.execute("""SELECT confdeltype FROM pg_constraint WHERE contype='f'
                AND conrelid='action_items'::regclass AND confrelid='action_item_projects'::regclass""")
            assert cursor.fetchone()[0] in {"r", "a"}
            cursor.execute(
                "SELECT condeferrable,condeferred FROM pg_constraint WHERE conname='action_item_order_unique'"
            )
            assert cursor.fetchone() == (True, True)
            cursor.execute(
                "INSERT INTO action_item_projects(name) VALUES('Empty after migration')"
            )

        command.downgrade(migration, PARENT)

        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT to_jsonb(action_items) FROM action_items ORDER BY id"
            )
            assert [row[0] for row in cursor.fetchall()] == before
            cursor.execute("SELECT to_regclass('public.action_item_projects')")
            assert cursor.fetchone()[0] is None

        command.upgrade(migration, head)
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("""SELECT to_jsonb(a)-'project_id'||jsonb_build_object('project',p.name)
                FROM action_items a LEFT JOIN action_item_projects p ON p.id=a.project_id ORDER BY a.id""")
            assert [row[0] for row in cursor.fetchall()] == before
