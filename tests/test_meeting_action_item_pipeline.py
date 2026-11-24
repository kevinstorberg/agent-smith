from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest

from tests.action_item_filter_helpers import filter_decision
from services.graphs.library import meeting_ingest
from services.meetings.action_item_run import ActionItemRun
from tests.test_meeting_action_item_proposals import (
    candidate,
    clean_generated_proposals as clean_generated_proposals,
    feed as feed,
    graph_result,
    install_analysis,
    saved as saved,
)
from tests.test_meeting_sync import source as source


def test_meeting_action_item_pipeline_has_two_real_nodes():
    graph = meeting_ingest.build_graph().get_graph()
    assert "generate_action_items" in graph.nodes
    assert "filter_action_items" in graph.nodes
    assert "propose_action_items" not in graph.nodes
    assert any(
        edge.source == "generate_action_items" and edge.target == "filter_action_items"
        for edge in graph.edges
    )


@pytest.mark.asyncio
async def test_meeting_action_item_pipeline_holds_one_lease_across_visible_nodes(
    source, feed, monkeypatch
):
    from services.meetings import action_item_db

    calls = install_analysis(monkeypatch)
    observed = []

    async def filter_stage(self, record, *, deadline):
        artifact = deepcopy(record["action_items_artifact"])
        assert artifact["version"] == 2 and artifact["phase"] == "generated"
        assert artifact["items"] == [candidate()]
        assert (
            action_item_db.get_record(record["meeting_id"])["claim_owner"] == self.owner
        )
        observed.append((record["meeting_id"], self.owner))
        artifact.update(phase="done", work_units=2)
        action_item_db.save_progress(
            record["meeting_id"], self.owner, artifact, complete=True
        )

    monkeypatch.setattr(ActionItemRun, "_filter_and_publish", filter_stage)
    result = await graph_result(source)
    assert result["action_items"]["outcome"] == "done"
    assert len(calls) == len(observed) == 1
    current = action_item_db.get_record(observed[0][0])
    assert current["claim_owner"] is None
    assert observed[0][1].startswith("v2:")


@pytest.mark.asyncio
async def test_meeting_action_item_pipeline_cancel_between_nodes_preserves_generation(
    source, saved, monkeypatch
):
    from services.meetings import action_item_db

    meeting = saved()
    calls = install_analysis(monkeypatch)
    with pytest.raises(asyncio.CancelledError):
        async with ActionItemRun(source.name) as run:
            await run.prepare()
            await run.generate_candidates()
            assert run.record["action_items_artifact"]["work_units"] == 1
            raise asyncio.CancelledError
    assert action_item_db.get_record(meeting["id"])["claim_owner"] is None
    async with ActionItemRun(source.name) as run:
        await run.prepare()
        await run.generate_candidates()
        assert run.record["action_items_artifact"]["items"] == [candidate()]
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_meeting_action_item_pipeline_legacy_approved_prefix_is_never_reanalyzed(
    source, saved, monkeypatch
):
    from psycopg2.extras import Json
    from services.action_items import db as tasks, proposals
    from services.db import get_connection
    from services.meetings import action_item_run, action_item_db
    from tests.test_action_item_matching import Encoder, BUDGET

    completion = "Morgan confirmed the report is complete."
    meeting = saved(text=completion + " Morgan will send the design document.")
    task = tasks.create({"title": "AIFLOW legacy completed report"})
    old = {
        "action": "update",
        "target_id": task["id"],
        "expected_revision": task["revision"],
        "changes": {"status": "completed"},
        "rationale": "Explicit completion",
        "evidence": [{"segment_id": "summary-0", "quote": completion}],
    }
    proposed = proposals.stage_and_persist(meeting, old)
    approved = proposals.promote_proposal(proposed["id"])
    current = tasks.get(approved["applied_ref"]["action_item_id"])
    tasks.update(
        current["id"], {"expected_revision": current["revision"], "status": "open"}
    )
    legacy = {
        "items": [old, candidate()],
        "offset": 1,
        "total_units": 2,
        "skipped_count": 0,
        "published_ids": [proposed["id"]],
        "input_snapshot": meeting,
        "input_hash": meeting["content_hash"],
    }
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "UPDATE meeting_action_item_runs SET action_items_artifact=%s WHERE meeting_id=%s",
            (Json(legacy), meeting["id"]),
        )

    def forbidden(*args, **kwargs):
        pytest.fail("Completed legacy prefix must not trigger generation")

    monkeypatch.setattr(
        action_item_run.action_item_analysis, "analyze_action_items", forbidden
    )
    monkeypatch.setattr(action_item_run, "get_embeddings", lambda: Encoder())
    monkeypatch.setattr(action_item_run, "get_memory_token_budget", lambda: BUDGET)
    monkeypatch.setattr(action_item_run, "MEMORY_EMBEDDING_DIMENSION", 2)
    observed = []

    async def judge(snapshot, data, **kwargs):
        assert data["candidates"] == [candidate()]
        observed.append(data)
        return {"items": [filter_decision(data)]}

    monkeypatch.setattr(action_item_run.action_item_filter, "analyze_window", judge)
    try:
        async with ActionItemRun(source.name) as run:
            await run.prepare()
            await run.generate_proposals()
            assert run.report["outcome"] == "done"
        state = action_item_db.get_record(meeting["id"])["action_items_artifact"]
        assert observed and state["items"] == [candidate()]
        assert state["legacy_prefix_count"] == 1
        assert proposed["id"] in state["published_ids"]
        assert tasks.get(task["id"])["status"] == "open"
    finally:
        current = tasks.get(task["id"])
        tasks.delete(current["id"], {"expected_revision": current["revision"]})


@pytest.mark.asyncio
async def test_meeting_action_item_pipeline_legacy_adaptation_timeout_records_monotonic_progress(
    source, saved, monkeypatch
):
    from psycopg2.extras import Json
    from services.db import get_connection
    from services.meetings import action_item_db
    from services.meetings.analysis import AnalysisBudgetExpired

    meeting = saved()
    items = [candidate(f"Consumed legacy {i}") for i in range(2)] + [candidate()]
    legacy = {
        "items": items,
        "offset": 2,
        "total_units": 3,
        "skipped_count": 2,
        "published_ids": [],
        "input_snapshot": meeting,
        "input_hash": meeting["content_hash"],
    }
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "UPDATE meeting_action_item_runs SET action_items_artifact=%s WHERE meeting_id=%s",
            (Json(legacy), meeting["id"]),
        )
    save = action_item_db.save_progress

    def timed_out_after_save(key, owner, artifact, **kwargs):
        save(key, owner, artifact, **kwargs)
        if artifact.get("version") == 2:
            raise AnalysisBudgetExpired("Timeout after durable legacy adaptation")

    monkeypatch.setattr(action_item_db, "save_progress", timed_out_after_save)
    async with ActionItemRun(source.name) as run:
        await run.prepare()
        await run.generate_candidates()
        assert run.report["outcome"] == "continued"
        assert run.record["action_items_attempts"] == 0
        assert run.record["action_items_artifact"]["work_units"] == 3
        assert run.record["action_items_artifact"]["items"] == [candidate()]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["order_only", "new_pending", "deleted_witness"])
async def test_meeting_action_item_pipeline_repairs_only_affected_semantic_coverage(
    source, saved, monkeypatch, change
):
    from services.action_items import db as tasks, proposals
    from services.db import get_connection
    from services.meetings import action_item_run
    from tests.test_action_item_matching import Encoder, BUDGET
    from tests.test_meeting_action_item_proposals import generate, make_due

    meeting = saved()
    generated = install_analysis(monkeypatch)
    monkeypatch.setattr(action_item_run, "get_embeddings", lambda: Encoder())
    monkeypatch.setattr(action_item_run, "get_memory_token_budget", lambda: BUDGET)
    monkeypatch.setattr(action_item_run, "MEMORY_EMBEDDING_DIMENSION", 2)
    unrelated = (
        tasks.create({"title": "AIFLOW unrelated order fixture"})
        if change == "order_only"
        else None
    )
    old = (
        proposals.stage_and_persist(meeting, candidate("AIFLOW old paraphrase"))
        if change == "deleted_witness"
        else None
    )
    calls = []

    async def judge(snapshot, data, **kwargs):
        calls.append(data)
        pending = [
            record
            for record in data["comparison_records"]
            if record["kind"] == "proposal" and record["data"]["status"] == "pending"
        ]
        matches = [{"key": pending[0]["key"], "relation": "same"}] if pending else []
        return {"items": [filter_decision(data, matches=matches)]}

    monkeypatch.setattr(action_item_run.action_item_filter, "analyze_window", judge)
    original = proposals.publish_filtered_batch
    changed = False

    def mutate_then_publish(*args, **kwargs):
        nonlocal changed
        if not changed:
            changed = True
            if change == "order_only":
                with get_connection() as conn, conn.cursor() as cursor:
                    tasks.acquire_write_lock(cursor)
                    cursor.execute(
                        "UPDATE action_items SET revision=revision+1 WHERE id=%s",
                        (unrelated["id"],),
                    )
            elif change == "new_pending":
                proposals.stage_and_persist(
                    meeting, candidate("AIFLOW competing paraphrase")
                )
            else:
                proposals.delete_proposal(old["id"])
        return original(*args, **kwargs)

    monkeypatch.setattr(proposals, "publish_filtered_batch", mutate_then_publish)
    try:
        first = await generate(source)
        assert (
            first["outcome"] == "failed"
            and first["error_type"] == "ProposalConflictError"
        )
        make_due(meeting["id"])
        second = await generate(source)
        assert second["outcome"] == "done" and len(generated) == 1
        assert len(calls) == (1 if change == "order_only" else 2)
        if change == "new_pending":
            assert second["proposals"] == 0
        else:
            assert second["proposals"] == 1
    finally:
        if unrelated:
            current = tasks.get(unrelated["id"])
            tasks.delete(current["id"], {"expected_revision": current["revision"]})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["open", "completed"])
async def test_pipeline_does_not_publish_reworded_substeps_of_saved_tasks(
    source, saved, monkeypatch, status
):
    from services.action_items import db as tasks
    from services.meetings import action_item_db, action_item_run
    from tests.test_meeting_action_item_proposals import generate, proposal_rows

    meeting = saved()
    existing = tasks.create(
        {
            "title": "AIFLOW onboard the DevOps contractor and sign the contract",
            "status": status,
            "description": "Megan onboards the contractor and Aaron signs his contract.",
        }
    )
    install_analysis(
        monkeypatch,
        items=[candidate("AIFLOW re-engage the DevOps engineer with a draft contract")],
    )
    observed = []

    async def judge(snapshot, data, **kwargs):
        key = f"task:{existing['id']}"
        supplied = key in data["comparison_pairs"]["0"]
        observed.append(supplied)
        return {
            "items": [
                filter_decision(
                    data,
                    matches=[{"key": key, "relation": "overlap"}] if supplied else [],
                )
            ]
        }

    monkeypatch.setattr(action_item_run.action_item_filter, "analyze_window", judge)
    try:
        result = await generate(source)
        assert result["outcome"] == "done" and result["proposals"] == 0
        assert any(observed) and proposal_rows(source) == []
        assert action_item_db.get_record(meeting["id"])["action_items_status"] == "done"
        assert tasks.get(existing["id"])["status"] == status
    finally:
        current = tasks.get(existing["id"])
        tasks.delete(current["id"], {"expected_revision": current["revision"]})


def test_filter_checkpoint_requires_explicit_coverage_across_windows():
    from services.meetings.action_item_run import _validate_coverage
    from tests.test_meeting_action_item_analysis import SNAPSHOT

    records = {
        f"task:{key}": {
            "key": f"task:{key}",
            "kind": "task",
            "data": {"id": key, "title": f"Independent work {key}"},
        }
        for key in (7, 8)
    }
    keys = list(records)
    prior = {
        "covered_keys": keys,
        "complete": True,
        "results": [
            {
                "candidate_id": 0,
                "actionable": True,
                "matches": [],
                "different_keys": [key],
                "rationale": "An explicit distinct-work verdict",
                "evidence": candidate()["evidence"],
            }
            for key in keys
        ],
    }
    _validate_coverage(prior, candidate(), 0, keys, records, SNAPSHOT)
    prior["results"][0]["different_keys"] = []
    with pytest.raises(ValueError, match="requires explicit"):
        _validate_coverage(prior, candidate(), 0, keys, records, SNAPSHOT)
