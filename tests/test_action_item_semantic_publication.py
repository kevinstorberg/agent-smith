from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from psycopg2.extras import RealDictCursor

from services.action_items import db as tasks, proposal_corpus, proposals
from services.db import get_connection
from services.meetings import action_item_db
from tests.conftest import action_item_owner
from tests.test_action_item_proposals import (
    candidate,
    empty_task_proposals as empty_task_proposals,
    source as source,
    source_factory as source_factory,
)


def claim(source, label="publication"):
    owner = action_item_owner(label)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE meeting_action_item_runs SET claim_owner=%s,claim_until=clock_timestamp()+interval '10 minutes' WHERE meeting_id=%s",
            (owner, source["id"]),
        )
    return owner


def artifact(source, items):
    return {
        "version": 2,
        "phase": "publishing",
        "items": items,
        "input_snapshot": source,
        "input_hash": source["content_hash"],
        "work_units": 2,
        "offset": 0,
        "total_units": len(items),
        "published_ids": [],
        "skipped_count": 0,
    }


def publish(source, items, owner, *, corpus=None, supersede=None, keep=None):
    corpus = corpus or proposal_corpus.snapshot()
    return proposals.publish_filtered_batch(
        source,
        items,
        {
            "keep": list(range(len(items))) if keep is None else keep,
            "supersede": supersede or [],
        },
        expected_digest=corpus["digest"],
        artifact=artifact(source, items),
        lease_owner=owner,
    )


def test_action_item_semantic_publication_commits_batch_and_checkpoint_atomically(
    source,
):
    owner = claim(source)
    result = publish(
        source,
        [candidate(), candidate(title="Prepare another concrete deliverable")],
        owner,
    )
    assert result["stale"] is False and result["proposals"] == 2
    state = action_item_db.get_record(source["id"])
    assert state["action_items_status"] == "done"
    assert (
        state["action_items_artifact"]["published_ids"]
        == result["artifact"]["published_ids"]
    )
    assert tasks.list_items({"status": "all"})["total"] == 0


def test_action_item_semantic_publication_competing_paraphrases_cannot_both_commit(
    source, source_factory
):
    other = source_factory()
    first_owner, second_owner = claim(source, "first"), claim(other, "second")
    frozen = proposal_corpus.snapshot()
    barrier = Barrier(2)

    def run(meeting, owner, title):
        barrier.wait(timeout=5)
        return publish(meeting, [candidate(title=title)], owner, corpus=frozen)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(run, source, first_owner, "Send supplier checklist"),
            pool.submit(run, other, second_owner, "Email vendor readiness list"),
        ]
        results = [future.result(timeout=10) for future in futures]
    assert sorted(result["stale"] for result in results) == [False, True]
    assert proposals.decision_context()["total"] == 1
    loser = source if results[0]["stale"] else other
    owner = first_owner if results[0]["stale"] else second_owner
    fresh = proposal_corpus.snapshot()
    assert any(record["kind"] == "proposal" for record in fresh["records"])
    # A contextual recheck certified this incoming paraphrase as covered.
    assert (
        publish(
            loser,
            [candidate(title="Incoming paraphrase")],
            owner,
            corpus=fresh,
            keep=[],
        )["proposals"]
        == 0
    )
    assert proposals.decision_context()["total"] == 1


def test_action_item_semantic_publication_supersedes_without_dismissal_and_keeps_original_audit(
    source,
):
    old = proposals.stage_and_persist(source, candidate(title="Existing paraphrase"))
    owner = claim(source)
    result = publish(
        source,
        [candidate(title="Fresh supported wording")],
        owner,
        supersede=[{"proposal_id": old["id"], "replacement": "candidate:0"}],
    )
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM action_item_proposals WHERE id=%s", (old["id"],))
        stored = dict(cur.fetchone())
        assert stored["status"] == "superseded"
        assert stored["superseded_by_id"] == result["artifact"]["published_ids"][0]
        for field in ("title", "rationale", "evidence", "fingerprint"):
            assert stored[field] == old[field]
        cur.execute("SELECT count(*) AS count FROM action_item_proposal_receipts")
        assert cur.fetchone()["count"] == 0
    proposals.delete_proposal(old["id"])
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM action_item_proposal_receipts")
        assert cur.fetchone() == (0,)


def test_action_item_semantic_publication_rolls_back_new_rows_supersession_and_checkpoint(
    source, monkeypatch
):
    old = proposals.stage_and_persist(source, candidate(title="Old pending wording"))
    owner = claim(source)
    before = action_item_db.get_record(source["id"])["action_items_artifact"]
    original = proposals._persist_candidate

    def fail_after_insert(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Injected after insertion")

    monkeypatch.setattr(proposals, "_persist_candidate", fail_after_insert)
    with pytest.raises(RuntimeError, match="Injected"):
        publish(
            source,
            [candidate(title="Replacement wording")],
            owner,
            supersede=[{"proposal_id": old["id"], "replacement": "candidate:0"}],
        )
    assert proposals.decision_context()["total"] == 1
    assert (
        next(
            row
            for row in proposals.decision_context()["items"]
            if row["id"] == old["id"]
        )["status"]
        == "pending"
    )
    assert action_item_db.get_record(source["id"])["action_items_artifact"] == before


@pytest.mark.parametrize("mutation", ["task", "proposal", "receipt"])
def test_action_item_semantic_publication_rechecks_complete_corpus_before_writing(
    source, mutation
):
    owner = claim(source)
    frozen = proposal_corpus.snapshot()
    if mutation == "task":
        tasks.create({"title": "New saved work"})
    elif mutation == "proposal":
        proposals.stage_and_persist(source, candidate(title="Other pending work"))
    else:
        row = proposals.stage_and_persist(
            source, candidate(title="Explicitly rejected work")
        )
        proposals.reject_proposal(row["id"])
    current = proposals.decision_context()["total"]
    result = publish(source, [candidate()], owner, corpus=frozen)
    assert result["stale"] is True
    assert proposals.decision_context()["total"] == current
    assert action_item_db.get_record(source["id"])["action_items_status"] == "pending"


def test_action_item_semantic_publication_rejects_replacement_cycles_and_unleased_admission(
    source,
):
    first = proposals.stage_and_persist(source, candidate(title="One"))
    second = proposals.stage_and_persist(source, candidate(title="Two"))
    owner = claim(source)
    with pytest.raises(ValueError, match="cycles"):
        publish(
            source,
            [],
            owner,
            supersede=[
                {"proposal_id": first["id"], "replacement": f"proposal:{second['id']}"},
                {"proposal_id": second["id"], "replacement": f"proposal:{first['id']}"},
            ],
        )
    with pytest.raises(ValueError, match="version-two"):
        publish(source, [candidate()], "old-worker")


def test_action_item_semantic_publication_deleted_rejection_suppresses_replacement_without_blocking_independent_work(
    source, source_factory
):
    from services.meetings import action_item_filter

    rejected = proposals.stage_and_persist(source, candidate())
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "UPDATE meeting_summaries SET revision=revision+1,content_hash=%s WHERE id=%s",
            ("b" * 64, source["id"]),
        )
    prior = source_factory()
    sibling = proposals.stage_and_persist(prior, candidate())
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "UPDATE meeting_summaries SET revision=revision+1,content_hash=%s WHERE id=%s",
            ("c" * 64, prior["id"]),
        )
    proposals.reject_proposal(rejected["id"])
    proposals.delete_proposal(rejected["id"])
    current = source_factory()
    items = [candidate(), candidate(title="Prepare an independent checklist")]
    corpus = proposal_corpus.snapshot()
    dismissed = proposals.dismissed_candidate_indices(current, items, corpus)
    assert dismissed == {0}
    decisions = [
        {
            "candidate_id": index,
            "actionable": True,
            "matches": [{"key": f"proposal:{sibling['id']}", "relation": "same"}]
            if index == 0
            else [],
            "rationale": "Supported work",
            "evidence": item["evidence"],
        }
        for index, item in enumerate(items)
    ]
    filtered = action_item_filter.reduce_decisions(
        items, corpus["records"], [{"items": decisions}], dismissed=dismissed
    )
    assert filtered["keep"] == [1] and filtered["supersede"] == []
    result = proposals.publish_filtered_batch(
        current,
        items,
        filtered,
        expected_digest=corpus["digest"],
        artifact=artifact(current, items),
        lease_owner=claim(current),
    )
    assert result["stale"] is False and result["proposals"] == 1
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT proposal_id FROM action_item_proposal_receipts")
        assert cursor.fetchall() == [(None,)]
        cursor.execute(
            "SELECT status FROM action_item_proposals WHERE id=%s", (sibling["id"],)
        )
        assert cursor.fetchone() == ("pending",)


def test_action_item_semantic_publication_locks_other_proposal_sources_until_freshness_recheck(
    source, source_factory, monkeypatch
):
    from tests.test_proposal_decision_concurrency import (
        watch_decision_connections,
        wait_for_block,
    )

    other = source_factory()
    proposals.stage_and_persist(other, candidate(title="Other pending source"))
    owner = claim(source)
    frozen = proposal_corpus.snapshot()
    watched = watch_decision_connections(monkeypatch, service=proposals)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with get_connection() as blocker, blocker.cursor() as cursor:
            cursor.execute(
                "UPDATE meeting_summaries SET revision=revision+1,content_hash=%s WHERE id=%s",
                ("d" * 64, other["id"]),
            )
            future = pool.submit(publish, source, [candidate()], owner, corpus=frozen)
            wait_for_block(
                cursor, watched.get(timeout=2), future, blocker.get_backend_pid()
            )
        result = future.result(timeout=8)
    assert result["stale"] is True
    assert proposals.decision_context()["total"] == 1
