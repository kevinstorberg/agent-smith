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


def test_assessment_migration_preserves_human_sections_and_completed_work(monkeypatch):
    with temporary_postgres() as url:
        create_database(url)
        monkeypatch.setattr(config, "DATABASE_URL", url)
        migration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(migration, "9d2f6a8c1b40")
        profile_id, meeting_id = str(uuid4()), str(uuid4())
        claims = [{"id": "existing-claim", "content": "Existing evidence"}]
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("""INSERT INTO participant_profiles
                (id,identity_key,display_name,identity_scope,section_notes,claims)
                VALUES (%s,%s,'Synthetic person','manual',%s,%s)""",
                           (profile_id, "manual:" + profile_id, Json({"drivers": "Human assessment"}), Json(claims)))
            cursor.execute("""INSERT INTO meeting_summaries
                (id,provider,account_key,external_id,source_name,summary_text,source_url,
                 provider_created_at,provider_updated_at,content_hash)
                VALUES (%s,'test','test','test','test','Saved summary','https://example.test',now(),now(),'frozen')""",
                           (meeting_id,))
            cursor.execute("""INSERT INTO meeting_digestions
                (meeting_id,memory_status,memory_artifact,profile_status,profile_artifact)
                VALUES (%s,'done',%s,'done',%s)""",
                           (meeting_id, Json({"offset": 42, "published": ["receipt"]}), Json({"offset": 42})))
        for _ in range(2):
            command.upgrade(migration, "head")
            with psycopg2.connect(url) as connection, connection.cursor() as cursor:
                cursor.execute("SELECT section_notes,section_evidence,claims,assessment_dirty FROM participant_profiles WHERE id=%s",
                               (profile_id,))
                assert cursor.fetchone() == ({"drivers": "Human assessment"}, {"drivers": {"human": True}}, claims, True)
                cursor.execute("SELECT labels,labels_revision,labels_source,revision,content_hash FROM meeting_summaries WHERE id=%s", (meeting_id,))
                assert cursor.fetchone() == ([], 0, None, 1, "frozen")
                cursor.execute("SELECT memory_status,memory_artifact,profile_status,profile_artifact FROM meeting_digestions WHERE meeting_id=%s", (meeting_id,))
                assert cursor.fetchone() == ("done", {"offset": 42, "published": ["receipt"]}, "done", {"offset": 42})
                cursor.execute("""UPDATE participant_profiles SET
                    section_notes=section_notes || %s,section_evidence=section_evidence || %s WHERE id=%s""",
                               (Json({"strengths": "Agent assessment"}), Json({"strengths": {"claim_ids": ["existing-claim"]}}), profile_id))
            with pytest.raises(psycopg2.errors.CheckViolation):
                with psycopg2.connect(url) as connection, connection.cursor() as cursor:
                    cursor.execute("UPDATE participant_profiles SET assessment_claim_owner='unpaired' WHERE id=%s", (profile_id,))
            command.downgrade(migration, "9d2f6a8c1b40")
            with psycopg2.connect(url) as connection, connection.cursor() as cursor:
                cursor.execute("SELECT section_notes,claims FROM participant_profiles WHERE id=%s", (profile_id,))
                assert cursor.fetchone() == ({"drivers": "Human assessment"}, claims)
