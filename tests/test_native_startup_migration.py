from __future__ import annotations

import os
from contextlib import closing
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit

from alembic.config import Config
from alembic.script import ScriptDirectory
import psycopg2
from psycopg2 import sql
import pytest

from scripts import manage
from scripts.shared.automated_tests import sanitize_automated_environment
from scripts.shared.database_safety import database_identity
from scripts.shared.local_postgres import temporary_postgres
from scripts.shared.native_startup import probe_database


def test_confirmed_launcher_upgrade_and_read_only_schema_check_use_owned_cluster(tmp_path, monkeypatch):
    database = "agent_smith_launcher_owned"
    reader = "agent_smith_launcher_reader"
    memory = tmp_path / "unused-existing-memory"
    memory.mkdir()
    (memory / "owned-test-marker").write_text("Migration tests never open the memory store.")
    monkeypatch.setattr(manage, "python_executable", lambda: sys.executable)
    expected_heads = set(ScriptDirectory.from_config(Config(str(manage.ROOT / "alembic.ini"))).get_heads())

    with temporary_postgres() as owned_url:
        parsed = urlsplit(owned_url)
        assert parsed.hostname == "127.0.0.1"
        assert parsed.port not in (5432, 7654)
        admin_url = urlunsplit(parsed._replace(path="/postgres"))
        with closing(psycopg2.connect(admin_url, connect_timeout=2)) as admin:
            admin.autocommit = True
            with admin.cursor() as cursor:
                cursor.execute("SHOW data_directory")
                data_directory = Path(cursor.fetchone()[0]).resolve()
                assert data_directory.parent.name.startswith("agent-smith-test-")
                cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
                cursor.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOINHERIT").format(sql.Identifier(reader)))

        production_url = urlunsplit(parsed._replace(path=f"/{database}"))
        assert database_identity(production_url) == ("localhost", parsed.port, database)
        assert not database.endswith("_test")
        env = {key: value for key, value in os.environ.items() if not key.startswith("DATABASE_URL_")}
        env.update(APP_ENV="production", DATABASE_URL_PRODUCTION=production_url,
                   MEMORY_BACKEND="lancedb", MEMORY_STORE_PATH=str(memory), AGENT_SMITH_AUTOMATED_TESTS="1")
        sanitize_automated_environment(env)
        probe_database(sys.executable, env)

        with pytest.raises(subprocess.CalledProcessError):
            manage.apply_database_upgrade(env, "not_the_owned_database")
        with psycopg2.connect(production_url, connect_timeout=2) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('public.alembic_version')")
            assert cursor.fetchone()[0] is None

        manage.apply_database_upgrade(env, database)
        with psycopg2.connect(production_url, connect_timeout=2) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM alembic_version")
            assert {row[0] for row in cursor.fetchall()} == expected_heads
            cursor.execute("SELECT to_regclass('public.harness_rules'), to_regclass('public.background_jobs'), to_regclass('public.memories')")
            assert all(cursor.fetchone())
            cursor.execute("CREATE TABLE launcher_owned_probe (id integer PRIMARY KEY, note text NOT NULL)")
            cursor.execute("INSERT INTO launcher_owned_probe VALUES (1, 'preserved across rerun')")
            cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database), sql.Identifier(reader)))
            cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(reader)))
            cursor.execute(sql.SQL("GRANT SELECT ON alembic_version TO {}").format(sql.Identifier(reader)))

        manage.apply_database_upgrade(env, database)
        reader_url = urlunsplit(parsed._replace(netloc=f"{reader}@127.0.0.1:{parsed.port}", path=f"/{database}"))
        read_only_env = {**env, "DATABASE_URL_PRODUCTION": reader_url}
        subprocess.run(
            [sys.executable, "-c", "from alembic.config import Config; from services.db import check_production_schema; "
             f"check_production_schema(Config({str(manage.ROOT / 'alembic.ini')!r}))"],
            cwd=manage.ROOT, env=read_only_env, check=True, timeout=15,
        )
        with psycopg2.connect(production_url, connect_timeout=2) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM alembic_version")
            assert {row[0] for row in cursor.fetchall()} == expected_heads
            cursor.execute("SELECT * FROM launcher_owned_probe")
            assert cursor.fetchall() == [(1, "preserved across rerun")]

    assert not data_directory.exists()
