from __future__ import annotations

import copy
from datetime import datetime, timezone
from uuid import UUID

from psycopg2.extras import Json

from services.meetings import profile_db, stage_db
from services.meetings.db import _cursor, _serialize
from services.meetings.manual_analysis_contracts import AnalysisRequest

STAGES = {"profiles": ("profile",), "memories": ("memory",), "both": ("profile", "memory")}
SOURCE_FIELDS = ("provider", "account_key", "source_name", "meeting_revision", "transcript_hash", "participants_revision", "speaker_updated_at")


class AnalysisConflict(profile_db.ProfileRevisionConflict):
    pass


class AnalysisNotFound(LookupError):
    pass


def expected_values(meeting: dict, row: dict | None) -> dict:
    row = row or {}
    return _serialize({**{key: meeting[key] for key in ("provider", "account_key", "source_name")},
        "meeting_revision": meeting["revision"], "transcript_hash": row.get("transcript_hash"),
        "participants_revision": meeting["participants_revision"],
        **{stage + "_updated_at": row.get(stage + "_updated_at") for stage in ("speaker", "profile", "memory")}})


def worker_jobs() -> list[dict]:
    from services.config import DEVICE_NAME
    from services.jobs.models.job import list_graph_jobs
    from services.jobs.scoping import job_runs_on_device

    return [job for kind in ("persona", "meeting_ingest") for job in list_graph_jobs(kind)
            if job_runs_on_device(job["id"], DEVICE_NAME)]


def covering_job(jobs: list[dict], meeting: dict, stage: str) -> dict | None:
    for job in jobs:
        params = job.get("input_params") or {}
        inputs = params.get("graph_inputs") or {}
        if inputs.get("source") not in (None, meeting["source_name"]):
            continue
        if stage == "profile" and params.get("graph_type") == "persona" and not inputs.get("profile_id"):
            return job
        if (stage == "memory" and params.get("graph_type") == "meeting_ingest"
                and inputs.get("digest", True) and not inputs.get("meeting_id")):
            from services.meetings.digestion import configured_sources

            try:
                configs = configured_sources(inputs.get("source"))
            except ValueError:
                continue
            if (meeting["provider"], meeting["account_key"]) in configs:
                return job
    return None


def target_has_segments(cur, meeting: dict, row: dict, target_id: str) -> bool:
    from services.meetings.digestion_db import _SNAPSHOT_FIELDS
    from services.meetings.participants_db import effective_speakers
    from services.meetings.speaker_db import context_snapshot

    row = {**row, "snapshot": {key: meeting[key] for key in _SNAPSHOT_FIELDS}}
    snapshot = context_snapshot(row, manual=meeting["manual_participants"])
    return any(person.get("profile_id") == target_id
               for person in effective_speakers(cur, snapshot, row.get("transcript", {}).get("segments", [])).values())


def blocked_reason(row: dict | None, stage: str, *, target_ready: bool = True) -> str | None:
    if not row or row.get("transcript_status") != "ready":
        return "A saved transcript is required. This action does not fetch or restore transcripts."
    if row.get("speaker_status") == "pending":
        return "Finish identifying transcript speakers before requesting analysis."
    if has_active_lease(row):
        return "Meeting analysis is already running."
    recover_changed_source = (row.get(stage + "_status") == "failed"
        and row.get(stage + "_error") == "ManualAnalysisInputChanged"
        and row.get("manual_analysis", {}).get(stage, {}).get("active") is False)
    if row.get(stage + "_status") != "done" and not recover_changed_source:
        return "Resume unfinished analysis to keep its saved progress."
    if stage == "profile" and not target_ready:
        return "Assign this profile to its transcript statements or speaker before requesting analysis."
    if stage == "memory":
        artifact = row.get("memory_artifact") or {}
        items, published = artifact.get("items"), artifact.get("published_ids")
        if (artifact.get("version") != 1 or not isinstance(items, list) or not isinstance(published, list)
                or any(not isinstance(item, dict) or not item.get("id") for item in items)
                or len({item["id"] for item in items}) != len(items)
                or set(published) != {item["id"] for item in items}):
            return "Resume unfinished memory publication before starting another analysis pass."
    return None


def _date(value: str | datetime) -> datetime:
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def has_active_lease(row: dict) -> bool:
    return any(row.get(key) and _date(row[key]) > datetime.now(timezone.utc) for key in ("claim_until", "profile_claim_until"))


def _locked_meeting(cur, meeting_id: str) -> tuple[dict, dict]:
    cur.execute("SELECT * FROM meeting_digestions WHERE meeting_id=%s FOR UPDATE", (meeting_id,))
    row = cur.fetchone()
    cur.execute("SELECT * FROM meeting_summaries WHERE id=%s AND available FOR UPDATE", (meeting_id,))
    meeting = cur.fetchone()
    if not meeting:
        raise AnalysisNotFound("Saved meeting is no longer available")
    if not row:
        raise AnalysisConflict("A saved transcript is required before analysis")
    return dict(meeting), dict(row)


def _target(cur, payload: dict) -> dict | None:
    requested = payload.get("target_profile")
    if not requested:
        return None
    row = profile_db._canonical(cur, requested["id"], lock=True)
    if not row or row["deleted"] or str(row["id"]) != requested["id"] or row["revision"] != requested["expected_revision"]:
        raise AnalysisConflict("Target profile changed; reload it before confirming analysis")
    return {"id": str(row["id"]), "identity_key": row["identity_key"]}


def request_analysis(request: AnalysisRequest | dict) -> dict:
    model = request if isinstance(request, AnalysisRequest) else AnalysisRequest.model_validate(request)
    payload = model.model_dump(mode="json")
    payload["meetings"].sort(key=lambda entry: entry["id"])
    jobs = worker_jobs()
    with profile_db.profile_write_cursor() as cur:
        cur.execute("SELECT * FROM meeting_analysis_requests WHERE request_id=%s FOR UPDATE", (payload["request_id"],))
        receipt = cur.fetchone()
        if receipt:
            if receipt["payload"] != payload:
                raise AnalysisConflict("This request ID was already used for a different selection")
            return _receipt(cur, dict(receipt), jobs)
        locked = {selection["id"]: _locked_meeting(cur, selection["id"]) for selection in payload["meetings"]}
        target = _target(cur, payload)
        entries = []
        for selection in payload["meetings"]:
            meeting, row = locked[selection["id"]]
            live = expected_values(meeting, row)
            for key in (*SOURCE_FIELDS, *(stage + "_updated_at" for stage in STAGES[payload["scope"]])):
                if selection["expected"][key] != live[key]:
                    raise AnalysisConflict(f"Meeting {key} changed; refresh the selection and confirm again")
            target_ready = not target or row["transcript_status"] == "ready" and target_has_segments(cur, meeting, row, target["id"])
            stages = {}
            for stage in STAGES[payload["scope"]]:
                reason = blocked_reason(row, stage, target_ready=target_ready)
                if reason:
                    raise AnalysisConflict(reason)
                control = row["manual_analysis"].get(stage, {})
                if control.get("active"):
                    raise AnalysisConflict("A manual analysis request is already queued for this meeting")
                job = covering_job(jobs, meeting, stage)
                if not job:
                    raise AnalysisConflict(f"Configure a normal {'Personas' if stage == 'profile' else 'Meetings'} graph job enabled on this device for {meeting['source_name']}.")
                stages[stage] = {"status": "queued", "source": {key: live[key] for key in SOURCE_FIELDS},
                    "job_id": job["id"], "job_name": job["name"], "error_type": None,
                    "target": target if stage == "profile" else None}
            entries.append({"meeting_id": selection["id"], "title": meeting["title"], "stages": stages})
        result = {"items": entries}
        cur.execute("INSERT INTO meeting_analysis_requests(request_id,payload,result) VALUES(%s,%s,%s) RETURNING *",
                    (payload["request_id"], Json(payload), Json(result)))
        receipt = dict(cur.fetchone())
        for entry in entries:
            _reopen(cur, payload["request_id"], entry)
        return _receipt(cur, receipt, jobs)


def _reopen(cur, request_id: str, entry: dict) -> None:
    for stage, state in entry["stages"].items():
        cur.execute("SELECT * FROM meeting_digestions WHERE meeting_id=%s", (entry["meeting_id"],))
        row = dict(cur.fetchone())
        artifact = copy.deepcopy(row[stage + "_artifact"])
        if stage == "profile":
            artifact = {}
        else:
            artifact["offset"] = 0
            artifact["manual_request_id"] = request_id
            for key in ("vocabulary", "attribution_snapshot", "attribution_identities", "context_labels_revision", "context_labels", "total_units"):
                artifact.pop(key, None)
        control = {**row["manual_analysis"], stage: {"request_id": request_id, "active": True,
                    "source": state["source"], "target": state["target"]}}
        cur.execute(f"""UPDATE meeting_digestions SET {stage}_status='pending', {stage}_artifact=%s,
            {stage}_attempts=0,{stage}_error=NULL,{stage}_next_attempt_at=clock_timestamp(),
            {stage}_updated_at=clock_timestamp(),requested_at=clock_timestamp(),manual_analysis=%s WHERE meeting_id=%s""",
                    (Json(artifact), Json(control), entry["meeting_id"]))


def get_request(request_id: str) -> dict | None:
    key = str(UUID(request_id))
    jobs = worker_jobs()
    with _cursor() as cur:
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        cur.execute("SELECT * FROM meeting_analysis_requests WHERE request_id=%s", (key,))
        receipt = cur.fetchone()
        return _receipt(cur, dict(receipt), jobs) if receipt else None


def _receipt(cur, receipt: dict, jobs: list[dict]) -> dict:
    items = []
    for entry in receipt["result"]["items"]:
        cur.execute("SELECT * FROM meeting_digestions WHERE meeting_id=%s", (entry["meeting_id"],))
        row = cur.fetchone()
        stages = {}
        for stage, saved in entry["stages"].items():
            public = {key: saved[key] for key in ("status", "error_type", "job_id", "job_name")}
            progress = saved.get("progress") if saved["status"] in {"done", "failed"} else None
            public["progress"] = progress or _serialize(stage_db.progress(dict(row) if row else {}, stage))
            if saved["status"] not in {"done", "failed"}:
                control = (row or {}).get("manual_analysis", {}).get(stage, {})
                if not row or control.get("request_id") != str(receipt["request_id"]) or not control.get("active"):
                    public.update(status="failed", error_type="ManualAnalysisSuperseded")
                else:
                    from services.meetings import manual_stage

                    lease = "profile_claim_until" if stage == "profile" else "claim_until"
                    running = row.get(lease) and _date(row[lease]) > datetime.now(timezone.utc)
                    public["status"] = "running" if running else "continued" if row[stage + "_attempts"] or public["progress"]["processed_units"] else "queued"
                    public["error_type"] = row[stage + "_error"]
                    job = covering_job(jobs, saved["source"], stage)
                    if job:
                        public.update(job_id=job["id"], job_name=job["name"])
                    else:
                        public["waiting_for"] = "job"
                    try:
                        manual_stage._source(cur, dict(row), saved, lock=False)
                    except manual_stage.ManualAnalysisInputChanged:
                        public.update(status="failed", error_type="ManualAnalysisInputChanged")
            stages[stage] = public
        items.append({"meeting_id": entry["meeting_id"], "title": entry["title"], "stages": stages})
    states = [stage["status"] for entry in items for stage in entry["stages"].values()]
    status = "failed" if all(state in {"done", "failed"} for state in states) and "failed" in states else (
        "done" if all(state == "done" for state in states) else "running" if "running" in states else "continued" if "continued" in states else "queued")
    return _serialize({"request_id": receipt["request_id"], "scope": receipt["payload"]["scope"],
        "target_profile_id": (receipt["payload"].get("target_profile") or {}).get("id"),
        "created_at": receipt["created_at"], "updated_at": receipt["updated_at"], "status": status, "items": items})
