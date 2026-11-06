from pathlib import Path

import psycopg2
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from scripts.shared.local_postgres import temporary_postgres
from services import config
from services.db.create import create_database


def test_project_metadata_migration_preserves_catalog_assignments_and_roundtrips(
    monkeypatch,
):
    migration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    parent = "f8d5c0e3b7a2"
    head = ScriptDirectory.from_config(migration).get_current_head()
    assert head != parent, (
        "Project descriptions need a migration beyond the current catalog"
    )
    with temporary_postgres() as url:
        create_database(url)
        monkeypatch.setattr(config, "DATABASE_URL", url)
        command.upgrade(migration, parent)
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO action_item_projects(name,created_at) VALUES('  Exact legacy\nname  ','2025-01-02T03:04:05-05:00') RETURNING id"
            )
            project_id = cursor.fetchone()[0]
            cursor.execute(
                "INSERT INTO action_items(title,project_id,sort_key) VALUES('Preserve assignment',%s,1)",
                (project_id,),
            )
            cursor.execute(
                "SELECT to_jsonb(action_item_projects) FROM action_item_projects"
            )
            before = cursor.fetchone()[0]
            cursor.execute("SELECT to_jsonb(action_items) FROM action_items")
            item = cursor.fetchone()[0]
        command.upgrade(migration, head)
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT to_jsonb(action_item_projects)-'description'-'revision'-'updated_at',description,revision,updated_at=created_at FROM action_item_projects"
            )
            assert cursor.fetchone() == (before, "", 1, True)
            cursor.execute("SELECT to_jsonb(action_items) FROM action_items")
            assert cursor.fetchone()[0] == item
            cursor.execute(
                "UPDATE action_item_projects SET description='New context',revision=2"
            )
        command.downgrade(migration, parent)
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT to_jsonb(action_item_projects) FROM action_item_projects"
            )
            assert cursor.fetchone()[0] == before
            cursor.execute("SELECT to_jsonb(action_items) FROM action_items")
            assert cursor.fetchone()[0] == item
        command.upgrade(migration, head)
