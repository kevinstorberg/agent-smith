from pathlib import Path

import psycopg2
import pytest
from alembic import command
from alembic.config import Config
from psycopg2.errors import NotNullViolation

from scripts.shared.local_postgres import temporary_postgres
from services import config
from services.db.create import create_database


def test_job_scheduling_migration_preserves_definitions_and_guards_paused_downgrade(monkeypatch):
    with temporary_postgres() as url:
        create_database(url)
        monkeypatch.setattr(config, "DATABASE_URL", url)
        migration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(migration, "a2c5e8f1b4d7")
        with psycopg2.connect(url) as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO background_jobs(name,schedule_config,input_params)
                VALUES('Existing job','{"minutes":5}','{"command":"echo synthetic"}') RETURNING id""")
            job_id = cur.fetchone()[0]
            cur.execute("SELECT to_jsonb(j) FROM background_jobs j WHERE id=%s", (job_id,))
            before = cur.fetchone()[0]
        command.upgrade(migration, "head")
        with psycopg2.connect(url) as conn, conn.cursor() as cur:
            cur.execute("SELECT to_jsonb(j) FROM background_jobs j WHERE id=%s", (job_id,))
            after = cur.fetchone()[0]
            assert after.pop("schedule_enabled") is True and after == before
            for state in ("active", "proposed", "rejected"):
                cur.execute("""INSERT INTO background_jobs(name,schedule_config,input_params,state)
                    VALUES(%s,'{"hours":1}','{}',%s) RETURNING schedule_enabled""", (f"New {state}", state))
                assert cur.fetchone()[0] is True
            cur.execute("UPDATE background_jobs SET schedule_enabled=false WHERE id=%s", (job_id,))
        with pytest.raises(NotNullViolation):
            with psycopg2.connect(url) as conn, conn.cursor() as cur:
                cur.execute("UPDATE background_jobs SET schedule_enabled=NULL WHERE id=%s", (job_id,))
        with pytest.raises(RuntimeError, match="automatic scheduling paused"):
            command.downgrade(migration, "a2c5e8f1b4d7")
        with psycopg2.connect(url) as conn, conn.cursor() as cur:
            cur.execute("SELECT schedule_enabled FROM background_jobs WHERE id=%s", (job_id,))
            assert cur.fetchone()[0] is False
            cur.execute("UPDATE background_jobs SET schedule_enabled=true WHERE id=%s", (job_id,))
        command.downgrade(migration, "a2c5e8f1b4d7")
        command.upgrade(migration, "head")
        with psycopg2.connect(url) as conn, conn.cursor() as cur:
            cur.execute("SELECT to_jsonb(j) FROM background_jobs j WHERE id=%s", (job_id,))
            roundtrip = cur.fetchone()[0]
            assert roundtrip.pop("schedule_enabled") is True and roundtrip == before
