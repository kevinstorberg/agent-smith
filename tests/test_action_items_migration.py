from pathlib import Path

import psycopg2
from alembic import command
from alembic.config import Config

from scripts.shared.local_postgres import temporary_postgres
from services import config
from services.db.create import create_database


def test_action_items_migration_is_additive_and_roundtrips(monkeypatch):
    with temporary_postgres() as url:
        create_database(url)
        monkeypatch.setattr(config, "DATABASE_URL", url)
        migration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(migration, "8a3b0d7e9f21")
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("INSERT INTO plans(title,body) VALUES ('Existing document','Keep this') RETURNING id")
            plan_id = cursor.fetchone()[0]
        command.upgrade(migration, "head")
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM action_items")
            assert cursor.fetchone()[0] == 0
            cursor.execute("SELECT condeferrable,condeferred FROM pg_constraint WHERE conname='action_item_order_unique'")
            assert cursor.fetchone() == (True, True)
        command.downgrade(migration, "8a3b0d7e9f21")
        command.upgrade(migration, "head")
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT body FROM plans WHERE id=%s", (plan_id,))
            assert cursor.fetchone()[0] == "Keep this"
