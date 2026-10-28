from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg2.extras import Json

from services.api.routers.meetings import router
from services.meetings import db, digestion_db
from services.meetings.config import SourceConfig
from tests.conftest import clean_meeting_rows
from tests.test_meeting_sync import note


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/api/meetings")
    return TestClient(app)


@pytest.fixture
def saved():
    suffix = uuid4().hex
    configs, rows = [], []
    for index in range(2):
        config = SourceConfig(f"reader-{suffix}-{index}", "test", f"reader-{suffix}-{index}", "not-a-real-key", project=f"project-{index}")
        configs.append(config)
        db.claim_source(config, "writer")
        summary = note(text=f"Visible summary {suffix} {index}")
        summary = replace(summary, provider_created_at=summary.provider_created_at + timedelta(days=index))
        saved = db.save_progress(config, "writer", {}, summary=summary)
        rows.append(db.get_summary(saved["id"]))
        db.release_source(config, "writer", "completed")
    yield configs, rows, suffix
    for config in configs:
        clean_meeting_rows(config.account_key)


def test_rest_list_defaults_to_every_connection_and_pages_search_results(client, saved):
    configs, rows, suffix = saved
    response = client.get("/api/meetings")
    assert response.status_code == 200
    assert {row["id"] for row in rows} <= {item["id"] for item in response.json()["items"]}
    first = client.get("/api/meetings", params={"q": suffix, "limit": 1}).json()
    second = client.get("/api/meetings", params={"q": suffix, "limit": 1, "offset": 1}).json()
    assert first["total"] == second["total"] == 2
    assert first["items"][0]["id"] == rows[1]["id"]
    assert second["items"][0]["id"] == rows[0]["id"]
    filtered = client.get("/api/meetings", params={"source": configs[0].name, "project": "project-0", "q": suffix}).json()
    assert filtered["total"] == 1 and filtered["items"][0]["id"] == rows[0]["id"]
    dated = client.get("/api/meetings", params={"q": suffix, "after": "2026-01-02T00:00:00Z"}).json()
    assert dated["total"] == 1 and dated["items"][0]["id"] == rows[1]["id"]


def test_rest_detail_and_list_hide_unavailable_summaries(client, saved):
    configs, rows, suffix = saved
    response = client.get(f"/api/meetings/{rows[0]['id']}")
    assert response.status_code == 200
    assert response.json()["summary_text"] == rows[0]["summary_text"]
    assert response.json()["source_name"] == configs[0].name
    assert response.json()["revision"] == 1
    db.claim_source(configs[0], "hider")
    for _ in range(3):
        db.save_progress(configs[0], "hider", {}, unavailable_id=rows[0]["external_id"])
    db.release_source(configs[0], "hider", "completed_with_warnings")
    assert client.get(f"/api/meetings/{rows[0]['id']}").status_code == 404
    assert client.get(f"/api/meetings/{uuid4()}").status_code == 404
    assert client.get("/api/meetings", params={"q": suffix}).json()["total"] == 1


@pytest.mark.parametrize("params", [
    {"limit": 0}, {"limit": 101}, {"offset": -1}, {"q": " "}, {"q": "x" * 1001},
    {"source": " "}, {"project": " "}, {"after": "2026-01-01"}, {"before": "wrong"},
    {"after": "2026-02-01T00:00:00Z", "before": "2026-01-01T00:00:00Z"},
])
def test_rest_list_rejects_invalid_filters_at_http_boundary(client, params):
    assert client.get("/api/meetings", params=params).status_code == 422


def test_rest_uuid_and_status_boundaries_are_read_only_and_safe(client, saved):
    configs, rows, _ = saved
    assert client.get("/api/meetings/not-a-uuid").status_code == 422
    assert client.post("/api/meetings", json={}).status_code == 405
    assert client.put(f"/api/meetings/{rows[0]['id']}", json={}).status_code == 405
    assert client.delete(f"/api/meetings/{rows[0]['id']}").status_code == 405
    assert client.get("/api/meetings/status", params={"source": " "}).status_code == 422
    response = client.get("/api/meetings/status", params={"source": configs[0].name})
    assert response.status_code == 200
    assert response.json()[0]["source_name"] == configs[0].name
    assert response.json()[0]["outcome"] == "completed"
    assert "claim_owner" not in response.json()[0] and "scan" not in response.json()[0]
    assert "not-a-real-key" not in response.text and "Visible summary" not in response.text


def test_rest_transcript_pages_capture_and_retains_deleted_state(client, saved):
    configs, rows, _ = saved
    config, meeting_id = configs[0], rows[0]["id"]
    claim = digestion_db.claim_transcript([(config.provider, config.account_key)], "router-reader")
    assert claim["meeting_id"] == meeting_id
    segments = [
        {"id": f"segment-{index}", "text": f"Recorded statement {index}", "speaker": {"diarization_label": "Speaker 1"},
         "start_time": "2026-01-01T10:00:00+00:00", "end_time": None}
        for index in range(2)
    ]
    digestion_db.save_capture(meeting_id, "router-reader", digestion_db.get_context(meeting_id), {"segments": segments}, complete=True)
    digestion_db.release(meeting_id, "router-reader")

    first = client.get(f"/api/meetings/{meeting_id}/transcript", params={"limit": 1}).json()
    second = client.get(f"/api/meetings/{meeting_id}/transcript", params={"limit": 1, "offset": 1}).json()
    assert first["status"] == second["status"] == "ready"
    assert first["total"] == second["total"] == 2
    assert first["items"] == segments[:1] and second["items"] == segments[1:]
    assert first["captured_at"] and first["error_type"] is None
    assert "snapshot" not in first and "claim_owner" not in first

    deleted = client.delete(f"/api/meetings/{meeting_id}/transcript")
    assert deleted.status_code == 200 and deleted.json() == {"deleted": True, "id": meeting_id}
    response = client.get(f"/api/meetings/{meeting_id}/transcript").json()
    assert response["status"] == "deleted" and response["items"] == [] and response["total"] == 0
    assert client.post(f"/api/meetings/{meeting_id}/transcript/retry").status_code == 422


def test_rest_transcript_retry_queues_unavailable_capture(client, saved):
    configs, rows, _ = saved
    config, meeting_id = configs[0], rows[0]["id"]
    digestion_db.claim_transcript([(config.provider, config.account_key)], "router-retry")
    digestion_db.record_failure(meeting_id, "router-retry", "TranscriptUnavailable", status="unavailable")
    digestion_db.release(meeting_id, "router-retry")

    response = client.post(f"/api/meetings/{meeting_id}/transcript/retry")
    assert response.status_code == 200 and response.json() == {"success": True}
    queued = client.get(f"/api/meetings/{meeting_id}/transcript").json()
    assert queued["status"] == "pending" and queued["error_type"] is None


def test_rest_transcript_does_not_backfill_old_meetings(client, saved):
    _, rows, _ = saved
    meeting_id = rows[0]["id"]
    with db._cursor() as cur:
        cur.execute("DELETE FROM meeting_digestions WHERE meeting_id = %s", (meeting_id,))

    response = client.get(f"/api/meetings/{meeting_id}/transcript")
    assert response.status_code == 200 and response.json()["status"] == "not_imported"
    assert client.post(f"/api/meetings/{meeting_id}/transcript/retry").status_code == 422
    assert digestion_db.get_record(meeting_id) is None


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}])
def test_rest_transcript_rejects_invalid_paging(client, saved, params):
    _, rows, _ = saved
    assert client.get(f"/api/meetings/{rows[0]['id']}/transcript", params=params).status_code == 422


@pytest.mark.parametrize("suffix,method", [
    ("/transcript", "get"), ("/transcript", "delete"), ("/transcript/retry", "post"),
    ("/memories", "get"), ("/memories/retry", "post"),
])
def test_rest_meeting_artifacts_require_an_available_meeting_and_uuid(client, saved, suffix, method):
    configs, rows, _ = saved
    request = getattr(client, method)
    assert request(f"/api/meetings/not-a-uuid{suffix}").status_code == 422
    assert request(f"/api/meetings/{uuid4()}{suffix}").status_code == 404
    db.claim_source(configs[0], "transcript-hider")
    for _ in range(3):
        db.save_progress(configs[0], "transcript-hider", {}, unavailable_id=rows[0]["external_id"])
    db.release_source(configs[0], "transcript-hider", "completed_with_warnings")
    assert request(f"/api/meetings/{rows[0]['id']}{suffix}").status_code == 404


@pytest.fixture
def captured_for_memories(saved):
    configs, rows, _ = saved
    config, meeting_id = configs[0], rows[0]["id"]
    digestion_db.claim_transcript([(config.provider, config.account_key)], "memory-reader")
    segments = [{"id": "segment-0", "text": "The team agreed to ship next week.", "speaker": {}, "start_time": None, "end_time": None}]
    digestion_db.save_capture(meeting_id, "memory-reader", digestion_db.get_context(meeting_id), {"segments": segments}, complete=True)
    digestion_db.release(meeting_id, "memory-reader")
    return meeting_id


def test_rest_meeting_memories_hide_staging_and_expose_only_the_committed_artifact(client, captured_for_memories):
    meeting_id = captured_for_memories
    item = {
        "id": str(uuid4()), "content": "The team agreed to ship next week.", "kind": "decision",
        "evidence": [{"segment_id": "segment-0", "quote": "The team agreed to ship next week."}],
    }
    artifact = {"offset": 1, "items": [item], "created_at": "2026-10-28T12:00:00+00:00", "reason": None,
                "published_ids": [item["id"]], "private_agent_messages": "PRIVATE_MODEL_CHAIN"}
    with db._cursor() as cur:
        cur.execute("UPDATE meeting_digestions SET memory_artifact = %s WHERE meeting_id = %s", (Json(artifact), meeting_id))

    staged = client.get(f"/api/meetings/{meeting_id}/memories")
    assert staged.status_code == 200 and staged.json()["status"] == "pending"
    assert staged.json()["items"] == [] and item["content"] not in staged.text

    with db._cursor() as cur:
        cur.execute("UPDATE meeting_digestions SET memory_status = 'done', memory_updated_at = clock_timestamp() WHERE meeting_id = %s", (meeting_id,))
    committed = client.get(f"/api/meetings/{meeting_id}/memories")
    assert committed.status_code == 200
    assert committed.json()["status"] == "done" and committed.json()["items"] == [item]
    assert committed.json()["updated_at"]
    assert set(committed.json()) == {"status", "items", "reason", "error_type", "updated_at"}
    assert "PRIVATE_MODEL_CHAIN" not in committed.text and "published_ids" not in committed.text


def test_rest_meeting_memories_retry_only_failed_generation_with_a_complete_transcript(client, captured_for_memories):
    meeting_id = captured_for_memories
    with db._cursor() as cur:
        cur.execute("UPDATE meeting_digestions SET memory_status = 'failed', memory_attempts = 3, memory_error = 'SafeFailure' WHERE meeting_id = %s", (meeting_id,))
    response = client.post(f"/api/meetings/{meeting_id}/memories/retry")
    assert response.status_code == 200 and response.json() == {"success": True}
    queued = client.get(f"/api/meetings/{meeting_id}/memories").json()
    assert queued["status"] == "pending" and queued["error_type"] is None
    assert client.post(f"/api/meetings/{meeting_id}/memories/retry").status_code == 422


@pytest.mark.parametrize("status", ["pending", "deleted", "unsupported", "unavailable", "failed"])
def test_rest_meeting_memories_explain_missing_transcripts_without_queueing_generation(client, saved, status):
    _, rows, _ = saved
    meeting_id = rows[0]["id"]
    with db._cursor() as cur:
        cur.execute("UPDATE meeting_digestions SET transcript_status = %s WHERE meeting_id = %s", (status, meeting_id))
    blocked = client.get(f"/api/meetings/{meeting_id}/memories").json()
    assert blocked["status"] == "blocked" and blocked["reason"] == "transcript_" + status
    assert blocked["items"] == []
    assert client.post(f"/api/meetings/{meeting_id}/memories/retry").status_code == 422


def test_rest_meeting_memories_do_not_backfill_an_older_meeting(client, saved):
    _, rows, _ = saved
    meeting_id = rows[0]["id"]
    with db._cursor() as cur:
        cur.execute("DELETE FROM meeting_digestions WHERE meeting_id = %s", (meeting_id,))
    response = client.get(f"/api/meetings/{meeting_id}/memories")
    assert response.status_code == 200 and response.json()["status"] == "not_imported"
    assert response.json()["items"] == []
    assert client.post(f"/api/meetings/{meeting_id}/memories/retry").status_code == 422
    assert digestion_db.get_record(meeting_id) is None
