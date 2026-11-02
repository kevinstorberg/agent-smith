from __future__ import annotations

import copy
from datetime import datetime, timezone
from uuid import UUID

from psycopg2.extras import Json

STAGES = ("memory", "profile")
REASONS = ("memory_retry", "profile_retry", "transcript_retry", "participant_assignment",
           "process_meeting", "manual_analysis", "manual_resume")
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_MAX_TIMESTAMP = 253_402_300_799_999_999


def _stage(stage: str) -> str:
    if stage not in STAGES:
        raise ValueError("Work request stage must be memory or profile")
    return stage


def _controls(controls: dict) -> dict:
    if not isinstance(controls, dict) or not isinstance(controls.get("work_requests", {}), dict):
        raise ValueError("Meeting work requests require an object control map")
    return copy.deepcopy(controls)


def mark(controls: dict, stage: str, reason: str, *, requested_at: datetime) -> dict:
    stage = _stage(stage)
    if reason not in REASONS:
        raise ValueError("Unknown meeting work request reason")
    if not isinstance(requested_at, datetime) or requested_at.utcoffset() is None:
        raise ValueError("Work request time must include a timezone")
    delta = requested_at.astimezone(timezone.utc) - _EPOCH
    stamp = (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds
    if not 0 < stamp <= _MAX_TIMESTAMP:
        raise ValueError("Work request time must be within the supported UTC calendar")
    result = _controls(controls)
    result.setdefault("work_requests", {})[stage] = {"requested_at": stamp, "reason": reason}
    return result


def consume(controls: dict, stages: tuple[str, ...]) -> dict:
    result = _controls(controls)
    for stage in stages:
        result.get("work_requests", {}).pop(_stage(stage), None)
    if not result.get("work_requests"):
        result.pop("work_requests", None)
    return result


def _change(cur, meeting_id: str, transform) -> dict:
    key = str(UUID(str(meeting_id)))
    cur.execute("SELECT manual_analysis,clock_timestamp() AS now FROM meeting_digestions WHERE meeting_id=%s FOR UPDATE", (key,))
    row = cur.fetchone()
    if row is None:
        raise ValueError("Saved meeting processing state is unavailable")
    controls = transform(row["manual_analysis"], row["now"])
    if controls != row["manual_analysis"]:
        cur.execute("UPDATE meeting_digestions SET manual_analysis=%s WHERE meeting_id=%s", (Json(controls), key))
    return controls


def request(cur, meeting_id: str, stages: tuple[str, ...], reason: str) -> dict:
    def update(controls, now):
        for stage in stages:
            controls = mark(controls, stage, reason, requested_at=now)
        return controls
    return _change(cur, meeting_id, update)


def finish(cur, meeting_id: str, stages: tuple[str, ...]) -> dict:
    return _change(cur, meeting_id, lambda controls, _now: consume(controls, stages))


def requested_time_sql(stage: str | None, *, alias: str = "d") -> str:
    if stage is None:
        return "NULL::numeric"
    stage = _stage(stage)
    if alias != "d":
        raise ValueError("Meeting request SQL requires the digestion alias d")
    marker = f"({alias}.manual_analysis->'work_requests'->'{stage}')"
    stamp = f"({marker}->>'requested_at')"
    reasons = ",".join("'" + reason + "'" for reason in REASONS)
    valid = f"""CASE WHEN jsonb_typeof({marker})='object' THEN (
        {marker} ?& ARRAY['requested_at','reason']
        AND {marker}-'requested_at'-'reason'='{{}}'::jsonb
        AND jsonb_typeof({marker}->'requested_at')='number'
        AND {marker}->>'reason' IN ({reasons})
        AND CASE WHEN {stamp} ~ '^[0-9]{{1,18}}$'
            THEN {stamp}::numeric BETWEEN 1 AND {_MAX_TIMESTAMP} ELSE false END) ELSE false END"""
    control = f"({alias}.manual_analysis->'{stage}')"
    return f"""CASE WHEN ({valid}) THEN {stamp}::numeric
        WHEN {control}->'active'='true'::jsonb THEN (
            SELECT extract(epoch FROM request.created_at)*1000000
            FROM meeting_analysis_requests request
            WHERE request.request_id::text={control}->>'request_id'
              AND EXISTS (SELECT 1 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(request.result->'items')='array'
                    THEN request.result->'items' ELSE '[]'::jsonb END) entry
                WHERE entry->>'meeting_id'={alias}.meeting_id::text
                  AND entry->'stages'->'{stage}'->>'status' IN ('queued','continued','running')
                  AND entry->'stages'->'{stage}'->'source'={control}->'source'
                  AND coalesce(entry->'stages'->'{stage}'->'target','null'::jsonb)=coalesce({control}->'target','null'::jsonb)))
        ELSE NULL END"""
