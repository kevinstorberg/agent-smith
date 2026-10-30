from __future__ import annotations

from uuid import UUID

from services.meetings import profile_db, stage_db
from services.meetings.db import _cursor, _optional_date, _serialize
from services.meetings.manual_analysis import (AnalysisNotFound, blocked_reason, covering_job, expected_values,
                                                target_has_segments, worker_jobs)


def list_candidates(*, profile_id: str | None = None, related: bool = True, query: str | None = None,
                    search_transcript: bool = False, source: str | None = None, after: str | None = None,
                    before: str | None = None, meeting_id: str | None = None, limit: int = 10, offset: int = 0) -> dict:
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        raise ValueError("Candidate limit must be 1-100 and offset must be nonnegative")
    if type(related) is not bool or type(search_transcript) is not bool:
        raise ValueError("Candidate related and search_transcript must be booleans")
    if query is not None and (not isinstance(query, str) or not query.strip() or len(query) > 1000):
        raise ValueError("Candidate search must be nonblank and at most 1000 characters")
    if search_transcript and not query:
        raise ValueError("Enter search text before searching saved transcripts")
    if source is not None and (not isinstance(source, str) or not source.strip() or len(source) > 100):
        raise ValueError("Candidate source must be a nonblank name of at most 100 characters")
    start, end = _optional_date(after, "after"), _optional_date(before, "before")
    if start and end and start > end:
        raise ValueError("Candidate after must not be later than before")
    jobs = worker_jobs()
    with _cursor() as cur:
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        profile = None
        ids, emails, names = [], [], []
        if profile_id:
            profile = profile_db._canonical(cur, str(UUID(profile_id)))
            if not profile or profile["deleted"]:
                raise AnalysisNotFound("Profile is no longer available")
            ids = profile_db.canonical_identity_ids(cur, str(profile["id"]))
            cur.execute("SELECT email,display_name,nicknames FROM participant_profiles WHERE id::text=ANY(%s)", (ids,))
            identities = cur.fetchall()
            emails = sorted({row["email"].strip().casefold() for row in identities if row["email"]})
            names = sorted({value.strip().casefold() for row in identities
                            for value in (row["display_name"], *row["nicknames"]) if value.strip()})
        person_match = "(person->>'profile_id'=ANY(%s) OR lower(btrim(person->>'email'))=ANY(%s))"
        reasons = f"""array_remove(ARRAY[
            CASE WHEN EXISTS(SELECT 1 FROM jsonb_array_elements(m.manual_participants) person WHERE {person_match}) THEN 'participant_assignment' END,
            CASE WHEN EXISTS(SELECT 1 FROM jsonb_array_elements(coalesce(d.speaker_artifact->'assignments','[]'::jsonb)) person WHERE {person_match}) THEN 'identified_speaker' END,
            CASE WHEN EXISTS(SELECT 1 FROM jsonb_array_elements(coalesce(d.transcript->'segments','[]'::jsonb)) segment,
                LATERAL (SELECT segment->'speaker' AS person) speaker WHERE {person_match}) THEN 'transcript_speaker' END,
            CASE WHEN EXISTS(SELECT 1 FROM jsonb_array_elements(coalesce(m.metadata->'attendees','[]'::jsonb)) person WHERE {person_match}) THEN 'attendee_email' END,
            CASE WHEN EXISTS(SELECT 1 FROM jsonb_array_elements(coalesce(m.metadata->'attendees','[]'::jsonb)) person
                WHERE lower(btrim(person->>'name'))=ANY(%s)) THEN 'attendee_name' END,
            CASE WHEN EXISTS(SELECT 1 FROM jsonb_array_elements(coalesce(d.transcript->'segments','[]'::jsonb)) segment
                WHERE lower(btrim(segment->'speaker'->>'name'))=ANY(%s)) THEN 'speaker_name' END
            ],NULL)"""
        params = [value for _ in range(4) for value in (ids, emails)] + [names, names]
        clauses = ["m.available"]
        if meeting_id:
            clauses.append("m.id=%s")
            params.append(str(UUID(meeting_id)))
        if source:
            clauses.append("m.source_name=%s")
            params.append(source)
        if query:
            pattern = "%" + query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            match = "(m.title ILIKE %s OR m.summary_text ILIKE %s"
            params.extend([pattern, pattern])
            if search_transcript:
                match += " OR EXISTS(SELECT 1 FROM jsonb_array_elements(coalesce(d.transcript->'segments','[]'::jsonb)) segment WHERE segment->>'text' ILIKE %s)"
                params.append(pattern)
            clauses.append(match + ")")
        for operator, value in ((">=", start), ("<=", end)):
            if value:
                clauses.append(f"coalesce(m.meeting_start,m.provider_created_at) {operator} %s")
                params.append(value)
        base = f"""WITH candidates AS (SELECT m.*,to_jsonb(d) AS digestion,{reasons} AS match_reasons
            FROM meeting_summaries m LEFT JOIN meeting_digestions d ON d.meeting_id=m.id WHERE {' AND '.join(clauses)})"""
        where = "WHERE cardinality(match_reasons)>0" if profile and related else ""
        cur.execute(f"{base} SELECT count(*) AS total FROM candidates {where}", params)
        total = cur.fetchone()["total"]
        cur.execute(f"{base} SELECT * FROM candidates {where} ORDER BY coalesce(meeting_start,provider_created_at) DESC,id LIMIT %s OFFSET %s",
                    (*params, limit, offset))
        rows = [dict(row) for row in cur.fetchall()]
        items = []
        for meeting in rows:
            row = meeting.pop("digestion")
            ready = not profile or bool(row and row.get("transcript_status") == "ready"
                                        and target_has_segments(cur, meeting, row, str(profile["id"])))
            stages = {}
            for stage in ("profile", "memory"):
                reason = blocked_reason(row, stage, target_ready=ready)
                job = covering_job(jobs, meeting, stage)
                if not reason and not job:
                    reason = "Configure a normal graph job enabled on this device for this meeting connection."
                stages[stage] = {"status": (row or {}).get(stage + "_status", "not_imported"),
                    "can_reanalyze": reason is None, "blocked_reason": reason,
                    "progress": _serialize(stage_db.progress(row, stage)), "job_id": job["id"] if job else None,
                    "job_name": job["name"] if job else None}
            items.append(_serialize({key: meeting.get(key) for key in ("id", "title", "source_name", "meeting_start", "labels", "match_reasons")}
                | {"attribution_ready": ready, "expected": expected_values(meeting, row), "stages": stages}))
        return {"items": items, "total": total,
                "profile": {"id": str(profile["id"]), "revision": profile["revision"], "display_name": profile["display_name"]} if profile else None}
