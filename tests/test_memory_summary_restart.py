import copy
import hashlib
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from psycopg2.extras import Json

from services.db import get_connection
from services.meetings import (
    db,
    digestion_db,
    management_db,
    manual_analysis,
    manual_stage,
    memory_db,
    memory_pass,
)
from tests.test_manual_analysis import (
    finish_stage,
    jobs as jobs,
    payload as payload,
    saved as saved,
)
from tests.test_meeting_sync import source as source
from tests.test_meeting_memory_flow import (
    agents as agents,
    feed as feed,
    ready as ready,
)


def fail(meeting_id, artifact=None):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE meeting_digestions SET memory_status='failed',memory_attempts=3,memory_error='ModelCallTimeoutError' WHERE meeting_id=%s",
            (meeting_id,),
        )
        if artifact is not None:
            cur.execute(
                "UPDATE meeting_digestions SET memory_artifact=%s WHERE meeting_id=%s",
                (Json(artifact), meeting_id),
            )


def update_summary(meeting_id, text, **fields):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE meeting_summaries SET summary_text=%s,revision=revision+1 WHERE id=%s",
            (text, meeting_id),
        )
        for field, value in fields.items():
            assert field in {"source_url", "project"}
            cur.execute(
                f"UPDATE meeting_summaries SET {field}=%s WHERE id=%s",
                (value, meeting_id),
            )


def assert_restarted(meeting_id, text):
    row = digestion_db.get_record(meeting_id)
    artifact = row["memory_artifact"]
    assert (
        row["memory_status"] == "pending"
        and row["memory_attempts"] == 0
        and row["memory_error"] is None
    )
    assert row["claim_owner"] is row["claim_until"] is None
    assert (
        artifact["offset"] == 0
        and artifact["input_source"] == "summary"
        and artifact["prompt_version"] == 4
    )
    assert artifact["input_snapshot"]["summary_text"] == text
    assert artifact["input_hash"] == hashlib.sha256(text.encode()).hexdigest()
    assert artifact["total_units"] == 1
    assert all(
        key not in artifact
        for key in (
            "vocabulary",
            "attribution_snapshot",
            "attribution_identities",
            "context_labels",
            "context_labels_revision",
        )
    )
    return row


def test_retry_restarts_legacy_pass_from_current_summary_and_fences_old_owner(
    source, saved
):
    meeting_id = saved()
    before = digestion_db.get_record(meeting_id)
    artifact = copy.deepcopy(before["memory_artifact"])
    artifact.update(offset=100, total_units=631, prompt_version=3)
    fail(meeting_id, artifact)
    update_summary(meeting_id, "Current Granola summary.")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE meeting_digestions SET claim_owner='retired',claim_until=clock_timestamp()-interval '1 second' WHERE meeting_id=%s",
            (meeting_id,),
        )
    memory_db.retry_memories(meeting_id)
    row = assert_restarted(meeting_id, "Current Granola summary.")
    assert row["memory_artifact"]["pass_start_index"] == len(artifact["items"])
    assert row["memory_artifact"]["items"] == artifact["items"]
    assert row["memory_artifact"]["published_ids"] == artifact["published_ids"]
    assert row["memory_artifact"]["created_at"] == artifact["created_at"]
    assert {k: v for k, v in row.items() if k.startswith("profile_")} == {
        k: v for k, v in before.items() if k.startswith("profile_")
    }
    with pytest.raises(db.ClaimLostError):
        memory_db.save_progress(meeting_id, "retired", row["transcript_hash"], artifact)
    with pytest.raises(ValueError):
        memory_db.retry_memories(meeting_id)


def test_repeated_retries_preserve_uncertain_publication_payload_across_summary_source_changes(
    source, saved
):
    meeting_id = saved()
    before = digestion_db.get_record(meeting_id)
    artifact = copy.deepcopy(before["memory_artifact"])
    item = {
        "id": str(uuid4()),
        "content": "An older decision",
        "kind": "decision",
        "tags": ["product"],
        "evidence": [
            {"segment_id": "segment-9", "quote": "Private old transcript quote"}
        ],
    }
    artifact["items"].append(item)
    artifact["total_units"] = artifact["offset"]
    expected = memory_pass.publication_payload(
        meeting_id, before["snapshot"], artifact, item
    )
    fail(meeting_id, artifact)
    update_summary(
        meeting_id,
        "New summary.",
        project="new-project",
        source_url="https://example.test/new",
    )
    memory_db.retry_memories(meeting_id)
    first = assert_restarted(meeting_id, "New summary.")
    assert first["memory_artifact"]["publication_envelopes"][item["id"]] == expected
    fail(meeting_id)
    update_summary(
        meeting_id,
        "Newest summary.",
        project="next-project",
        source_url="https://example.test/next",
    )
    memory_db.retry_memories(meeting_id)
    second = assert_restarted(meeting_id, "Newest summary.")
    assert (
        second["memory_artifact"]["publication_envelopes"]
        == first["memory_artifact"]["publication_envelopes"]
    )
    assert second["memory_artifact"]["items"] == artifact["items"]


@pytest.mark.parametrize(
    "boundary",
    [
        "blank_summary",
        "duplicate_id",
        "unknown_receipt",
        "oversized",
        "memory_lease",
        "profile_lease",
    ],
)
def test_invalid_restart_leaves_every_stage_unchanged(source, saved, boundary):
    meeting_id = saved()
    artifact = digestion_db.get_record(meeting_id)["memory_artifact"]
    if boundary == "duplicate_id":
        artifact["items"].append(copy.deepcopy(artifact["items"][0]))
    if boundary == "unknown_receipt":
        artifact["published_ids"].append(str(uuid4()))
    if boundary == "oversized":
        artifact["reason"] = "x" * 2_000_000
    fail(meeting_id, artifact)
    if boundary == "blank_summary":
        update_summary(meeting_id, "\t\n")
    if boundary.endswith("lease"):
        prefix = "profile_" if boundary == "profile_lease" else ""
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"UPDATE meeting_digestions SET {prefix}claim_owner='active',{prefix}claim_until=clock_timestamp()+interval '5 minutes' WHERE meeting_id=%s",
                (meeting_id,),
            )
    before = digestion_db.get_record(meeting_id)
    with pytest.raises((ValueError, manual_analysis.AnalysisConflict)):
        memory_db.retry_memories(meeting_id)
    assert digestion_db.get_record(meeting_id) == before


def test_direct_retry_detaches_only_memory_scope_and_keeps_historical_receipt(
    source, saved, payload, jobs
):
    meeting_id = saved()
    jobs()
    jobs("meeting_ingest")
    request = manual_analysis.request_analysis(payload(meeting_id, scope="both"))
    finish_stage(meeting_id, "memory", status="failed")
    before = digestion_db.get_record(meeting_id)
    historical = manual_analysis.get_request(request["request_id"])["items"][0][
        "stages"
    ]["memory"]
    update_summary(meeting_id, "Latest summary after confirmation.")
    memory_db.retry_memories(meeting_id)
    after = assert_restarted(meeting_id, "Latest summary after confirmation.")
    assert (
        "memory" not in after["manual_analysis"]
        and "manual_request_id" not in after["memory_artifact"]
    )
    assert after["manual_analysis"]["profile"] == before["manual_analysis"]["profile"]
    assert (
        manual_analysis.get_request(request["request_id"])["items"][0]["stages"][
            "memory"
        ]
        == historical
    )
    frozen = copy.deepcopy(after)
    with pytest.raises(manual_analysis.AnalysisConflict):
        manual_stage.resume_request(request["request_id"])
    assert digestion_db.get_record(meeting_id) == frozen


def test_manual_memory_resume_restarts_summary_but_retains_immutable_request_and_other_stage(
    source, saved, payload, jobs
):
    meeting_id = saved()
    jobs()
    jobs("meeting_ingest")
    request = manual_analysis.request_analysis(payload(meeting_id, scope="both"))
    finish_stage(meeting_id, "profile", status="done")
    artifact = digestion_db.get_record(meeting_id)["memory_artifact"]
    artifact.update(offset=12, reason="Old pass", vocabulary=[{"term": "stale"}])
    finish_stage(meeting_id, "memory", status="failed", artifact=artifact)
    before = digestion_db.get_record(meeting_id)
    manual_stage.resume_request(request["request_id"])
    after = assert_restarted(meeting_id, db.get_summary(meeting_id)["summary_text"])
    assert after["manual_analysis"]["memory"]["request_id"] == request["request_id"]
    assert after["memory_artifact"]["manual_request_id"] == request["request_id"]
    assert {k: v for k, v in after.items() if k.startswith("profile_")} == {
        k: v for k, v in before.items() if k.startswith("profile_")
    }


def test_processing_failed_memory_uses_summary_restart_without_reopening_done_profile(
    source, saved
):
    meeting_id = saved()
    fail(meeting_id)
    update_summary(meeting_id, "Summary used by Process meeting.")
    before = digestion_db.get_record(meeting_id)
    assert management_db.request_processing(meeting_id) == {"status": "queued"}
    after = assert_restarted(meeting_id, "Summary used by Process meeting.")
    assert (
        after["profile_status"] == "done"
        and after["profile_artifact"] == before["profile_artifact"]
    )


def test_concurrent_retries_queue_one_summary_pass(source, saved):
    meeting_id = saved()
    fail(meeting_id)

    def retry():
        try:
            memory_db.retry_memories(meeting_id)
            return "queued"
        except ValueError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: retry(), range(2)))
    assert sorted(results) == ["queued", "rejected"]
    assert_restarted(meeting_id, db.get_summary(meeting_id)["summary_text"])


@pytest.mark.parametrize("status", ["failed", "unsupported", "unavailable"])
def test_processing_requeues_capture_before_its_summary_memory_pass(
    source, saved, status
):
    meeting_id = saved()
    fail(meeting_id)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE meeting_digestions SET transcript_status=%s WHERE meeting_id=%s",
            (status, meeting_id),
        )
    before = digestion_db.get_record(meeting_id)
    assert management_db.request_processing(meeting_id) == {"status": "queued"}
    after = assert_restarted(meeting_id, db.get_summary(meeting_id)["summary_text"])
    assert after["transcript_status"] == "pending"
    assert (
        after["profile_artifact"] == before["profile_artifact"]
        and after["profile_status"] == "done"
    )


def test_ambiguous_legacy_manual_publication_cannot_be_reconstructed_from_changed_source(
    source, saved, payload, jobs
):
    meeting_id = saved()
    jobs("meeting_ingest")
    manual_analysis.request_analysis(payload(meeting_id, scope="memories"))
    artifact = digestion_db.get_record(meeting_id)["memory_artifact"]
    for key in ("input_source", "input_snapshot", "input_hash"):
        artifact.pop(key, None)
    artifact["items"].append(
        {
            "id": str(uuid4()),
            "content": "Uncertain legacy output",
            "kind": "fact",
            "evidence": [],
        }
    )
    artifact["offset"] = artifact["total_units"]
    artifact["next_item_index"] = len(artifact["items"])
    finish_stage(meeting_id, "memory", status="failed", artifact=artifact)
    update_summary(meeting_id, "Changed current summary.", project="changed-project")
    before = digestion_db.get_record(meeting_id)
    with pytest.raises(ValueError, match="uncertain publications"):
        memory_db.retry_memories(meeting_id)
    assert digestion_db.get_record(meeting_id) == before


def test_partial_legacy_manual_candidates_do_not_require_reconstructing_changed_source(
    source, saved, payload, jobs
):
    meeting_id = saved()
    jobs("meeting_ingest")
    manual_analysis.request_analysis(payload(meeting_id, scope="memories"))
    artifact = digestion_db.get_record(meeting_id)["memory_artifact"]
    for key in ("input_source", "input_snapshot", "input_hash"):
        artifact.pop(key, None)
    candidate = {
        "id": str(uuid4()),
        "content": "Never published candidate",
        "kind": "fact",
        "evidence": [],
    }
    artifact["items"].append(candidate)
    artifact.update(offset=1, total_units=2, next_item_index=2)
    finish_stage(meeting_id, "memory", status="failed", artifact=artifact)
    update_summary(
        meeting_id,
        "A new summary after the incomplete pass.",
        project="changed-project",
    )
    memory_db.retry_memories(meeting_id)
    restarted = assert_restarted(
        meeting_id, "A new summary after the incomplete pass."
    )["memory_artifact"]
    assert [item["id"] for item in restarted["items"]] == artifact["published_ids"]
    assert (
        restarted["next_item_index"] == 2
        and candidate["id"] not in restarted["publication_envelopes"]
    )


@pytest.mark.parametrize("phase", ["completed", "incomplete", "untrusted_hash"])
def test_retry_without_old_total_uses_the_shared_capture_completion_proof(
    source, ready, phase
):
    row = digestion_db.get_record(ready)
    item = {
        "id": str(uuid4()),
        "content": "Legacy candidate",
        "kind": "fact",
        "evidence": [],
    }
    assert all(
        0 < len(segment["text"]) <= memory_pass.WINDOW_CHARS
        for segment in row["transcript"]["segments"]
    )
    units = len(row["transcript"]["segments"])
    artifact = {
        "version": 1,
        "items": [item],
        "published_ids": [],
        "created_at": "2026-01-01T00:00:00+00:00",
        "offset": units - 1 if phase == "incomplete" else units,
        "reason": "",
    }
    fail(ready, artifact)
    if phase == "untrusted_hash":
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE meeting_digestions SET transcript_hash='untrusted' WHERE meeting_id=%s",
                (ready,),
            )
        before = digestion_db.get_record(ready)
        with pytest.raises(ValueError, match="publication phase is unknown"):
            memory_db.retry_memories(ready)
        assert digestion_db.get_record(ready) == before
        return
    update_summary(
        ready,
        "The current saved summary.",
        project="new-project",
        source_url="https://example.test/current",
    )
    memory_db.retry_memories(ready)
    after = assert_restarted(ready, "The current saved summary.")["memory_artifact"]
    assert after["next_item_index"] == 1
    if phase == "completed":
        assert after["items"] == [item]
        assert after["publication_envelopes"][
            item["id"]
        ] == memory_pass.publication_payload(ready, row["snapshot"], artifact, item)
    else:
        assert after["items"] == [] and after["publication_envelopes"] == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("lost", ["ack", "receipt"])
async def test_retry_replays_old_frozen_publication_and_analyzes_only_new_summary(
    source, ready, agents, monkeypatch, lost
):
    from services.meetings import enrichment
    from services.memory import db as vector_db

    item = {
        "id": str(uuid4()),
        "content": "A legacy output awaiting its receipt",
        "kind": "decision",
        "tags": ["product"],
        "evidence": [{"segment_id": "segment-99", "quote": "OLD_QUOTE_CANARY"}],
    }
    artifact = {
        "version": 1,
        "items": [item],
        "published_ids": [],
        "created_at": "2026-01-01T00:00:00+00:00",
        "offset": 1,
        "total_units": 1,
        "reason": "",
    }
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE meeting_digestions SET memory_artifact=%s WHERE meeting_id=%s",
            (Json(artifact), ready),
        )
    before = digestion_db.get_record(ready)
    expected = memory_pass.publication_payload(
        ready, before["snapshot"], artifact, item
    )
    failed = []
    original_save, original_publish = memory_db.save_progress, vector_db.publish
    if lost == "ack":

        def publish(*args, **kwargs):
            result = original_publish(*args, **kwargs)
            if not failed:
                failed.append(True)
                raise RuntimeError("Synthetic lost ACK")
            return result

        monkeypatch.setattr(vector_db, "publish", publish)
    else:

        def save(*args, **kwargs):
            if item["id"] in args[3]["published_ids"] and not failed:
                failed.append(True)
                raise RuntimeError("Synthetic lost receipt")
            return original_save(*args, **kwargs)

        monkeypatch.setattr(memory_db, "save_progress", save)
    async with enrichment.DigestionRun(source.name) as run:
        await run.prepare()
        await run.generate_memories()
        assert run.memory_report["outcome"] == "failed"
    assert agents.analyses == []
    stored = copy.deepcopy(agents.stored[item["id"]])
    first = digestion_db.get_record(ready)["memory_artifact"]
    assert (
        first["publication_envelopes"][item["id"]] == expected
        and first["published_ids"] == []
    )
    fail(ready)
    update_summary(
        ready,
        "The retry must analyze this saved summary.",
        project="new-project",
        source_url="https://example.test/new",
    )
    memory_db.retry_memories(ready)
    assert_restarted(ready, "The retry must analyze this saved summary.")
    update_summary(
        ready,
        "LATER_SUMMARY_CANARY",
        project="later-project",
        source_url="https://example.test/later",
    )
    async with enrichment.DigestionRun(source.name) as run:
        await run.prepare()
        await run.generate_memories()
        assert run.memory_report["outcome"] == "done"
    assert len(agents.analyses) == 1 and agents.analyses[0][2] == []
    assert agents.analyses[0][1] == [
        {"id": "summary-0", "text": "The retry must analyze this saved summary."}
    ]
    assert "OLD_QUOTE_CANARY" not in repr(agents.analyses)
    assert agents.stored[item["id"]] == stored
    assert agents.publications.count(item["id"]) == 2
    final = digestion_db.get_record(ready)["memory_artifact"]
    assert len(final["published_ids"]) == len(final["items"]) == 2
    assert final["publication_envelopes"][item["id"]] == expected
