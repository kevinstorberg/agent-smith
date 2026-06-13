"""Schema-level guarantees for improvement proposals (tracer bullet 1).

Proposed rows live in the real harness/job tables with state='proposed'
(harness rows additionally have version IS NULL). These tests prove the
invisibility contract: no existing read path may ever surface them.
"""
from __future__ import annotations

import psycopg2
import pytest

from psycopg2.extras import Json

from services.api.models.shared.harness import (
    get_item,
    get_item_by_id,
    get_version_history,
    get_version_history_summary,
    list_items,
    list_items_full,
    update_content,
    upsert_item,
)
from services.config import ALL_AGENTS
from services.db import get_connection
from services.jobs.models.job import get_job, list_jobs, update_job
from services.jobs.service import create_job_with_default_config
from tests.conftest import harness_cleanup, jobs_cleanup

RULE_CONTENT = {"body": "## Proposal Test Rule", "metadata": {}}

_clean_harness = harness_cleanup("proptest_%")
_clean_jobs = jobs_cleanup("PROPTEST %")


@pytest.fixture(autouse=True)
def _clean_proposals():
    yield
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM improvement_proposals WHERE target_name LIKE 'proptest_%'")


def insert_proposed_harness_row(table: str, name: str, body: str, project: str | None = None) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {table} (name, project, agents, subagents, content, sort_key, enabled, version, state)
                VALUES (%s, %s, %s, %s, %s, 0, true, NULL, 'proposed')
                RETURNING id
                """,
                (name, project, [], [], Json({"body": body, "metadata": {}})),
            )
            return cur.fetchone()[0]


def insert_proposed_job_row(name: str) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO background_jobs (name, schedule_config, input_params, state)
                VALUES (%s, %s, %s, 'proposed')
                RETURNING id
                """,
                (name, Json({"hours": 1}), Json({"command": "echo proposed"})),
            )
            return cur.fetchone()[0]


def test_proposed_harness_row_invisible_to_all_read_paths():
    upsert_item("rule", "proptest_rule", content=RULE_CONTENT, agents=ALL_AGENTS)
    proposed_id = insert_proposed_harness_row("harness_rules", "proptest_rule", "## Proposed edit")

    listed = [r for r in list_items("rule") if r["name"] == "proptest_rule"]
    assert len(listed) == 1 and listed[0]["version"] == 1

    listed_full = [r for r in list_items_full("rule") if r["name"] == "proptest_rule"]
    assert len(listed_full) == 1 and listed_full[0]["id"] != proposed_id

    assert get_item("rule", "proptest_rule")["id"] != proposed_id
    assert all(v["id"] != proposed_id for v in get_version_history("rule", "proptest_rule"))
    assert all(v["id"] != proposed_id for v in get_version_history_summary("rule", "proptest_rule"))


def test_proposed_harness_row_readable_by_id():
    insert_proposed_harness_row("harness_rules", "proptest_byid", "## Proposed")
    proposed_id = insert_proposed_harness_row("harness_rules", "proptest_byid", "## Proposed again")
    row = get_item_by_id("rule", proposed_id)
    assert row is not None
    assert row["state"] == "proposed"
    assert row["version"] is None


def test_multiple_proposed_rows_per_name_allowed():
    insert_proposed_harness_row("harness_rules", "proptest_multi", "## One")
    insert_proposed_harness_row("harness_rules", "proptest_multi", "## Two")


def test_active_rows_still_unique_per_name_project_version():
    upsert_item("rule", "proptest_unique", content=RULE_CONTENT, agents=ALL_AGENTS)
    with pytest.raises(psycopg2.IntegrityError):
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO harness_rules (name, project, agents, subagents, content, sort_key, enabled, version)
                    VALUES ('proptest_unique', NULL, '{}', '{}', %s, 0, true, 1)
                    """,
                    (Json(RULE_CONTENT),),
                )


def test_update_content_rejects_proposed_rows():
    proposed_id = insert_proposed_harness_row("harness_rules", "proptest_noedit", "## Proposed")
    with pytest.raises(AssertionError, match="proposed row"):
        update_content("rule", proposed_id, {"body": "## New", "metadata": {}})


def test_proposed_job_invisible_to_list_but_readable_by_id():
    create_job_with_default_config("PROPTEST active", {"hours": 1}, {"command": "echo hi"})
    proposed_id = insert_proposed_job_row("PROPTEST proposed")

    names = [j["name"] for j in list_jobs(limit=1000)[0]]
    assert "PROPTEST active" in names
    assert "PROPTEST proposed" not in names

    row = get_job(proposed_id)
    assert row is not None and row["state"] == "proposed"


def test_proposed_job_may_share_name_with_active_job():
    create_job_with_default_config("PROPTEST shared", {"hours": 1}, {"command": "echo hi"})
    insert_proposed_job_row("PROPTEST shared")

    with pytest.raises(psycopg2.IntegrityError):
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO background_jobs (name, schedule_config, input_params)
                    VALUES ('PROPTEST shared', %s, %s)
                    """,
                    (Json({"hours": 1}), Json({"command": "echo dup"})),
                )


def test_job_update_bumps_version():
    job_id = create_job_with_default_config("PROPTEST bump", {"hours": 1}, {"command": "echo hi"})
    assert get_job(job_id)["version"] == 1
    update_job(job_id, description="bumped")
    assert get_job(job_id)["version"] == 2


def test_pending_fingerprint_unique_index():
    def insert_proposal(status: str):
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO improvement_proposals
                        (target_kind, action, proposed_item_id, target_name, title, rationale, status, fingerprint)
                    VALUES ('rule', 'create', 1, 'proptest_fp', 't', 'r', %s, 'fp-abc')
                    """,
                    (status,),
                )

    insert_proposal("pending")
    with pytest.raises(psycopg2.IntegrityError):
        insert_proposal("pending")
    insert_proposal("rejected")
