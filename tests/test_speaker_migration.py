from pathlib import Path
from uuid import uuid4

import psycopg2
from alembic import command
from alembic.config import Config
from psycopg2.extras import Json

from scripts.shared.local_postgres import temporary_postgres
from services import config
from services.db.create import create_database


def test_speaker_migration_keeps_completed_and_partial_memory_receipts(monkeypatch):
    with temporary_postgres() as url:
        create_database(url)
        monkeypatch.setattr(config, "DATABASE_URL", url)
        migration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(migration, "c7a8e9f0b1d2")
        keys = [str(uuid4()), str(uuid4())]
        artifact = {"version": 1, "offset": 18, "items": [{"id": "frozen-id", "kind": "fact"}], "published_ids": ["frozen-id"]}
        for key, status in zip(keys, ("done", "pending")):
            with psycopg2.connect(url) as connection, connection.cursor() as cursor:
                cursor.execute("""INSERT INTO meeting_summaries
                    (id,provider,account_key,external_id,source_name,summary_text,source_url,
                     provider_created_at,provider_updated_at,content_hash)
                    VALUES (%s,'test','migration',%s,'test','Saved summary','https://example.invalid',now(),now(),'frozen')""", (key, key))
                cursor.execute("""INSERT INTO meeting_digestions (meeting_id,memory_status,memory_artifact,profile_status)
                    VALUES (%s,%s,%s,'done')""", (key, status, Json(artifact)))
        for _ in range(2):
            command.upgrade(migration, "head")
            with psycopg2.connect(url) as connection, connection.cursor() as cursor:
                for key, status, speaker in zip(keys, ("done", "pending"), ("legacy", "pending")):
                    cursor.execute("SELECT memory_status,memory_artifact,profile_status,speaker_status,speaker_artifact FROM meeting_digestions WHERE meeting_id=%s", (key,))
                    assert cursor.fetchone() == (status, artifact, "done", speaker, {})
            command.downgrade(migration, "c7a8e9f0b1d2")
            with psycopg2.connect(url) as connection, connection.cursor() as cursor:
                cursor.execute("SELECT memory_artifact FROM meeting_digestions WHERE meeting_id IN %s", (tuple(keys),))
                assert all(row[0] == artifact for row in cursor.fetchall())
