from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from scripts.shared.local_postgres import temporary_postgres
from services import config
from services.db.create import create_database

REVISION = "b5e7a9c2d4f6"
PARENT = "a4b6c8d0e2f1"


def view_columns(cursor):
    cursor.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='action_item_ordered_items' ORDER BY ordinal_position"
    )
    return [row[0] for row in cursor.fetchall()]


@pytest.mark.parametrize("starting_revision", ["base", "a9c6d3e8f1b2", PARENT])
def test_priority_extends_actual_single_head_and_upgrades_partial_histories(
    monkeypatch, starting_revision
):
    migration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(migration)
    assert scripts.get_revision(REVISION).down_revision == PARENT
    with temporary_postgres() as url:
        create_database(url)
        monkeypatch.setattr(config, "DATABASE_URL", url)
        command.upgrade(migration, starting_revision)
        command.upgrade(migration, REVISION)
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            assert view_columns(cursor)[-2:] == ["queue_priority", "is_priority"]
            cursor.execute("SELECT * FROM action_item_global_positions")
            assert cursor.fetchall() == []
        command.downgrade(migration, PARENT)
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            assert view_columns(cursor)[-1] == "queue_priority"
        command.upgrade(migration, REVISION)


def test_priority_populated_migration_preserves_fields_positions_views_and_profiles(
    monkeypatch,
):
    migration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with temporary_postgres() as url:
        create_database(url)
        monkeypatch.setattr(config, "DATABASE_URL", url)
        command.upgrade(migration, PARENT)
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            profile_id = str(uuid4())
            cursor.execute(
                "INSERT INTO participant_profiles(id,identity_key,display_name,identity_scope) VALUES(%s,%s,'Priority migration profile','manual')",
                (profile_id, f"manual:{profile_id}"),
            )
            for index, (owner, status, deleted) in enumerate(
                [
                    (None, "open", False),
                    (None, "completed", False),
                    (None, "open", True),
                    (profile_id, "open", False),
                ]
            ):
                cursor.execute(
                    """INSERT INTO action_items(title,profile_id,status,completed_at,deleted_at,sort_key)
                    VALUES(%s,%s,%s,CASE WHEN %s='completed' THEN CURRENT_TIMESTAMP END,
                    CASE WHEN %s THEN CURRENT_TIMESTAMP END,%s) RETURNING id""",
                    (
                        f"Legacy {index}",
                        owner,
                        status,
                        status,
                        deleted,
                        1 if owner else None,
                    ),
                )
                item_id = cursor.fetchone()[0]
                if owner is None:
                    cursor.execute(
                        "INSERT INTO action_item_queue_entries(action_item_id,sort_key) VALUES(%s,%s)",
                        (item_id, 1 if status == "open" and not deleted else None),
                    )
            cursor.execute("SELECT to_jsonb(a) FROM action_items a ORDER BY id")
            before = [row[0] for row in cursor.fetchall()]
            columns = view_columns(cursor)
            cursor.execute(
                "SELECT * FROM action_item_global_positions ORDER BY action_item_id"
            )
            positions = cursor.fetchall()
        command.upgrade(migration, REVISION)
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            assert view_columns(cursor) == [*columns, "is_priority"]
            cursor.execute(
                "SELECT to_jsonb(a)-'is_priority',is_priority FROM action_items a ORDER BY id"
            )
            rows = cursor.fetchall()
            assert [row[0] for row in rows] == before
            assert all(row[1] is False for row in rows)
            cursor.execute(
                "SELECT * FROM action_item_global_positions ORDER BY action_item_id"
            )
            assert cursor.fetchall() == positions
            cursor.execute(
                "UPDATE action_items SET is_priority=true WHERE profile_id IS NULL"
            )
        with pytest.raises(psycopg2.errors.CheckViolation):
            with psycopg2.connect(url) as connection, connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE action_items SET is_priority=true WHERE profile_id=%s",
                    (profile_id,),
                )
        command.downgrade(migration, PARENT)
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            assert view_columns(cursor) == columns
            cursor.execute("SELECT to_jsonb(a) FROM action_items a ORDER BY id")
            assert [row[0] for row in cursor.fetchall()] == before
        command.upgrade(migration, REVISION)
