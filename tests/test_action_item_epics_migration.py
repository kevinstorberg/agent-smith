from pathlib import Path

import psycopg2
import pytest
from alembic import command
from alembic.config import Config

from scripts.shared.local_postgres import temporary_postgres
from services import config
from services.db.create import create_database


def test_epic_migration_preserves_flat_history_and_profiles(monkeypatch):
    with temporary_postgres() as url:
        create_database(url)
        monkeypatch.setattr(config, "DATABASE_URL", url)
        migration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(migration, "e4b7c9d2a6f1")
        with psycopg2.connect(url) as conn, conn.cursor() as cursor:
            cursor.execute("INSERT INTO action_items(title,sort_key) VALUES('Existing',1) RETURNING id,revision,created_at")
            before = cursor.fetchone()
        command.upgrade(migration, "head")
        with psycopg2.connect(url) as conn, conn.cursor() as cursor:
            cursor.execute("SELECT a.id,a.revision,a.created_at,a.sort_key,p.priority FROM action_items a JOIN action_item_global_positions p ON p.action_item_id=a.id")
            assert cursor.fetchone() == (*before, None, 1)
            cursor.execute("SELECT condeferrable,condeferred FROM pg_constraint WHERE conname='action_item_queue_order'")
            assert cursor.fetchone() == (True, True)
        command.downgrade(migration, "e4b7c9d2a6f1")
        with psycopg2.connect(url) as conn, conn.cursor() as cursor:
            cursor.execute("SELECT id,revision,created_at,sort_key FROM action_items")
            assert cursor.fetchone() == (*before, 1)
        command.upgrade(migration, "head")
        with psycopg2.connect(url) as conn, conn.cursor() as cursor:
            cursor.execute("INSERT INTO action_item_epics(title,request_id,create_payload) VALUES('Keep history','00000000-0000-0000-0000-000000000001','{}') RETURNING id")
            epic_id = cursor.fetchone()[0]
            cursor.execute("INSERT INTO action_item_queue_entries(epic_id,sort_key) VALUES(%s,2)", (epic_id,))
        with pytest.raises(RuntimeError, match="Epic history"):
            command.downgrade(migration, "e4b7c9d2a6f1")
