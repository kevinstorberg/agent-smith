from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from alembic import command
from alembic.config import Config
from psycopg2.errors import CheckViolation, UniqueViolation
from psycopg2.extras import Json

from scripts.shared.local_postgres import temporary_postgres
from services import config
from services.db.create import create_database


def test_manual_analysis_migration_preserves_saved_work_and_bounds_durable_controls(monkeypatch):
    with temporary_postgres() as url:
        create_database(url)
        monkeypatch.setattr(config, "DATABASE_URL", url)
        migration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(migration, "91b2c3d4e5f6")
        meeting_id, request_id = str(uuid4()), str(uuid4())
        transcript = {"segments": [{"id": "old", "text": "Saved source text"}]}
        artifact = {"version": 1, "offset": 2, "items": [{"id": str(uuid4()), "content": "Already published"}]}
        artifact["published_ids"] = [artifact["items"][0]["id"]]
        with psycopg2.connect(url) as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO meeting_summaries(id,provider,account_key,external_id,source_name,summary_text,
                source_url,provider_created_at,provider_updated_at,content_hash)
                VALUES(%s,'granola','migration-test','old-note','test','Saved summary','https://example.test',now(),now(),'hash')""", (meeting_id,))
            cur.execute("""INSERT INTO meeting_digestions(meeting_id,transcript_status,transcript,memory_status,memory_artifact)
                VALUES(%s,'ready',%s,'done',%s)""", (meeting_id, Json(transcript), Json(artifact)))
            cur.execute("SELECT to_jsonb(d) FROM meeting_digestions d WHERE meeting_id=%s", (meeting_id,))
            before = cur.fetchone()[0]
        command.upgrade(migration, "head")
        with psycopg2.connect(url) as conn, conn.cursor() as cur:
            cur.execute("SELECT to_jsonb(d) FROM meeting_digestions d WHERE meeting_id=%s", (meeting_id,))
            after = cur.fetchone()[0]
            assert after.pop("manual_analysis") == {} and after == before
            cur.execute("INSERT INTO meeting_analysis_requests(request_id,payload,result) VALUES(%s,'{}','{}')", (request_id,))
        with pytest.raises(UniqueViolation):
            with psycopg2.connect(url) as conn, conn.cursor() as cur:
                cur.execute("INSERT INTO meeting_analysis_requests(request_id,payload,result) VALUES(%s,'{}','{}')", (request_id,))
        for field, invalid in (("payload", []), ("result", []), ("payload", {"oversized": "x" * 50_000}),
                               ("result", {"oversized": "x" * 100_000})):
            with pytest.raises(CheckViolation):
                with psycopg2.connect(url) as conn, conn.cursor() as cur:
                    cur.execute(f"UPDATE meeting_analysis_requests SET {field}=%s WHERE request_id=%s", (Json(invalid), request_id))
        for invalid in ([], {"oversized": "x" * 10_000}):
            with pytest.raises(CheckViolation):
                with psycopg2.connect(url) as conn, conn.cursor() as cur:
                    cur.execute("UPDATE meeting_digestions SET manual_analysis=%s WHERE meeting_id=%s", (Json(invalid), meeting_id))
        marker = {"memory": {"request_id": request_id, "active": False}}
        with psycopg2.connect(url) as conn, conn.cursor() as cur:
            cur.execute("UPDATE meeting_digestions SET manual_analysis=%s WHERE meeting_id=%s", (Json(marker), meeting_id))
        with pytest.raises(RuntimeError, match="request controls exist"):
            command.downgrade(migration, "91b2c3d4e5f6")
        with psycopg2.connect(url) as conn, conn.cursor() as cur:
            cur.execute("SELECT manual_analysis FROM meeting_digestions WHERE meeting_id=%s", (meeting_id,))
            assert cur.fetchone()[0] == marker
            cur.execute("SELECT count(*) FROM meeting_analysis_requests WHERE request_id=%s", (request_id,))
            assert cur.fetchone()[0] == 1
            cur.execute("UPDATE meeting_digestions SET manual_analysis='{}' WHERE meeting_id=%s", (meeting_id,))
        command.downgrade(migration, "91b2c3d4e5f6")
        command.upgrade(migration, "head")
        with psycopg2.connect(url) as conn, conn.cursor() as cur:
            cur.execute("SELECT to_jsonb(d) FROM meeting_digestions d WHERE meeting_id=%s", (meeting_id,))
            roundtrip = cur.fetchone()[0]
            assert roundtrip.pop("manual_analysis") == {} and roundtrip == before
