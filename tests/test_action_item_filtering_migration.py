from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import psycopg2
import pytest
from alembic import command
from psycopg2.extras import Json

from tests.test_separate_action_item_proposals import (
    REVISION as PARENT,
    legacy_database as legacy_database,
    legacy_rows,
)

REVISION = "e4b7c9d2a6f1"


def setup_previous(legacy_database):
    migration, url = legacy_database
    meeting, before, payloads = legacy_rows(url)
    command.upgrade(migration, PARENT)
    with psycopg2.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO meeting_sync_state(provider,account_key,source_name,config_fingerprint) "
            "VALUES('test','fixture','Fixture','hash'),('test','new','New','hash')"
        )
    return migration, url, meeting, before, payloads


def test_action_item_filtering_migration_preserves_audit_and_scopes_activation(
    legacy_database,
):
    migration, url, meeting, before, payloads = setup_previous(legacy_database)
    command.upgrade(migration, REVISION)
    with psycopg2.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT state.action_items_activated_at=run.created_at FROM meeting_sync_state state "
            "JOIN meeting_summaries source USING(provider,account_key) "
            "JOIN meeting_action_item_runs run ON run.meeting_id=source.id "
            "WHERE state.account_key='fixture'"
        )
        assert cur.fetchone() == (True,)
        cur.execute(
            "SELECT action_items_activated_at FROM meeting_sync_state WHERE account_key='new'"
        )
        assert (
            abs((datetime.now(timezone.utc) - cur.fetchone()[0]).total_seconds()) < 30
        )
        cur.execute(
            "SELECT to_jsonb(action_item_proposal_payloads) FROM action_item_proposal_payloads ORDER BY proposal_id"
        )
        assert cur.fetchall() == payloads
        cur.execute("SELECT status FROM action_item_proposals ORDER BY id")
        assert [r[0] for r in cur.fetchall()] == [r[9] for r in before]
        cur.execute("SELECT version_num FROM alembic_version")
        assert cur.fetchall() == [(REVISION,)]
    command.downgrade(migration, PARENT)
    command.upgrade(migration, REVISION)


def test_action_item_filtering_migration_blocks_legacy_claim_and_active_upgrade(
    legacy_database,
):
    migration, url, meeting, _, _ = setup_previous(legacy_database)
    with psycopg2.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE meeting_action_item_runs SET claim_owner=%s,claim_until=now()+interval '1 minute' WHERE meeting_id=%s",
            (str(uuid4()), meeting),
        )
    with pytest.raises(RuntimeError, match="Stop Action Item workers"):
        command.upgrade(migration, REVISION)
    with psycopg2.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE meeting_action_item_runs SET claim_until=now()-interval '1 minute'"
        )
    command.upgrade(migration, REVISION)
    with pytest.raises(psycopg2.errors.CheckViolation):
        with psycopg2.connect(url) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE meeting_action_item_runs SET claim_owner=%s,claim_until=now()+interval '1 minute'",
                (str(uuid4()),),
            )
    with psycopg2.connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT claim_owner,claim_until FROM meeting_action_item_runs")
        assert cur.fetchone() == (None, None)
        cur.execute(
            "UPDATE meeting_action_item_runs SET claim_owner=%s,claim_until=now()+interval '1 minute'",
            (f"v2:{uuid4()}",),
        )


def test_action_item_filtering_migration_protects_superseded_from_old_api_delete(
    legacy_database,
):
    migration, url, _, _, _ = setup_previous(legacy_database)
    command.upgrade(migration, REVISION)
    with psycopg2.connect(url) as conn, conn.cursor() as cur:
        cur.execute("UPDATE action_item_proposals SET status='superseded' WHERE id=700")
    with pytest.raises(psycopg2.errors.CheckViolation, match="Dismissals require"):
        with psycopg2.connect(url) as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM action_item_proposals WHERE id=700 FOR UPDATE")
            cur.execute(
                "INSERT INTO action_item_proposal_receipts(decision_key,proposal_id) VALUES(%s,700) ON CONFLICT DO NOTHING",
                ("0" * 64,),
            )
            cur.execute("DELETE FROM action_item_proposals WHERE id=700")
    with psycopg2.connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT status FROM action_item_proposals WHERE id=700")
        assert cur.fetchone() == ("superseded",)
        cur.execute(
            "SELECT count(*) FROM action_item_proposal_receipts WHERE proposal_id=700"
        )
        assert cur.fetchone() == (0,)
        cur.execute("DELETE FROM action_item_proposals WHERE id=700")
    with pytest.raises(psycopg2.errors.CheckViolation, match="Dismissals require"):
        with psycopg2.connect(url) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO action_item_proposal_receipts(decision_key,proposal_id) VALUES(%s,701)",
                ("1" * 64,),
            )


def test_action_item_filtering_migration_receipts_remain_text_free_and_block_fake_supersession(
    legacy_database,
):
    migration, url, _, _, _ = setup_previous(legacy_database)
    command.upgrade(migration, REVISION)
    with psycopg2.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO action_item_proposal_receipts(decision_key,proposal_id) VALUES(%s,700)",
            ("0" * 64,),
        )
    with pytest.raises(psycopg2.errors.CheckViolation, match="Only pending"):
        with psycopg2.connect(url) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE action_item_proposals SET status='superseded' WHERE id=700"
            )
    with psycopg2.connect(url) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM action_item_proposals WHERE id=700")
        cur.execute(
            "SELECT proposal_id FROM action_item_proposal_receipts WHERE decision_key=%s",
            ("0" * 64,),
        )
        assert cur.fetchone() == (None,)


def test_action_item_filtering_migration_replacement_delete_keeps_audit_and_refuses_unsafe_rollback(
    legacy_database,
):
    migration, url, meeting, _, _ = setup_previous(legacy_database)
    command.upgrade(migration, REVISION)
    with pytest.raises(psycopg2.errors.CheckViolation):
        with psycopg2.connect(url) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE action_item_proposals SET status='superseded',superseded_by_id=id WHERE id=700"
            )
    with psycopg2.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE action_item_proposals SET status='superseded',superseded_by_id=701 WHERE id=700"
        )
        cur.execute("DELETE FROM action_item_proposals WHERE id=701")
        cur.execute(
            "SELECT status,superseded_by_id FROM action_item_proposals WHERE id=700"
        )
        assert cur.fetchone() == ("superseded", None)
    with pytest.raises(RuntimeError, match="Cannot downgrade filtered"):
        command.downgrade(migration, PARENT)
    with psycopg2.connect(url) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM action_item_proposals WHERE status='superseded'")
        cur.execute(
            "UPDATE meeting_action_item_runs SET action_items_artifact=%s WHERE meeting_id=%s",
            (Json({"version": 2}), meeting),
        )
    with pytest.raises(RuntimeError, match="Cannot downgrade filtered"):
        command.downgrade(migration, PARENT)


def test_action_item_filtering_migration_validates_rejected_receipts_keys_and_later_source_defaults(
    legacy_database,
):
    migration, url, _, _, _ = setup_previous(legacy_database)
    command.upgrade(migration, REVISION)
    before = datetime.now(timezone.utc)
    with psycopg2.connect(url) as conn, conn.cursor() as cursor:
        cursor.execute(
            "DELETE FROM action_item_proposal_receipts WHERE proposal_id=702"
        )
        cursor.execute(
            "INSERT INTO action_item_proposal_receipts(decision_key,proposal_id) VALUES(%s,702)",
            ("2" * 64,),
        )
        cursor.execute(
            "INSERT INTO meeting_sync_state(provider,account_key,source_name,config_fingerprint) VALUES('test','late-created','Later','hash') RETURNING action_items_activated_at"
        )
        activated = cursor.fetchone()[0]
        assert before <= activated <= datetime.now(timezone.utc)
    with pytest.raises(psycopg2.errors.CheckViolation, match="original decision key"):
        with psycopg2.connect(url) as conn, conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO action_item_proposal_receipts(decision_key,proposal_id) VALUES(%s,700) ON CONFLICT DO NOTHING",
                ("9" * 64,),
            )
