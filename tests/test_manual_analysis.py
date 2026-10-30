from __future__ import annotations

import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg2.extras import Json
from pydantic import ValidationError

from services.api.routers.meeting_analysis import router
from services.db import get_connection
from services.jobs.models.job import get_job
from services.jobs.service import create_job_with_default_config
from services.meetings import db as meeting_db, digestion_db, manual_analysis as analysis, manual_candidates, manual_stage, profile_db
from services.meetings.manual_analysis_contracts import AnalysisRequest
from tests.test_meeting_profiles_db import ready_meeting
from tests.test_meeting_sync import source as source


@pytest.fixture
def target():
    row = profile_db.create_profile("Manual analysis target", email=f"manual-{uuid4().hex}@example.test")
    yield row
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM participant_profiles WHERE id=%s OR merged_into=%s", (row["id"], row["id"]))


@pytest.fixture
def saved(source):
    def create(*, person=None, suffix=None):
        meeting_id = ready_meeting(source, suffix or uuid4().hex)
        memory_id = str(uuid4())
        artifact = {"version": 1, "offset": 2, "created_at": "2026-01-01T00:00:00+00:00",
            "items": [{"id": memory_id, "content": "A previously saved fact", "kind": "fact", "evidence": []}],
            "published_ids": [memory_id], "reason": "", "vocabulary": [{"term": "old", "definition": "Old context"}],
            "attribution_snapshot": {"old": "snapshot"}, "context_labels": ["prior"]}
        manual = [{"profile_id": person["id"], "name": person["display_name"], "email": person["email"], "segment_id": "segment-0"}] if person else []
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("UPDATE meeting_summaries SET manual_participants=%s WHERE id=%s", (Json(manual), meeting_id))
            cur.execute("""UPDATE meeting_digestions SET profile_status='done',profile_artifact=%s,profile_updated_at=clock_timestamp(),
                memory_status='done',memory_artifact=%s,memory_updated_at=clock_timestamp(),speaker_updated_at=clock_timestamp()
                WHERE meeting_id=%s""", (Json({"version": 1, "offset": 2, "items": [], "profile_ids": [], "reason": "No previous observations"}), Json(artifact), meeting_id))
        return meeting_id
    return create


@pytest.fixture
def payload():
    request_ids = []
    def build(*meeting_ids, scope="profiles", person=None):
        request_id = str(uuid4())
        request_ids.append(request_id)
        result = {"request_id": request_id, "confirmed": True, "scope": scope,
                  "meetings": [{"id": meeting_id, "expected": analysis.expected_values(meeting_db.get_summary(meeting_id), digestion_db.get_record(meeting_id))}
                               for meeting_id in meeting_ids]}
        if person:
            result["target_profile"] = {"id": person["id"], "expected_revision": person["revision"]}
        return result
    yield build
    if request_ids:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM meeting_analysis_requests WHERE request_id IN %s", (tuple(request_ids),))


@pytest.fixture
def jobs(source):
    ids = []
    def create(kind="persona", *, inputs=None, device="*", enabled=True):
        job_id = create_job_with_default_config("MANUAL " + uuid4().hex, {"minutes": 15},
            {"graph_type": kind, "graph_inputs": {"source": source.name} if inputs is None else inputs, "timeout": 600}, device=device)
        ids.append(job_id)
        if not enabled:
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute("UPDATE job_configs SET enabled=false WHERE job_id=%s", (job_id,))
        return get_job(job_id)
    yield create
    if ids:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM background_jobs WHERE id IN %s", (tuple(ids),))


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/api/meeting-analysis")
    return TestClient(app)


def test_manual_analysis_profile_request_reopens_only_selected_stage_and_preserves_memories(source, target, saved, payload, jobs):
    selected, unrelated = saved(person=target), saved()
    job = jobs()
    before, other = digestion_db.get_record(selected), digestion_db.get_record(unrelated)
    body = payload(selected, person=target)
    receipt = analysis.request_analysis(body)
    assert receipt["request_id"] == body["request_id"] and receipt["status"] == "queued"
    assert receipt["target_profile_id"] == target["id"]
    stage = receipt["items"][0]["stages"]["profile"]
    assert stage["job_id"] == job["id"] and stage["status"] == "queued"
    row = digestion_db.get_record(selected)
    assert row["profile_status"] == "pending" and row["profile_artifact"] == {}
    assert row["memory_status"] == "done" and row["memory_artifact"] == before["memory_artifact"]
    assert row["memory_updated_at"] == before["memory_updated_at"]
    assert row["transcript"] == before["transcript"] and row["snapshot"] == before["snapshot"]
    assert row["manual_analysis"]["profile"]["target"]["id"] == target["id"]
    assert row["manual_analysis"]["profile"]["source"] == {key: body["meetings"][0]["expected"][key] for key in analysis.SOURCE_FIELDS}
    assert digestion_db.get_record(unrelated) == other
    assert profile_db.get_profile(target["id"])["claims"] == []
    assert "transcript_hash" not in json.dumps(receipt, default=str) and "A previously saved fact" not in json.dumps(receipt, default=str)


def test_manual_analysis_both_scope_keeps_frozen_memory_ids_and_receipts(source, saved, payload, jobs):
    meeting_id = saved()
    jobs()
    jobs("meeting_ingest")
    before = digestion_db.get_record(meeting_id)
    receipt = analysis.request_analysis(payload(meeting_id, scope="both"))
    row = digestion_db.get_record(meeting_id)
    assert set(receipt["items"][0]["stages"]) == {"profile", "memory"}
    assert row["profile_status"] == row["memory_status"] == "pending"
    assert row["memory_artifact"]["items"] == before["memory_artifact"]["items"]
    assert row["memory_artifact"]["published_ids"] == before["memory_artifact"]["published_ids"]
    assert row["memory_artifact"]["created_at"] == before["memory_artifact"]["created_at"]
    assert row["memory_artifact"]["offset"] == 0
    assert "vocabulary" not in row["memory_artifact"] and "attribution_snapshot" not in row["memory_artifact"]


def test_manual_analysis_frozen_replay_returns_current_done_receipt_without_reopening(source, saved, payload, jobs):
    meeting_id = saved()
    jobs()
    body = payload(meeting_id)
    first = analysis.request_analysis(body)
    before = digestion_db.get_record(meeting_id)
    assert analysis.request_analysis(copy.deepcopy(body))["request_id"] == first["request_id"]
    assert digestion_db.get_record(meeting_id) == before
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""UPDATE meeting_digestions SET profile_status='done',profile_updated_at=clock_timestamp(),
            manual_analysis=jsonb_set(manual_analysis,'{profile,active}','false'::jsonb) WHERE meeting_id=%s""", (meeting_id,))
        cur.execute("""UPDATE meeting_analysis_requests SET result=jsonb_set(result,'{items,0,stages,profile,status}','\"done\"'::jsonb)
            WHERE request_id=%s""", (body["request_id"],))
    completed = digestion_db.get_record(meeting_id)
    assert analysis.request_analysis(body)["status"] == "done"
    assert digestion_db.get_record(meeting_id) == completed
    changed = copy.deepcopy(body)
    changed["scope"] = "both"
    with pytest.raises(analysis.AnalysisConflict, match="different selection"):
        analysis.request_analysis(changed)
    changed = copy.deepcopy(body)
    changed["request_id"] = str(uuid4())
    with pytest.raises(analysis.AnalysisConflict, match="profile_updated_at changed"):
        analysis.request_analysis(changed)


def test_manual_analysis_batch_replay_normalizes_meeting_order_and_copies_input(source, saved, payload, jobs):
    meetings = [saved(), saved()]
    jobs()
    body = payload(*reversed(meetings))
    original = copy.deepcopy(body)
    receipt = analysis.request_analysis(body)
    assert body == original
    reverse = copy.deepcopy(body)
    reverse["meetings"].reverse()
    assert analysis.request_analysis(reverse)["request_id"] == receipt["request_id"]
    body["meetings"][0]["expected"]["account_key"] = "mutated-after-submission"
    assert analysis.get_request(receipt["request_id"])["status"] == "queued"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT payload FROM meeting_analysis_requests WHERE request_id=%s", (receipt["request_id"],))
        assert "mutated-after-submission" not in json.dumps(cur.fetchone()[0])


def test_manual_analysis_invalid_later_selection_rolls_back_the_entire_batch(source, saved, payload, jobs):
    meetings = [saved(), saved()]
    jobs()
    before = {meeting_id: digestion_db.get_record(meeting_id) for meeting_id in meetings}
    body = payload(*sorted(meetings))
    body["meetings"][-1]["expected"]["meeting_revision"] += 1
    with pytest.raises(analysis.AnalysisConflict, match="meeting_revision"):
        analysis.request_analysis(body)
    assert analysis.get_request(body["request_id"]) is None
    assert all(digestion_db.get_record(meeting_id) == before[meeting_id] for meeting_id in meetings)


def test_manual_analysis_receipt_and_all_reopen_writes_roll_back_together(source, saved, payload, jobs, monkeypatch):
    meetings = [saved(), saved()]
    jobs()
    body = payload(*meetings)
    before = {meeting_id: digestion_db.get_record(meeting_id) for meeting_id in meetings}
    original, calls = analysis._reopen, []
    def failed(cur, request_id, entry):
        original(cur, request_id, entry)
        calls.append(entry["meeting_id"])
        if len(calls) == 2:
            raise RuntimeError("Synthetic second write failure")
    monkeypatch.setattr(analysis, "_reopen", failed)
    with pytest.raises(RuntimeError, match="second write failure"):
        analysis.request_analysis(body)
    assert analysis.get_request(body["request_id"]) is None
    assert all(digestion_db.get_record(meeting_id) == before[meeting_id] for meeting_id in meetings)


@pytest.mark.parametrize("field", ["provider", "account_key", "source_name", "meeting_revision", "transcript_hash",
                                    "participants_revision", "speaker_updated_at", "profile_updated_at"])
def test_manual_analysis_rejects_every_stale_selected_source_boundary(source, saved, payload, jobs, field):
    meeting_id = saved()
    jobs()
    body = payload(meeting_id)
    expected = body["meetings"][0]["expected"]
    if field.endswith("_at"):
        expected[field] = "2000-01-01T00:00:00+00:00"
    elif field in {"meeting_revision", "participants_revision"}:
        expected[field] += 1
    elif field == "transcript_hash":
        expected[field] = "f" * 64
    else:
        expected[field] += "-stale"
    before = digestion_db.get_record(meeting_id)
    with pytest.raises(analysis.AnalysisConflict, match=field):
        analysis.request_analysis(body)
    assert digestion_db.get_record(meeting_id) == before


@pytest.mark.parametrize("status", ["pending", "failed"])
def test_manual_analysis_unfinished_stages_keep_their_checkpoints_for_resume(source, saved, payload, jobs, status):
    meeting_id = saved()
    jobs()
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_digestions SET profile_status=%s,profile_attempts=2 WHERE meeting_id=%s", (status, meeting_id))
    before = digestion_db.get_record(meeting_id)
    with pytest.raises(analysis.AnalysisConflict, match="Resume unfinished"):
        analysis.request_analysis(payload(meeting_id))
    assert digestion_db.get_record(meeting_id) == before


@pytest.mark.parametrize("boundary", ["claim_until", "profile_claim_until", "speaker_status", "transcript_status", "memory_publication"])
def test_manual_analysis_refuses_active_or_unready_work_without_resetting_progress(source, saved, payload, jobs, boundary):
    meeting_id = saved()
    jobs()
    jobs("meeting_ingest")
    with get_connection() as conn, conn.cursor() as cur:
        if boundary.endswith("until"):
            cur.execute(f"UPDATE meeting_digestions SET {boundary}=%s WHERE meeting_id=%s", (datetime.now(timezone.utc) + timedelta(minutes=5), meeting_id))
        elif boundary == "speaker_status":
            cur.execute("UPDATE meeting_digestions SET speaker_status='pending' WHERE meeting_id=%s", (meeting_id,))
        elif boundary == "transcript_status":
            cur.execute("UPDATE meeting_digestions SET transcript_status='deleted' WHERE meeting_id=%s", (meeting_id,))
        else:
            cur.execute("UPDATE meeting_digestions SET memory_artifact=jsonb_set(memory_artifact,'{published_ids}','[]'::jsonb) WHERE meeting_id=%s", (meeting_id,))
    before = digestion_db.get_record(meeting_id)
    with pytest.raises(analysis.AnalysisConflict):
        analysis.request_analysis(payload(meeting_id, scope="memories" if boundary == "memory_publication" else "profiles"))
    assert digestion_db.get_record(meeting_id) == before


def test_manual_analysis_target_requires_current_identity_revision_and_real_statement_mapping(source, saved, payload, jobs, target):
    meeting_id = saved()
    jobs()
    with pytest.raises(analysis.AnalysisConflict, match="Assign this profile"):
        analysis.request_analysis(payload(meeting_id, person=target))
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_summaries SET metadata=%s WHERE id=%s", (Json({"attendees": [{"name": target["display_name"], "email": target["email"]}]}), meeting_id))
    with pytest.raises(analysis.AnalysisConflict, match="Assign this profile"):
        analysis.request_analysis(payload(meeting_id, person=target))
    mapped = saved(person=target)
    stale = payload(mapped, person={**target, "revision": target["revision"] + 1})
    with pytest.raises(analysis.AnalysisConflict, match="Target profile changed"):
        analysis.request_analysis(stale)
    assert analysis.request_analysis(payload(mapped, person=target))["target_profile_id"] == target["id"]


@pytest.mark.parametrize("kind,inputs,device,enabled", [
    ("persona", {"profile_id": "00000000-0000-0000-0000-000000000001"}, "*", True),
    ("persona", {"source": "another-source"}, "*", True),
    ("persona", {}, "not-this-device", True), ("persona", {}, "*", False),
    ("meeting_ingest", {"digest": False}, "*", True),
    ("meeting_ingest", {"meeting_id": "00000000-0000-0000-0000-000000000001"}, "*", True),
])
def test_manual_analysis_real_job_coverage_rejects_nonworkers(source, saved, payload, jobs, kind, inputs, device, enabled):
    meeting_id = saved()
    jobs(kind, inputs=inputs, device=device, enabled=enabled)
    with pytest.raises(analysis.AnalysisConflict, match="Configure a normal"):
        analysis.request_analysis(payload(meeting_id, scope="memories" if kind == "meeting_ingest" else "profiles"))


def test_manual_analysis_memory_worker_requires_matching_configured_provider_account(source, saved, payload, jobs, monkeypatch):
    meeting_id = saved()
    jobs("meeting_ingest")
    monkeypatch.setenv("MEETING_SOURCES_JSON", json.dumps({source.name: {"provider": source.provider, "account_key": "wrong-account", "api_key_env": "MEETING_SYNC_TEST_KEY"}}))
    with pytest.raises(analysis.AnalysisConflict, match="Configure a normal"):
        analysis.request_analysis(payload(meeting_id, scope="memories"))


def test_manual_analysis_progress_reports_disabled_worker_without_losing_authorization(source, saved, payload, jobs):
    meeting_id = saved()
    job = jobs()
    receipt = analysis.request_analysis(payload(meeting_id))
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE job_configs SET enabled=false WHERE job_id=%s", (job["id"],))
    current = analysis.get_request(receipt["request_id"])
    assert current["status"] == "queued"
    assert current["items"][0]["stages"]["profile"]["waiting_for"] == "job"
    assert digestion_db.get_record(meeting_id)["manual_analysis"]["profile"]["active"]


@pytest.mark.parametrize("same_uuid", [False, True])
def test_manual_analysis_concurrent_requests_enqueue_one_authorized_pass(source, saved, payload, jobs, same_uuid):
    meeting_id = saved()
    jobs()
    first = payload(meeting_id)
    second = copy.deepcopy(first) if same_uuid else payload(meeting_id)
    barrier = threading.Barrier(2)
    def submit(body):
        barrier.wait(timeout=5)
        try:
            return analysis.request_analysis(body)
        except analysis.AnalysisConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, [first, second]))
    accepted = [result for result in results if isinstance(result, dict)]
    assert len(accepted) == (2 if same_uuid else 1)
    assert len({result["request_id"] for result in accepted}) == 1
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM meeting_analysis_requests WHERE request_id IN %s", ((first["request_id"], second["request_id"]),))
        assert cur.fetchone()[0] == 1


def test_manual_analysis_candidates_recover_a_mapped_zero_claim_profile_without_artifact_membership(source, target, saved, jobs):
    meeting_id, other = saved(person=target), saved()
    job = jobs()
    result = manual_candidates.list_candidates(profile_id=target["id"], source=source.name)
    assert result["total"] == 1 and result["items"][0]["id"] == meeting_id
    item = result["items"][0]
    assert "participant_assignment" in item["match_reasons"] and item["attribution_ready"]
    assert item["stages"]["profile"]["can_reanalyze"] and item["stages"]["profile"]["job_id"] == job["id"]
    assert result["profile"]["revision"] == target["revision"]
    assert profile_db.get_profile(target["id"])["claims"] == []
    assert digestion_db.get_record(meeting_id)["profile_artifact"]["profile_ids"] == []
    all_meetings = manual_candidates.list_candidates(profile_id=target["id"], related=False, source=source.name)
    assert {item["id"] for item in all_meetings["items"]} == {meeting_id, other}
    exact = manual_candidates.list_candidates(meeting_id=other, related=False)
    assert exact["total"] == 1 and exact["items"][0]["id"] == other


def test_manual_analysis_name_and_nickname_discovery_never_implies_statement_ownership(source, target, saved, payload, jobs):
    profile = profile_db.update_metadata(target["id"], target["revision"], nicknames=["Distinct Nickname"])
    meeting_id = saved()
    jobs()
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_summaries SET metadata=%s WHERE id=%s", (Json({"attendees": [{"name": "DISTINCT NICKNAME"}]}), meeting_id))
    result = manual_candidates.list_candidates(profile_id=profile["id"], source=source.name)
    assert result["total"] == 1
    item = result["items"][0]
    assert "attendee_name" in item["match_reasons"]
    assert not item["attribution_ready"] and not item["stages"]["profile"]["can_reanalyze"]
    with pytest.raises(analysis.AnalysisConflict, match="Assign this profile"):
        analysis.request_analysis(payload(meeting_id, person=profile))
    assert profile_db.get_profile(profile["id"])["claims"] == []


def test_manual_analysis_related_alias_emails_are_case_insensitive_and_profile_ids_are_canonical(source, target, saved, jobs):
    alias = profile_db.create_profile("Historical manual name", email=f"historical-{uuid4().hex}@example.test")
    try:
        canonical = profile_db.merge_profiles(alias["id"], target["id"], alias["revision"], target["revision"])
        meeting_id = saved()
        jobs()
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("UPDATE meeting_summaries SET metadata=%s WHERE id=%s", (Json({"attendees": [{"name": "Historical manual name", "email": alias["email"].upper()}]}), meeting_id))
        result = manual_candidates.list_candidates(profile_id=alias["id"], source=source.name)
        assert result["profile"]["id"] == canonical["id"]
        assert result["total"] == 1 and "attendee_email" in result["items"][0]["match_reasons"]
        assert not result["items"][0]["attribution_ready"]
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM participant_profiles WHERE id=%s", (alias["id"],))


@pytest.mark.parametrize("identity_source", ["speaker", "identified"])
def test_manual_analysis_candidates_find_saved_speaker_identities_without_claims(source, target, saved, jobs, identity_source):
    meeting_id = saved()
    jobs()
    with get_connection() as conn, conn.cursor() as cur:
        if identity_source == "speaker":
            cur.execute("UPDATE meeting_digestions SET transcript=jsonb_set(transcript,'{segments,0,speaker}',%s) WHERE meeting_id=%s",
                        (Json({"name": target["display_name"], "email": target["email"].upper()}), meeting_id))
        else:
            artifact = {"assignments": [{"segment_id": "segment-0", "profile_id": target["id"], "name": target["display_name"], "confidence": "high"}],
                        "committed_transcript_hash": digestion_db.get_record(meeting_id)["transcript_hash"]}
            cur.execute("UPDATE meeting_digestions SET speaker_artifact=%s WHERE meeting_id=%s", (Json(artifact), meeting_id))
    result = manual_candidates.list_candidates(profile_id=target["id"], source=source.name)
    assert result["total"] == 1 and result["items"][0]["attribution_ready"]
    assert ("transcript_speaker" if identity_source == "speaker" else "identified_speaker") in result["items"][0]["match_reasons"]


def test_manual_analysis_candidate_sql_search_filters_and_pages_before_results(source, saved, jobs):
    meetings = [saved() for _ in range(3)]
    jobs()
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_summaries SET title='Roadmap Needle',summary_text='Security overview' WHERE id=%s", (meetings[0],))
        cur.execute("UPDATE meeting_summaries SET title='Unrelated title',summary_text='Operations overview' WHERE id=%s", (meetings[1],))
        cur.execute("UPDATE meeting_summaries SET available=false WHERE id=%s", (meetings[2],))
        cur.execute("UPDATE meeting_digestions SET transcript=jsonb_set(transcript,'{segments,0,text}',%s) WHERE meeting_id=%s",
                    (Json("A special saved transcript phrase"), meetings[1]))
    first = manual_candidates.list_candidates(source=source.name, related=False, limit=1)
    second = manual_candidates.list_candidates(source=source.name, related=False, limit=1, offset=1)
    assert first["total"] == second["total"] == 2
    assert [item["id"] for item in first["items"] + second["items"]] == sorted(meetings[:2])
    assert manual_candidates.list_candidates(source=source.name, query="SECURITY")["items"][0]["id"] == meetings[0]
    assert manual_candidates.list_candidates(source=source.name, query="special saved transcript")["total"] == 0
    assert manual_candidates.list_candidates(source=source.name, query="special saved transcript", search_transcript=True)["items"][0]["id"] == meetings[1]
    assert manual_candidates.list_candidates(source=source.name, query="' OR true --")["total"] == 0
    assert manual_candidates.list_candidates(source=source.name, after="2027-01-01T00:00:00Z")["total"] == 0
    assert manual_candidates.list_candidates(source=source.name, offset=100)["items"] == []


@pytest.mark.parametrize("values", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"related": 1}, {"search_transcript": True},
                                   {"query": " "}, {"query": "x" * 1001}, {"source": " "},
                                   {"after": "2026-02-01T00:00:00Z", "before": "2026-01-01T00:00:00Z"}])
def test_manual_analysis_candidate_validation_is_read_only(values):
    with pytest.raises(ValueError):
        manual_candidates.list_candidates(**values)


@pytest.mark.parametrize("mutate", [
    lambda body: body.update(confirmed=False), lambda body: body.update(confirmed=1),
    lambda body: body.update(confirmed="true"), lambda body: body.update(force=True),
    lambda body: body.update(scope="invalid"), lambda body: body.update(meetings=[]),
    lambda body: body.update(meetings=body["meetings"] * 2),
    lambda body: body["meetings"][0]["expected"].update(force=True),
    lambda body: body["meetings"][0]["expected"].update(meeting_revision=True),
    lambda body: body["meetings"][0]["expected"].update(speaker_updated_at="2026-01-01T00:00:00"),
])
def test_manual_analysis_request_schema_is_strict_before_any_write(source, saved, payload, mutate):
    body = payload(saved())
    mutate(body)
    with pytest.raises(ValidationError):
        AnalysisRequest.model_validate(body)
    assert analysis.get_request(body["request_id"]) is None


def test_manual_analysis_rest_boundaries_echo_durable_receipts_without_triggering_workers(client, source, target, saved, payload, jobs):
    meeting_id = saved(person=target)
    jobs()
    candidates = client.get("/api/meeting-analysis/candidates", params={"profile_id": target["id"], "source": source.name}).json()
    assert candidates["items"][0]["expected"]
    body = payload(meeting_id, person=target)
    response = client.post("/api/meeting-analysis/requests", json=body)
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "queued"
    assert client.get("/api/meeting-analysis/requests/" + body["request_id"]).json() == response.json()
    assert client.post("/api/meeting-analysis/requests", json={**body, "confirmed": False}).status_code == 422
    assert client.get("/api/meeting-analysis/requests/not-a-uuid").status_code == 422
    assert client.get("/api/meeting-analysis/requests/" + str(uuid4())).status_code == 404


@pytest.mark.parametrize("operation", ["request", "candidates"])
def test_manual_analysis_rest_reports_shared_profile_conflicts_as_409(client, source, saved, payload, monkeypatch, operation):
    def busy(*args, **kwargs):
        raise profile_db.ProfileRevisionConflict("Profiles are busy; try again.")
    if operation == "request":
        body = payload(saved())
        monkeypatch.setattr(analysis, "request_analysis", busy)
        response = client.post("/api/meeting-analysis/requests", json=body)
    else:
        monkeypatch.setattr(manual_candidates, "list_candidates", busy)
        response = client.get("/api/meeting-analysis/candidates")
    assert response.status_code == 409
    assert response.json() == {"detail": "Profiles are busy; try again."}


def finish_stage(meeting_id, stage, *, status, artifact=None, stale_row=None):
    with meeting_db._cursor() as cur:
        cur.execute("SELECT * FROM meeting_digestions WHERE meeting_id=%s FOR UPDATE", (meeting_id,))
        row = dict(cur.fetchone())
        cur.execute(f"UPDATE meeting_digestions SET {stage}_status=%s,{stage}_attempts=3,{stage}_error=%s WHERE meeting_id=%s",
                    (status, "SyntheticFailure" if status == "failed" else None, meeting_id))
        if artifact is not None:
            cur.execute(f"UPDATE meeting_digestions SET {stage}_artifact=%s WHERE meeting_id=%s", (Json(artifact), meeting_id))
        manual_stage.finish(cur, stale_row or row, stage, status=status, artifact=artifact,
                            error_type="SyntheticFailure" if status == "failed" else None)


def test_manual_analysis_finish_and_resume_preserve_independent_stage_controls_and_frozen_target(source, target, saved, payload, jobs):
    meeting_id = saved(person=target)
    jobs()
    jobs("meeting_ingest")
    profile_request = analysis.request_analysis(payload(meeting_id, person=target))
    stale_profile_row = digestion_db.get_record(meeting_id)
    frozen_target = stale_profile_row["manual_analysis"]["profile"]["target"]
    memory_request = analysis.request_analysis(payload(meeting_id, scope="memories"))
    memory_control = digestion_db.get_record(meeting_id)["manual_analysis"]["memory"]
    artifact = {"version": 1, "offset": 1, "items": [], "profile_ids": [], "reason": "Saved checkpoint"}
    finish_stage(meeting_id, "profile", status="failed", artifact=artifact, stale_row=stale_profile_row)
    failed = digestion_db.get_record(meeting_id)
    assert failed["manual_analysis"]["profile"] == {"request_id": profile_request["request_id"], "active": False}
    assert failed["manual_analysis"]["memory"] == memory_control
    assert analysis.get_request(profile_request["request_id"])["status"] == "failed"
    assert analysis.get_request(memory_request["request_id"])["status"] == "queued"
    resumed = manual_stage.resume_request(profile_request["request_id"])
    current = digestion_db.get_record(meeting_id)
    assert resumed["status"] == "continued"
    assert current["profile_status"] == "pending" and current["profile_attempts"] == 0
    assert current["profile_artifact"] == artifact
    assert current["manual_analysis"]["profile"]["target"] == frozen_target
    assert current["manual_analysis"]["memory"] == memory_control
    assert current["memory_artifact"] == failed["memory_artifact"]
    assert current["memory_updated_at"] == failed["memory_updated_at"]
    assert analysis.get_request(memory_request["request_id"])["status"] == "queued"
    json.dumps(resumed)


def test_manual_analysis_both_scope_resume_keeps_completed_stage_and_saved_receipts(source, target, saved, payload, jobs):
    meeting_id = saved(person=target)
    jobs()
    jobs("meeting_ingest")
    request = analysis.request_analysis(payload(meeting_id, scope="both", person=target))
    memory_artifact = digestion_db.get_record(meeting_id)["memory_artifact"]
    finish_stage(meeting_id, "memory", status="done", artifact=memory_artifact)
    finish_stage(meeting_id, "profile", status="failed", artifact={"version": 1, "offset": 1, "items": [], "profile_ids": []})
    before = digestion_db.get_record(meeting_id)
    manual_stage.resume_request(request["request_id"])
    after = digestion_db.get_record(meeting_id)
    assert after["memory_status"] == "done" and after["memory_artifact"] == memory_artifact
    assert after["memory_updated_at"] == before["memory_updated_at"]
    assert after["manual_analysis"]["memory"] == before["manual_analysis"]["memory"]
    assert not after["manual_analysis"]["memory"]["active"]
    assert after["manual_analysis"]["profile"]["active"]
    receipt = analysis.get_request(request["request_id"])
    assert receipt["items"][0]["stages"]["memory"]["status"] == "done"
    assert receipt["items"][0]["stages"]["profile"]["status"] == "continued"
    json.dumps(receipt)


def test_manual_analysis_resume_rolls_back_all_selected_stages_if_a_later_meeting_changed(source, saved, payload, jobs):
    meeting_ids = sorted([saved(), saved()])
    jobs()
    request = analysis.request_analysis(payload(*meeting_ids))
    for meeting_id in meeting_ids:
        finish_stage(meeting_id, "profile", status="failed", artifact={"version": 1, "offset": 1, "items": [], "profile_ids": []})
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_summaries SET participants_revision=participants_revision+1 WHERE id=%s", (meeting_ids[-1],))
    before = {meeting_id: digestion_db.get_record(meeting_id) for meeting_id in meeting_ids}
    with pytest.raises(analysis.AnalysisConflict, match="changed after confirmation"):
        manual_stage.resume_request(request["request_id"])
    assert all(digestion_db.get_record(meeting_id) == before[meeting_id] for meeting_id in meeting_ids)
    assert analysis.get_request(request["request_id"])["status"] == "failed"


def test_manual_analysis_resume_accepts_live_profile_content_without_retargeting_identity(source, target, saved, payload, jobs):
    meeting_id = saved(person=target)
    jobs()
    request = analysis.request_analysis(payload(meeting_id, person=target))
    frozen = digestion_db.get_record(meeting_id)["manual_analysis"]["profile"]["target"]
    finish_stage(meeting_id, "profile", status="failed")
    updated = profile_db.update_metadata(target["id"], target["revision"], nicknames=["New human nickname"])
    assert updated["revision"] > target["revision"]
    assert manual_stage.resume_request(request["request_id"])["status"] in {"queued", "continued"}
    assert digestion_db.get_record(meeting_id)["manual_analysis"]["profile"]["target"] == frozen
    assert profile_db.get_profile(target["id"])["nicknames"] == ["New human nickname"]


@pytest.mark.parametrize("drift", ["source", "target", "replacement", "lease", "job"])
def test_manual_analysis_resume_revalidates_frozen_boundaries_without_mutating_checkpoints(source, target, saved, payload, jobs, drift):
    meeting_id = saved(person=target)
    job = jobs()
    request = analysis.request_analysis(payload(meeting_id, person=target))
    finish_stage(meeting_id, "profile", status="failed", artifact={"version": 1, "offset": 1, "items": [], "profile_ids": []})
    with get_connection() as conn, conn.cursor() as cur:
        if drift == "source":
            cur.execute("UPDATE meeting_summaries SET participants_revision=participants_revision+1 WHERE id=%s", (meeting_id,))
        elif drift == "target":
            cur.execute("UPDATE participant_profiles SET deleted=true WHERE id=%s", (target["id"],))
        elif drift == "replacement":
            cur.execute("UPDATE meeting_digestions SET manual_analysis=jsonb_set(manual_analysis,'{profile,request_id}',%s) WHERE meeting_id=%s",
                        (Json(str(uuid4())), meeting_id))
        elif drift == "lease":
            cur.execute("UPDATE meeting_digestions SET profile_claim_until=%s WHERE meeting_id=%s", (datetime.now(timezone.utc) + timedelta(minutes=5), meeting_id))
        else:
            cur.execute("UPDATE job_configs SET enabled=false WHERE job_id=%s", (job["id"],))
    before = digestion_db.get_record(meeting_id)
    with pytest.raises(analysis.AnalysisConflict):
        manual_stage.resume_request(request["request_id"])
    assert digestion_db.get_record(meeting_id) == before
    assert analysis.get_request(request["request_id"])["status"] == "failed"


def test_manual_analysis_resume_and_memory_completion_follow_one_lock_order(source, saved, payload, jobs, monkeypatch):
    meeting_id = saved()
    jobs("meeting_ingest")
    request = analysis.request_analysis(payload(meeting_id, scope="memories"))
    locked, resuming = threading.Event(), threading.Event()
    original = analysis._locked_meeting
    def observed_lock(cur, selected_id):
        resuming.set()
        return original(cur, selected_id)
    monkeypatch.setattr(analysis, "_locked_meeting", observed_lock)
    def complete():
        with meeting_db._cursor() as cur:
            cur.execute("SELECT * FROM meeting_digestions WHERE meeting_id=%s FOR UPDATE", (meeting_id,))
            row = dict(cur.fetchone())
            locked.set()
            assert resuming.wait(timeout=3)
            cur.execute("UPDATE meeting_digestions SET memory_status='done' WHERE meeting_id=%s", (meeting_id,))
            manual_stage.finish(cur, row, "memory", status="done", artifact=row["memory_artifact"])
    def resume():
        assert locked.wait(timeout=3)
        try:
            return manual_stage.resume_request(request["request_id"])
        except analysis.AnalysisConflict as error:
            return str(error)
    with ThreadPoolExecutor(max_workers=2) as pool:
        completed = pool.submit(complete)
        resumed = pool.submit(resume)
        completed.result(timeout=5)
        resumed.result(timeout=5)
    assert analysis.get_request(request["request_id"])["status"] == "done"
    row = digestion_db.get_record(meeting_id)
    assert row["memory_status"] == "done" and not row["manual_analysis"]["memory"]["active"]
