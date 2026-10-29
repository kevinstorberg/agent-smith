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


def test_relationship_migration_protects_legacy_clears_and_refuses_unsafe_downgrade(monkeypatch):
    with temporary_postgres() as url:
        create_database(url)
        monkeypatch.setattr(config, "DATABASE_URL", url)
        migration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(migration, "7f2a9c6d8e10")
        first, second = str(uuid4()), str(uuid4())
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            for key in (first, second):
                cursor.execute("INSERT INTO participant_profiles(id,identity_key,display_name,identity_scope) VALUES(%s,%s,'Known person','manual')", (key, "manual:" + key))
            cursor.execute("INSERT INTO profile_relationships(subject_id,target_id,human_confirmed,notes) VALUES(%s,%s,true,'')", (first, second))
        command.upgrade(migration, "head")
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT notes,analysis_evidence FROM profile_relationships")
            assert cursor.fetchone() == ("", {"version": 1, "human": True})
        command.downgrade(migration, "7f2a9c6d8e10")
        command.upgrade(migration, "head")
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE profile_relationships SET notes='Generated perspective',analysis_evidence=%s", (Json({"version": 1, "human": False}),))
        with pytest.raises(RuntimeError, match="Cannot downgrade"):
            command.downgrade(migration, "7f2a9c6d8e10")
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE profile_relationships SET notes=''")
            snapshot = {"subject_id": first, "target_id": second, "notes": "Historical generated perspective", "analysis_evidence": {"human": False}}
            cursor.execute("INSERT INTO profile_revisions(profile_id,base_revision,new_revision,actor,source,changes) VALUES(%s,1,2,'agent','assessment',%s)",
                           (first, Json({"relationships": {"before": [], "after": [snapshot]}})))
        with pytest.raises(RuntimeError, match="Cannot downgrade"):
            command.downgrade(migration, "7f2a9c6d8e10")
