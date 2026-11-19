from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg2.extras import Json

from scripts.shared.local_postgres import temporary_postgres
from services import config
from services.action_items import db as tasks
from services.action_items import proposals
from services.api.models.action_item_proposal import ActionItemProposalModel
from services.api.routers.action_item_proposals import router
from services.api.routers.proposals import router as harness_router
from services.proposals import service as harness_service
from services.db import get_connection
from services.db.create import create_database
from tests.conftest import clean_harness_rows
from tests.test_action_item_proposals import (
    candidate,
    empty_task_proposals as empty_task_proposals,
    source as source,
    source_factory as source_factory,
)

PARENT = "a9d8c7b6e5f4"
REVISION = "c8f3a2d1e6b9"
FIELDS = "id,action,target_name,project,target_id,base_version,title,rationale,evidence,status,fingerprint,applied_ref,created_at,updated_at"


@pytest.fixture
def legacy_database(monkeypatch):
    migration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with temporary_postgres() as url:
        create_database(url)
        monkeypatch.setattr(config, "DATABASE_URL", url)
        command.upgrade(migration, PARENT)
        yield migration, url


def legacy_rows(url):
    meeting = str(uuid4())
    with psycopg2.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO meeting_summaries(id,source_name,provider,account_key,external_id,source_url,title,summary_text,provider_created_at,provider_updated_at,content_hash) VALUES(%s,'fixture','test','fixture','one','https://example.test/fixture','Fixture','A commitment',now(),now(),%s)",
            (meeting, "a" * 64),
        )
        cur.execute(
            "INSERT INTO action_items(id,title,sort_key) VALUES(91,'Approved task survives',1)"
        )
        for index, status in enumerate(["pending", "approved", "rejected"], start=700):
            cur.execute(
                "INSERT INTO improvement_proposals(id,target_kind,action,target_name,title,rationale,evidence,status,fingerprint,applied_ref) VALUES(%s,'action_item','create','Task','New task','Supported',%s,%s,%s,%s)",
                (
                    index,
                    Json(
                        [{"source": "meeting", "id": meeting, "quote": "A commitment"}]
                    ),
                    status,
                    str(index) * 20,
                    Json({"action_item_id": 91}) if status == "approved" else None,
                ),
            )
            cur.execute(
                "INSERT INTO action_item_proposal_payloads(proposal_id,meeting_id,source_revision,source_hash,source_snapshot,changes,decision_key,create_request_id) VALUES(%s,%s,1,%s,%s,%s,%s,%s)",
                (
                    index,
                    meeting,
                    "a" * 64,
                    Json(
                        {"id": meeting, "revision": 1, "summary_text": "A commitment"}
                    ),
                    Json({"title": "Task"}),
                    str(index)[-1] * 64,
                    str(uuid4()),
                ),
            )
        cur.execute(
            "INSERT INTO action_item_proposal_receipts(decision_key,proposal_id) VALUES(%s,702),(%s,NULL)",
            ("2" * 64, "9" * 64),
        )
        cur.execute(
            "INSERT INTO meeting_action_item_runs(meeting_id,source_revision,source_hash,action_items_status,action_items_artifact) VALUES(%s,1,%s,'done',%s)",
            (meeting, "a" * 64, Json({"published_ids": [700, 701, 702, 699]})),
        )
        cur.execute(
            "INSERT INTO improvement_proposals(id,target_kind,action,proposed_item_id,target_name,title,rationale,fingerprint) VALUES(900,'rule','create',88,'Rule','Harness','Keep','harness')"
        )
        cur.execute(
            "UPDATE improvement_proposals SET action='update',target_id=91,base_version=3 WHERE id=701"
        )
        cur.execute(
            f"SELECT {FIELDS} FROM improvement_proposals WHERE target_kind='action_item' ORDER BY id"
        )
        rows = cur.fetchall()
        cur.execute(
            "SELECT to_jsonb(action_item_proposal_payloads) FROM action_item_proposal_payloads ORDER BY proposal_id"
        )
        payloads = cur.fetchall()
    return meeting, rows, payloads


def test_separate_action_item_migration_preserves_history_payloads_receipts_and_checkpoints(
    legacy_database,
):
    migration, url = legacy_database
    meeting, before, payloads = legacy_rows(url)
    command.upgrade(migration, REVISION)
    with psycopg2.connect(url) as conn, conn.cursor() as cur:
        cur.execute(f"SELECT {FIELDS} FROM action_item_proposals ORDER BY id")
        assert cur.fetchall() == before
        cur.execute(
            "SELECT to_jsonb(action_item_proposal_payloads) FROM action_item_proposal_payloads ORDER BY proposal_id"
        )
        assert cur.fetchall() == payloads
        cur.execute("SELECT id FROM improvement_proposals")
        assert cur.fetchall() == [(900,)]
        cur.execute("SELECT title FROM action_items WHERE id=91")
        assert cur.fetchone()[0] == "Approved task survives"
        cur.execute(
            "SELECT action_items_artifact FROM meeting_action_item_runs WHERE meeting_id=%s",
            (meeting,),
        )
        assert cur.fetchone()[0] == {"published_ids": [700, 701, 702, 699]}
        cur.execute(
            "SELECT proposal_id FROM action_item_proposal_receipts ORDER BY decision_key"
        )
        assert cur.fetchall() == [(702,), (None,)]
        cur.execute(
            "SELECT nextval(pg_get_serial_sequence('action_item_proposals','id'))"
        )
        assert cur.fetchone()[0] == 703
        cur.execute(
            "SELECT confrelid::regclass::text FROM pg_constraint WHERE contype='f' AND conrelid IN ('action_item_proposal_payloads'::regclass,'action_item_proposal_receipts'::regclass)"
        )
        assert {r[0] for r in cur.fetchall()} == {"action_item_proposals"}
    command.downgrade(migration, PARENT)
    with psycopg2.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {FIELDS} FROM improvement_proposals WHERE target_kind='action_item' ORDER BY id"
        )
        assert cur.fetchall() == before
    command.upgrade(migration, REVISION)


def test_separate_action_item_migration_empty_copy_and_harness_constraint(
    legacy_database,
):
    migration, url = legacy_database
    command.upgrade(migration, REVISION)
    with psycopg2.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT nextval(pg_get_serial_sequence('action_item_proposals','id'))"
        )
        assert cur.fetchone()[0] == 1
    with pytest.raises(psycopg2.IntegrityError):
        with psycopg2.connect(url) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO improvement_proposals(target_kind,action,target_name,title,rationale,fingerprint) VALUES('action_item','create','Task','Task','Reason','fingerprint')"
            )


@pytest.mark.parametrize(
    "corruption",
    [
        "missing_payload",
        "foreign_reference",
        "duplicate_child_reference",
        "wrong_domain_checkpoint",
        "active_lease",
    ],
)
def test_separate_action_item_migration_rejects_invalid_cutover_without_data_loss(
    legacy_database, corruption
):
    migration, url = legacy_database
    meeting, before, _ = legacy_rows(url)
    with psycopg2.connect(url) as conn, conn.cursor() as cur:
        if corruption == "missing_payload":
            cur.execute(
                "DELETE FROM action_item_proposal_payloads WHERE proposal_id=700"
            )
        elif corruption == "foreign_reference":
            cur.execute(
                "CREATE TABLE unexpected_proposal_reference(id integer REFERENCES improvement_proposals(id))"
            )
        elif corruption == "duplicate_child_reference":
            cur.execute(
                "ALTER TABLE action_item_proposal_payloads ADD CONSTRAINT unexpected_legacy_link FOREIGN KEY(proposal_id) REFERENCES improvement_proposals(id) ON DELETE CASCADE"
            )
        elif corruption == "wrong_domain_checkpoint":
            cur.execute(
                "UPDATE meeting_action_item_runs SET action_items_artifact=%s WHERE meeting_id=%s",
                (Json({"published_ids": [900]}), meeting),
            )
        else:
            cur.execute(
                "UPDATE meeting_action_item_runs SET claim_owner='active-worker',claim_until=now()+interval '5 minutes' WHERE meeting_id=%s",
                (meeting,),
            )
    with pytest.raises(RuntimeError):
        command.upgrade(migration, REVISION)
    with psycopg2.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {FIELDS} FROM improvement_proposals WHERE target_kind='action_item' ORDER BY id"
        )
        assert cur.fetchall() == before
        cur.execute("SELECT to_regclass('action_item_proposals')")
        assert cur.fetchone()[0] is None


def test_separate_action_item_downgrade_refuses_numeric_id_collisions(legacy_database):
    migration, url = legacy_database
    legacy_rows(url)
    command.upgrade(migration, REVISION)
    with psycopg2.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO improvement_proposals(id,target_kind,action,proposed_item_id,target_name,title,rationale,fingerprint) VALUES(700,'rule','create',99,'Independent','Independent','Keep','independent')"
        )
    with pytest.raises(RuntimeError, match="independent proposal IDs overlap"):
        command.downgrade(migration, PARENT)
    with psycopg2.connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM action_item_proposals")
        assert cur.fetchone()[0] == 3


def test_separate_action_item_apis_do_not_expose_or_decide_harness_records(source):
    proposal = proposals.stage_and_persist(source, candidate())
    app = FastAPI()
    app.include_router(router, prefix="/api/action-item-proposals")
    app.include_router(harness_router, prefix="/api/proposals")
    with TestClient(app) as client:
        response = client.get("/api/action-item-proposals?status=pending").json()
        assert [item["id"] for item in response["items"]] == [proposal["id"]]
        assert all("target_kind" not in item for item in response["items"])
        assert client.get(f"/api/proposals/{proposal['id']}").status_code == 404
        assert (
            client.post(f"/api/proposals/{proposal['id']}/approve").status_code == 404
        )
        assert tasks.list_items({"status": "all"})["total"] == 0
        assert (
            client.post(
                f"/api/action-item-proposals/{proposal['id']}/approve"
            ).status_code
            == 200
        )
        assert tasks.list_items({"status": "all"})["total"] == 1
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM improvement_proposals WHERE target_name=%s",
                (proposal["target_name"],),
            )
            assert cur.fetchone()[0] == 0


def test_separate_action_item_and_harness_decisions_with_the_same_numeric_id(
    source, monkeypatch
):
    name = "sepai_" + uuid4().hex
    harness_id = harness_service.persist_proposal(
        harness_service.stage_proposal(
            {
                "target_kind": "rule",
                "action": "create",
                "target_name": name,
                "title": "Harness review",
                "rationale": "Independent harness change",
                "evidence": [],
                "body": "Synthetic rule",
            }
        )
    )
    create = ActionItemProposalModel.create
    monkeypatch.setattr(
        ActionItemProposalModel,
        "create",
        lambda **fields: create(id=harness_id, **fields),
    )
    proposal = proposals.stage_and_persist(source, candidate())
    app = FastAPI()
    app.include_router(router, prefix="/api/action-item-proposals")
    app.include_router(harness_router, prefix="/api/proposals")
    try:
        with TestClient(app) as client:
            harness = client.get(f"/api/proposals/{harness_id}").json()
            action_item = client.get(f"/api/action-item-proposals/{harness_id}").json()
            assert harness["target_kind"] == "rule" and "target_kind" not in action_item
            assert proposal["id"] == harness_id
            task_review = client.post(
                f"/api/action-item-proposals/{harness_id}/approve"
            ).json()
            task = tasks.get(task_review["applied_ref"]["action_item_id"])
            assert client.get(f"/api/proposals/{harness_id}").json() == harness
            assert (
                client.post(f"/api/proposals/{harness_id}/approve").status_code == 200
            )
            assert tasks.get(task["id"]) == task
            assert client.get("/api/action-item-proposals/counts").json() == {
                "pending": 0,
                "approved": 1,
                "rejected": 0,
            }
    finally:
        harness_service.delete_proposal(harness_id)
        clean_harness_rows(name)
