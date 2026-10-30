from __future__ import annotations

from psycopg2.extras import Json

from services.meetings import stage_db
from services.meetings.db import _cursor, _serialize
from services.meetings.manual_analysis import (AnalysisConflict, SOURCE_FIELDS, covering_job, expected_values, has_active_lease, worker_jobs)


class ManualAnalysisInputChanged(AnalysisConflict):
    pass


class ManualAnalysisJobUnavailable(RuntimeError):
    pass


def _receipt_stage(cur, row: dict, stage: str, request_id: str) -> tuple[dict, dict]:
    cur.execute("SELECT * FROM meeting_analysis_requests WHERE request_id=%s FOR UPDATE", (request_id,))
    receipt = cur.fetchone()
    if receipt:
        for entry in receipt["result"]["items"]:
            if entry["meeting_id"] == str(row["meeting_id"]) and stage in entry["stages"]:
                return dict(receipt), entry["stages"][stage]
    raise ManualAnalysisInputChanged("Manual analysis receipt is unavailable")


def _source(cur, row: dict, saved: dict, *, lock: bool = True) -> dict:
    cur.execute("SELECT * FROM meeting_summaries WHERE id=%s" + (" FOR SHARE" if lock else ""), (row["meeting_id"],))
    meeting = cur.fetchone()
    if not meeting or not meeting["available"] or row["transcript_status"] != "ready":
        raise ManualAnalysisInputChanged("Saved meeting transcript is no longer available")
    meeting = dict(meeting)
    live = expected_values(meeting, row)
    if any(live[key] != saved["source"][key] for key in SOURCE_FIELDS):
        raise ManualAnalysisInputChanged("Meeting source or speaker assignments changed after confirmation")
    target = saved.get("target")
    if target:
        cur.execute("SELECT id,identity_key,deleted,merged_into FROM participant_profiles WHERE id=%s", (target["id"],))
        person = cur.fetchone()
        if not person or person["deleted"] or person["merged_into"] or person["identity_key"] != target["identity_key"]:
            raise ManualAnalysisInputChanged("Target profile identity changed after confirmation")
    return meeting


def validate(cur, row: dict, stage: str) -> dict | None:
    control = row.get("manual_analysis", {}).get(stage)
    marker = row.get(stage + "_artifact", {}).get("manual_request_id")
    if marker and row.get(stage + "_status") == "pending" and (
            not control or not control.get("active") or control.get("request_id") != marker):
        raise ManualAnalysisInputChanged("Manual analysis scope was removed from its checkpoint")
    if not control or not control.get("active"):
        return None
    receipt, saved = _receipt_stage(cur, row, stage, control["request_id"])
    if (saved["status"] not in {"queued", "continued", "running"}
            or control.get("source") != saved["source"] or control.get("target") != saved.get("target")):
        raise ManualAnalysisInputChanged("Manual analysis control does not match its immutable receipt")
    _source(cur, row, saved)
    return control


def before_analysis(meeting_id: str, owner: str, transcript_hash: str, stage: str) -> dict | None:
    with _cursor() as cur:
        row = stage_db.pending(cur, meeting_id, owner, transcript_hash, stage)
        control = row.get("manual_analysis", {}).get(stage)
        if control and not control.get("active"):
            control = None
        if control and not covering_job(worker_jobs(), control["source"], stage):
            raise ManualAnalysisJobUnavailable("Configure an eligible normal graph job for the selected connection")
        return control


def protected_profile(row: dict) -> bool:
    marker = row.get("manual_analysis", {}).get("profile", {})
    return bool(marker and (marker.get("active") or row.get("profile_status") == "failed"))


def invalidate_source(cur, meeting_id: str) -> None:
    cur.execute("SELECT * FROM meeting_digestions WHERE meeting_id=%s FOR UPDATE", (meeting_id,))
    row = cur.fetchone()
    if not row:
        return
    marker = row.get("manual_analysis", {}).get("profile", {})
    if marker and not marker.get("active") and row["profile_status"] == "failed":
        cur.execute("UPDATE meeting_digestions SET profile_error='ManualAnalysisInputChanged',profile_updated_at=clock_timestamp() WHERE meeting_id=%s", (meeting_id,))
    for stage in ("profile", "memory"):
        if not row.get("manual_analysis", {}).get(stage, {}).get("active"):
            continue
        cur.execute(f"""UPDATE meeting_digestions SET {stage}_status='failed',{stage}_attempts=3,
            {stage}_error='ManualAnalysisInputChanged',{stage}_updated_at=clock_timestamp() WHERE meeting_id=%s""", (meeting_id,))
        finish(cur, dict(row), stage, status="failed", error_type="ManualAnalysisInputChanged")
        cur.execute("SELECT * FROM meeting_digestions WHERE meeting_id=%s", (meeting_id,))
        row = cur.fetchone()


def finish(cur, row: dict, stage: str, *, status: str, artifact: dict | None = None, error_type: str | None = None) -> None:
    cur.execute("SELECT * FROM meeting_digestions WHERE meeting_id=%s FOR UPDATE", (row["meeting_id"],))
    row = dict(cur.fetchone())
    control = row.get("manual_analysis", {}).get(stage)
    if not control or not control.get("active"):
        return
    receipt, saved = _receipt_stage(cur, row, stage, control["request_id"])
    progress_row = dict(row)
    if artifact is not None:
        progress_row[stage + "_artifact"] = artifact
    saved.update(status=status, error_type=error_type, progress=_serialize(stage_db.progress(progress_row, stage)))
    cur.execute("UPDATE meeting_analysis_requests SET result=%s,updated_at=clock_timestamp() WHERE request_id=%s",
                (Json(receipt["result"]), control["request_id"]))
    controls = {**row["manual_analysis"], stage: {"request_id": control["request_id"], "active": False}}
    cur.execute("UPDATE meeting_digestions SET manual_analysis=%s WHERE meeting_id=%s", (Json(controls), row["meeting_id"]))


def resume_stage(cur, row: dict, stage: str) -> bool:
    marker = row.get("manual_analysis", {}).get(stage)
    if not marker:
        return False
    if has_active_lease(row):
        raise AnalysisConflict("Analysis is already running")
    receipt, saved = _receipt_stage(cur, row, stage, marker["request_id"])
    if row[stage + "_status"] not in {"pending", "failed"} or saved["status"] == "done":
        raise AnalysisConflict("Completed manual analysis requires a new confirmed request")
    meeting = _source(cur, row, saved)
    if not covering_job(worker_jobs(), meeting, stage):
        raise AnalysisConflict("Configure an eligible normal graph job for the selected connection")
    controls = {**row["manual_analysis"], stage: {"request_id": marker["request_id"], "active": True,
        "source": saved["source"], "target": saved.get("target")}}
    saved.update(status="continued", error_type=None)
    cur.execute("UPDATE meeting_analysis_requests SET result=%s,updated_at=clock_timestamp() WHERE request_id=%s",
                (Json(receipt["result"]), marker["request_id"]))
    cur.execute(f"""UPDATE meeting_digestions SET {stage}_status='pending',
        {stage}_attempts=CASE WHEN {stage}_status='failed' THEN 0 ELSE {stage}_attempts END,
        {stage}_error=NULL,{stage}_next_attempt_at=clock_timestamp(),{stage}_updated_at=clock_timestamp(),
        requested_at=clock_timestamp(),manual_analysis=%s WHERE meeting_id=%s""", (Json(controls), row["meeting_id"]))
    return True


def resume_request(request_id: str) -> dict:
    from services.meetings import manual_analysis, profile_db

    with profile_db.profile_write_cursor() as cur:
        cur.execute("SELECT * FROM meeting_analysis_requests WHERE request_id=%s", (request_id,))
        receipt = cur.fetchone()
        if not receipt:
            raise manual_analysis.AnalysisNotFound("Manual analysis request was not found")
        rows = {entry["meeting_id"]: manual_analysis._locked_meeting(cur, entry["meeting_id"])[1]
                for entry in receipt["result"]["items"]}
        for entry in receipt["result"]["items"]:
            row = rows[entry["meeting_id"]]
            for stage, saved in entry["stages"].items():
                if saved["status"] == "done":
                    continue
                marker = row["manual_analysis"].get(stage, {})
                if marker.get("request_id") != request_id:
                    raise AnalysisConflict("A newer request replaced this analysis; refresh its progress")
                if has_active_lease(row):
                    raise AnalysisConflict("Analysis is already running")
                resume_stage(cur, row, stage)
                cur.execute("SELECT * FROM meeting_digestions WHERE meeting_id=%s", (entry["meeting_id"],))
                row = dict(cur.fetchone())
    return manual_analysis.get_request(request_id)
