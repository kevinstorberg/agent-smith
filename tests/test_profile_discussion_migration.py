from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from alembic import command
from alembic.config import Config
from psycopg2.extras import Json

from scripts.shared.local_postgres import temporary_postgres
from services import config
from services.db.create import create_database

PARENT = "b6e2d9f4a1c7"
REVISION = "d4a7e2c9f6b1"
LEGACY_COLUMNS = "id,title,description,project,tags,status,completed_at,sort_key,revision,created_at,updated_at,request_id,create_payload,deleted_at"


def test_profile_discussion_migration_preserves_old_tasks_scopes_constraints_and_guarded_downgrade(monkeypatch):
    with temporary_postgres() as url:
        create_database(url)
        monkeypatch.setattr(config, "DATABASE_URL", url)
        migration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(migration, PARENT)
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            for title, status, position, deleted in (("Open first", "open", 1, False), ("Open second", "open", 2, False),
                                                       ("Completed", "completed", None, False), ("Deleted receipt", "open", None, True)):
                payload = {"title": title, "description": "Keep details", "project": "Work", "tags": ["prep"], "status": status}
                cursor.execute("""INSERT INTO action_items(title,description,project,tags,status,completed_at,sort_key,request_id,create_payload,deleted_at)
                    VALUES(%s,%s,%s,%s,%s,CASE WHEN %s='completed' THEN now() END,%s,%s,%s,CASE WHEN %s THEN now() END)""",
                    (title, payload["description"], payload["project"], payload["tags"], status, status, position, str(uuid4()), Json(payload), deleted))
            cursor.execute(f"SELECT {LEGACY_COLUMNS} FROM action_items ORDER BY id")
            before = cursor.fetchall()
        command.upgrade(migration, "head")
        profile_a, profile_b = str(uuid4()), str(uuid4())
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute(f"SELECT {LEGACY_COLUMNS} FROM action_items ORDER BY id")
            assert cursor.fetchall() == before
            cursor.execute("SELECT profile_id,scope_key FROM action_items ORDER BY id")
            assert cursor.fetchall() == [(None, "global")] * 4
            cursor.execute("SELECT condeferrable,condeferred,pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='action_item_order_unique'")
            deferred, initially, definition = cursor.fetchone()
            assert deferred and initially and "scope_key, sort_key" in definition
            for profile_id in (profile_a, profile_b):
                cursor.execute("INSERT INTO participant_profiles(id,identity_key,display_name,identity_scope) VALUES(%s,%s,'Profile','manual')", (profile_id, "manual:" + profile_id))
                cursor.execute("INSERT INTO action_items(title,profile_id,sort_key) VALUES('Topic',%s,1)", (profile_id,))
            cursor.execute("SELECT scope_key,sort_key FROM action_items WHERE profile_id IS NOT NULL ORDER BY scope_key")
            assert cursor.fetchall() == [(profile_id, 1) for profile_id in sorted((profile_a, profile_b))]
        inserted = False
        with pytest.raises(psycopg2.IntegrityError):
            with psycopg2.connect(url) as connection, connection.cursor() as cursor:
                cursor.execute("INSERT INTO action_items(title,profile_id,sort_key) VALUES('Duplicate rank',%s,1)", (profile_a,))
                inserted = True
        assert inserted
        with pytest.raises(psycopg2.errors.GeneratedAlways):
            with psycopg2.connect(url) as connection, connection.cursor() as cursor:
                cursor.execute("INSERT INTO action_items(title,profile_id,sort_key,scope_key) VALUES('Spoof owner',%s,2,'global')", (profile_a,))
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            with psycopg2.connect(url) as connection, connection.cursor() as cursor:
                cursor.execute("DELETE FROM participant_profiles WHERE id=%s", (profile_a,))
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM action_items WHERE profile_id=%s", (profile_b,))
            cursor.execute("UPDATE action_items SET status='completed',completed_at=now(),sort_key=NULL WHERE profile_id=%s", (profile_a,))
        with pytest.raises(RuntimeError, match="profile-owned action items"):
            command.downgrade(migration, PARENT)
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM alembic_version")
            assert cursor.fetchone() == (REVISION,)
            cursor.execute("SELECT scope_key,status FROM action_items WHERE profile_id=%s", (profile_a,))
            assert cursor.fetchone() == (profile_a, "completed")
            cursor.execute("DELETE FROM action_items WHERE profile_id IS NOT NULL")
        command.downgrade(migration, PARENT)
        command.upgrade(migration, "head")
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute(f"SELECT {LEGACY_COLUMNS} FROM action_items ORDER BY id")
            assert cursor.fetchall() == before
