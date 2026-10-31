from __future__ import annotations

from uuid import UUID

from services.meetings import stage_db, stage_state
from services.meetings.db import _cursor, _serialize


def get_processing(meeting_id: str) -> dict | None:
    key = str(UUID(meeting_id))
    with _cursor() as cur:
        cur.execute(f"""SELECT d.transcript_status,d.error_type,d.captured_at,
            CASE WHEN d.transcript_status='ready' THEN jsonb_array_length(d.transcript->'segments') ELSE 0 END AS total,
            d.speaker_status,d.speaker_error,d.memory_status,d.memory_error,d.profile_status,d.profile_error,
            d.speaker_next_attempt_at,d.memory_next_attempt_at,d.profile_next_attempt_at,
            d.memory_artifact->>'reason' AS memory_reason,d.profile_artifact->>'reason' AS profile_reason,
            coalesce(d.claim_until>clock_timestamp(),false) AS memory_running,
            coalesce(d.profile_claim_until>clock_timestamp(),false) AS persona_running,
            {stage_db.progress_sql('speaker')},{stage_db.progress_sql('memory')},{stage_db.progress_sql('profile')}
            FROM meeting_summaries m LEFT JOIN meeting_digestions d ON d.meeting_id=m.id
            WHERE m.id=%s AND m.available""", (key,))
        found = cur.fetchone()
    if found is None:
        return None
    row = dict(found)
    return _serialize({"transcript": stage_state.transcript(row), "speakers": stage_state.speakers(row),
                       "memories": stage_state.generation(row, "memory"), "profiles": stage_state.generation(row, "profile"),
                       "edit_lock_reason": stage_state.edit_lock(row)})
