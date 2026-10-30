from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from alembic import command
from alembic.config import Config
from psycopg2.errors import CheckViolation, UniqueViolation

from scripts.shared.local_postgres import temporary_postgres
from services import config
from services.db.create import create_database


def test_relationship_cards_migration_keeps_linked_records_and_guards_named_targets(monkeypatch):
    with temporary_postgres() as url:
        create_database(url)
        monkeypatch.setattr(config, "DATABASE_URL", url)
        migration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(migration, "8a3b0d7e9f21")
        owner, target = str(uuid4()), str(uuid4())
        with psycopg2.connect(url) as conn, conn.cursor() as cur:
            for key in (owner, target):
                cur.execute("INSERT INTO participant_profiles(id,identity_key,display_name,identity_scope) VALUES(%s,%s,'Known person','manual')", (key, "manual:" + key))
            cur.execute("INSERT INTO profile_relationships(subject_id,target_id,notes) VALUES(%s,%s,'Linked notes')", (owner, target))
        command.upgrade(migration, "head")
        with psycopg2.connect(url) as conn, conn.cursor() as cur:
            cur.execute("SELECT notes,target_id::text FROM profile_relationships")
            assert cur.fetchone() == ("Linked notes", target)
            cur.execute("INSERT INTO profile_relationships(subject_id,target_name) VALUES(%s,'Named person')", (owner,))
        with pytest.raises(CheckViolation):
            with psycopg2.connect(url) as conn, conn.cursor() as cur:
                cur.execute("INSERT INTO profile_relationships(subject_id) VALUES(%s)", (owner,))
        with pytest.raises(UniqueViolation):
            with psycopg2.connect(url) as conn, conn.cursor() as cur:
                cur.execute("INSERT INTO profile_relationships(subject_id,target_name) VALUES(%s,'NAMED PERSON')", (owner,))
        with pytest.raises(RuntimeError, match="named relationships"):
            command.downgrade(migration, "8a3b0d7e9f21")
        with psycopg2.connect(url) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM profile_relationships WHERE target_id IS NULL")
        command.downgrade(migration, "8a3b0d7e9f21")
        command.upgrade(migration, "head")
        with psycopg2.connect(url) as conn, conn.cursor() as cur:
            cur.execute("SELECT notes,target_id::text,target_name FROM profile_relationships")
            assert cur.fetchone() == ("Linked notes", target, "")
