from __future__ import annotations

from uuid import UUID

from services.meetings import stage_db, stage_state
from services.meetings.db import _cursor, _serialize


def _progress_sql(stage: str) -> str:
    stage = stage_state.stage_name(stage)
    artifact = f"d.{stage}_artifact"
    def count(name: str) -> str:
        return f"coalesce(jsonb_array_length({artifact}->'{name}'),0)"
    staged = count("draft_assignments") if stage == "speaker" else count("items") + (" + " + count("metadata_updates") if stage == "profile" else "")
    saved = f"(SELECT count(*) FROM jsonb_array_elements({artifact}->'assignments') entry WHERE entry->>'confidence'='high')" if stage == "speaker" else count("published_ids" if stage == "memory" else "profile_ids")
    fallback = "NULL" if stage == "speaker" else stage_db.TOTAL_UNITS_SQL
    return f"""jsonb_build_object('processed_units',coalesce(({artifact}->>'offset')::integer,0),
        'total_units',CASE WHEN {artifact} ? 'total_units' THEN ({artifact}->>'total_units')::integer ELSE {fallback} END,
        'staged_count',{staged},'saved_count',{saved},'attempts',coalesce(d.{stage}_attempts,0)) AS {stage}_progress"""


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
            {_progress_sql('speaker')},{_progress_sql('memory')},{_progress_sql('profile')}
            FROM meeting_summaries m LEFT JOIN meeting_digestions d ON d.meeting_id=m.id
            WHERE m.id=%s AND m.available""", (key,))
        found = cur.fetchone()
    if found is None:
        return None
    row = dict(found)
    return _serialize({"transcript": stage_state.transcript(row), "speakers": stage_state.speakers(row),
                       "memories": stage_state.generation(row, "memory"), "profiles": stage_state.generation(row, "profile"),
                       "edit_lock_reason": stage_state.edit_lock(row)})
