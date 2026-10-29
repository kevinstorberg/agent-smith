import asyncio
import json
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from services.meetings import db, digestion_db, label_analysis, labels_db
from services.meetings.analysis import MemoryAnalysisError, analyze_memories
from services.meetings.outputs import MemorySubmission
from services.meetings.topics import normalize_topics
from tests.test_meeting_memory_agent import ITEM, SEGMENTS, SNAPSHOT, backend as backend, call, model as model
from tests.test_meeting_memory_flow import feed as feed, ready as ready
from tests.test_meeting_sync import note, source as source
from tests.test_meetings_router import client as client, saved as saved


def test_topics_have_one_canonical_form_and_legacy_submissions_remain_readable():
    assert normalize_topics(["Product", " Roadmaps ", "roadmapping", "Vendor Evaluation"]) == ["product", "roadmapping", "vendor-evaluation"]
    assert normalize_topics([]) == []
    assert MemorySubmission(items=[]).context_labels == []


@pytest.mark.parametrize("labels", [["fact", "decision"], ["meeting-memory"], ["meeting:123"], [" "], ["x" * 51], ["product"] * 9, [1], "product"])
def test_topics_reject_origin_identifiers_and_invalid_boundary_values(labels):
    with pytest.raises(ValueError):
        normalize_topics(labels)


def test_label_edit_is_separate_from_provider_revision_and_digestion(client, saved):
    configs, rows, _ = saved
    meeting_id = rows[0]["id"]
    before = digestion_db.get_record(meeting_id)
    response = client.patch(f"/api/meetings/{meeting_id}/labels", json={"expected_revision": 0, "labels": ["Security", " Roadmap "]})
    assert response.status_code == 200
    assert response.json() == {"labels": ["security", "roadmapping"], "labels_revision": 1, "labels_source": "human"}
    assert db.get_summary(meeting_id)["revision"] == rows[0]["revision"]
    assert digestion_db.get_record(meeting_id) == before
    assert client.patch(f"/api/meetings/{meeting_id}/labels", json={"expected_revision": 0, "labels": []}).status_code == 409
    assert client.get("/api/meetings", params=[("labels", "security"), ("labels", "roadmap")]).json()["items"][0]["id"] == meeting_id
    assert client.get("/api/meetings", params={"labels": "growth"}).json()["total"] == 0
    config = configs[0]
    db.claim_source(config, "label-replay")
    db.save_progress(config, "label-replay", {}, summary=replace(note(), summary_text="Later provider edit", provider_updated_at=note().provider_updated_at + timedelta(hours=1)))
    db.release_source(config, "label-replay", "completed")
    current = db.get_summary(meeting_id)
    assert current["labels"] == ["security", "roadmapping"] and current["labels_source"] == "human"
    assert current["labels_revision"] == 1 and current["revision"] == 2


def test_empty_human_labels_are_protected_and_identical_save_is_idempotent(client, saved):
    _, rows, _ = saved
    meeting_id = rows[0]["id"]
    assert labels_db.update(meeting_id, 0, []) == {"labels": [], "labels_revision": 1, "labels_source": "human"}
    assert labels_db.update(meeting_id, 1, [])["labels_revision"] == 1
    assert client.patch(f"/api/meetings/{meeting_id}/labels", json={"expected_revision": 1, "expected_meeting_revision": 0, "labels": ["product"]}).status_code == 409
    assert client.patch(f"/api/meetings/{meeting_id}/labels", json={"expected_revision": 1, "labels": ["fact"]}).status_code == 422
    assert client.patch(f"/api/meetings/{uuid4()}/labels", json={"expected_revision": 0, "labels": []}).status_code == 404


@pytest.mark.parametrize("body", [{"expected_revision": True, "labels": []}, {"expected_revision": -1, "labels": []}, {"expected_revision": 0, "labels": ["product"] * 9}])
def test_label_http_boundaries(client, saved, body):
    assert client.patch(f"/api/meetings/{saved[1][0]['id']}/labels", json=body).status_code == 422


@pytest.mark.parametrize("case,expected", [("new", "applied"), ("human_clear", "human_owned"), ("changed_source", "stale_source"), ("changed_labels", "stale_labels")])
def test_automatic_labels_respect_owner_source_and_label_revisions(source, ready, case, expected):
    owner = "labels-agent"
    record = digestion_db.claim_digestion([(source.provider, source.account_key)], owner)
    assert record["meeting_id"] == ready
    try:
        if case == "human_clear":
            labels_db.update(ready, 0, [])
        elif case == "changed_source":
            with db._cursor() as cur:
                cur.execute("UPDATE meeting_summaries SET revision = revision + 1 WHERE id = %s", (ready,))
        elif case == "changed_labels":
            with db._cursor() as cur:
                cur.execute("UPDATE meeting_summaries SET labels = ARRAY['operations'], labels_source = 'agent', labels_revision = 1 WHERE id = %s", (ready,))
        result = labels_db.apply_from_memory(ready, owner, record["transcript_hash"], record["snapshot"]["revision"], 0, ["Product", "Roadmaps"])
        assert result == expected
        if case == "new":
            assert labels_db.snapshot(ready)["labels"] == ["product", "roadmapping"]
            assert labels_db.apply_from_memory(ready, owner, record["transcript_hash"], record["snapshot"]["revision"], 0, ["product", "roadmapping"]) == "unchanged"
            assert labels_db.snapshot(ready)["labels_revision"] == 1
        if case == "human_clear":
            assert labels_db.snapshot(ready)["labels"] == []
        with pytest.raises(db.ClaimLostError):
            labels_db.apply_from_memory(ready, "another-owner", record["transcript_hash"], 1, 0, ["product"])
        with pytest.raises(db.ClaimLostError):
            labels_db.apply_from_memory(ready, owner, "wrong-hash", 1, 0, ["product"])
    finally:
        digestion_db.release(ready, owner)


@pytest.mark.asyncio
@pytest.mark.parametrize("include_empty", [False, True])
async def test_new_memory_stage_requires_whole_meeting_subjects(backend, model, include_empty):
    stage = AIMessage(content="", tool_calls=[{
        "name": "stage_memories", "args": {"items": [ITEM], **({"context_labels": []} if include_empty else {})},
        "id": "missing-context", "type": "tool_call",
    }])
    model([
        call("search_previous_memories", query="release"),
        stage, AIMessage(content="Done"),
    ])
    with pytest.raises(MemoryAnalysisError, match="without a valid staged result"):
        await analyze_memories(SNAPSHOT, SEGMENTS, [])


@pytest.mark.asyncio
async def test_label_suggestion_only_reads_bounded_saved_summary_and_never_persists(model):
    instance, roles = model([call("stage_labels", labels=["Security", "Roadmap", "vendor-evaluation"]), AIMessage(content="Done")])
    snapshot = {"title": "Security scoping", "project": "explicit-project", "summary_text": "S" * 32_000 + "AFTER_LIMIT",
                "transcript": "PRIVATE_TRANSCRIPT_SENTINEL", "labels": ["security"]}
    assert await label_analysis.suggest_labels(snapshot) == {"labels": ["security", "roadmapping", "vendor-evaluation"], "reason": ""}
    assert roles == [("meeting_memory", "curator")]
    assert instance.tool_names == ["stage_labels"]
    quoted = next(message.content for message in instance.seen[0] if isinstance(message, HumanMessage))
    assert "PRIVATE_TRANSCRIPT_SENTINEL" not in quoted and "AFTER_LIMIT" not in quoted
    data = json.loads(quoted.split("\n", 1)[1])
    assert data["summary_truncated"] and data["summary_characters"] > len(data["summary"])


def test_suggest_preview_does_not_save_until_explicit_revision_checked_save(client, saved, model):
    _, rows, _ = saved
    meeting_id = rows[0]["id"]
    model([call("stage_labels", labels=["product", "roadmapping"]), AIMessage(content="Done")])
    response = client.post(f"/api/meetings/{meeting_id}/labels/suggest", json={"expected_revision": 0})
    assert response.status_code == 200
    assert response.json() == {"labels": ["product", "roadmapping"], "labels_revision": 0, "meeting_revision": 1}
    assert labels_db.snapshot(meeting_id)["labels"] == []
    response = client.patch(f"/api/meetings/{meeting_id}/labels", json={"labels": response.json()["labels"], "expected_revision": 0, "expected_meeting_revision": 1})
    assert response.status_code == 200 and response.json()["labels_source"] == "human"


@pytest.mark.parametrize("change", ["labels", "summary"])
def test_suggest_rejects_changes_during_model_wait(client, saved, monkeypatch, change):
    meeting_id = saved[1][0]["id"]

    async def changed(snapshot, *, deadline):
        if change == "labels":
            labels_db.update(meeting_id, 0, ["operations"])
        else:
            with db._cursor() as cur:
                cur.execute("UPDATE meeting_summaries SET revision = revision + 1 WHERE id = %s", (meeting_id,))
        return {"labels": ["product"]}

    monkeypatch.setattr(label_analysis, "suggest_labels", changed)
    response = client.post(f"/api/meetings/{meeting_id}/labels/suggest", json={"expected_revision": 0})
    assert response.status_code == 409
    assert labels_db.snapshot(meeting_id)["labels"] == (["operations"] if change == "labels" else [])


def test_suggestion_timeout_is_explicit_and_leaves_saved_labels_unchanged(client, saved, monkeypatch):
    async def stalled(*args, **kwargs):
        await asyncio.sleep(60)

    monkeypatch.setattr(label_analysis, "SUGGEST_SECONDS", 0.02)
    monkeypatch.setattr(label_analysis, "suggest_labels", stalled)
    meeting_id = saved[1][0]["id"]
    response = client.post(f"/api/meetings/{meeting_id}/labels/suggest", json={"expected_revision": 0})
    assert response.status_code == 504 and labels_db.snapshot(meeting_id)["labels_revision"] == 0


@pytest.mark.asyncio
async def test_summary_classifier_has_three_turn_limit(model):
    instance, _ = model([call("stage_labels", labels=["product"]) for _ in range(4)])
    with pytest.raises(label_analysis.LabelAnalysisError, match="ModelCallLimitExceededError"):
        await label_analysis.suggest_labels({"summary_text": "Product planning", "labels": []})
    assert len(instance.seen) == 3
