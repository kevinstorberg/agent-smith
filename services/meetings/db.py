from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from services.db import get_connection
from services.meetings.config import SourceConfig
from services.meetings.types import MeetingSummary


class ClaimLostError(RuntimeError):
    pass


class MeetingStorageError(RuntimeError):
    pass


@contextmanager
def _cursor() -> Iterator[RealDictCursor]:
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET LOCAL TIME ZONE 'UTC'")
                cur.execute("SET LOCAL statement_timeout = '5s'")
                cur.execute("SET LOCAL lock_timeout = '1s'")
                yield cur
    except psycopg2.Error as error:
        # PostgreSQL diagnostics may echo parameters containing meeting context.
        raise MeetingStorageError(f"Meeting storage operation failed (SQLSTATE {error.pgcode or 'unknown'})") from None


def _identity(config: SourceConfig) -> tuple[str, str]:
    return config.provider, config.account_key


def _owned_state(cur: RealDictCursor, config: SourceConfig, owner: str) -> dict:
    cur.execute(
        """SELECT * FROM meeting_sync_state
           WHERE provider = %s AND account_key = %s FOR UPDATE""",
        _identity(config),
    )
    state = cur.fetchone()
    cur.execute("SELECT clock_timestamp() AS now")
    now = cur.fetchone()["now"]
    if (state is None or state["claim_owner"] != owner
            or state["claim_until"] is None or state["claim_until"] <= now
            or state["config_fingerprint"] != config.fingerprint):
        raise ClaimLostError("Meeting source claim expired, changed, or belongs to another run")
    return state


def claim_source(config: SourceConfig, owner: str, lease_seconds: int = 300) -> dict | None:
    if not isinstance(owner, str) or not owner.strip() or len(owner) > 100:
        raise ValueError("Meeting claim owner must be a nonblank string of at most 100 characters")
    if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
        raise ValueError("Meeting claim lease_seconds must be between 1 and 3600")
    with _cursor() as cur:
        cur.execute(
            """INSERT INTO meeting_sync_state
               (provider, account_key, source_name, config_fingerprint, claim_owner, claim_until, outcome)
               VALUES (%s, %s, %s, %s, %s, clock_timestamp() + %s * interval '1 second', 'claimed')
               ON CONFLICT (provider, account_key) DO UPDATE SET
                 source_name = EXCLUDED.source_name,
                 config_fingerprint = EXCLUDED.config_fingerprint,
                 scan = CASE WHEN meeting_sync_state.config_fingerprint <> EXCLUDED.config_fingerprint
                             THEN '{}'::jsonb ELSE meeting_sync_state.scan END,
                 last_pull_started_at = CASE
                     WHEN meeting_sync_state.config_fingerprint <> EXCLUDED.config_fingerprint
                     THEN NULL ELSE meeting_sync_state.last_pull_started_at END,
                 claim_owner = EXCLUDED.claim_owner, claim_until = EXCLUDED.claim_until,
                 outcome = 'claimed', last_error = NULL, updated_at = clock_timestamp()
               WHERE meeting_sync_state.claim_until IS NULL
                  OR meeting_sync_state.claim_until <= clock_timestamp()
               RETURNING *""",
            (*_identity(config), config.name, config.fingerprint, owner, lease_seconds),
        )
        row = cur.fetchone()
        if row is not None:
            cur.execute(
                """UPDATE meeting_summaries SET source_name = %s
                   WHERE provider = %s AND account_key = %s AND source_name <> %s""",
                (config.name, *_identity(config), config.name),
            )
        return dict(row) if row else None


def _validate_scan(scan: dict) -> None:
    if not isinstance(scan, dict):
        raise ValueError("Meeting scan checkpoint must be an object")
    if len(json.dumps(scan).encode()) > 2_000_000:
        raise ValueError("Meeting scan checkpoint exceeds 2000000 bytes")


def _save_scan(cur: RealDictCursor, config: SourceConfig, scan: dict) -> None:
    cur.execute(
        """UPDATE meeting_sync_state SET scan = %s, updated_at = clock_timestamp()
           WHERE provider = %s AND account_key = %s""",
        (Json(scan), *_identity(config)),
    )


def _stored_summary(cur: RealDictCursor, config: SourceConfig, external_id: str) -> dict | None:
    cur.execute(
        "SELECT * FROM meeting_summaries WHERE provider = %s AND account_key = %s AND external_id = %s",
        (*_identity(config), external_id),
    )
    return cur.fetchone()


def _mark_seen(cur: RealDictCursor, config: SourceConfig, external_id: str, scan: dict) -> None:
    cur.execute(
        """UPDATE meeting_summaries SET last_seen_at = clock_timestamp(), last_seen_scan_id = %s
           WHERE provider = %s AND account_key = %s AND external_id = %s""",
        (scan.get("id"), *_identity(config), external_id),
    )


def save_progress(
    config: SourceConfig, owner: str, scan: dict,
    summary: MeetingSummary | None = None, unavailable_id: str | None = None,
    seen_id: str | None = None, deleted_at: datetime | None = None,
    observed_updated_at: datetime | None = None,
) -> dict | None:
    _validate_scan(scan)
    if sum(value is not None for value in (summary, unavailable_id, seen_id)) > 1:
        raise ValueError("Save one meeting observation per checkpoint")
    if deleted_at is not None:
        if (unavailable_id is None or not isinstance(deleted_at, datetime) or deleted_at.utcoffset() is None
                or not isinstance(observed_updated_at, datetime) or observed_updated_at.utcoffset() is None):
            raise ValueError("Meeting deletion requires unavailable_id and timezone-aware deleted_at/observed_updated_at")
    with _cursor() as cur:
        _owned_state(cur, config, owner)
        result = None
        if summary is not None:
            result = _save_summary(cur, config, scan, summary)
        elif unavailable_id is not None and deleted_at is not None:
            result = _save_tombstone(cur, config, scan, unavailable_id, deleted_at, observed_updated_at)
        elif unavailable_id is not None:
            cur.execute(
                """UPDATE meeting_summaries SET missing_count = missing_count + 1,
                   available = CASE WHEN missing_count >= 2 THEN false ELSE available END,
                   revision = revision + CASE WHEN missing_count >= 2 AND available THEN 1 ELSE 0 END,
                   updated_at = CASE WHEN missing_count >= 2 AND available THEN clock_timestamp() ELSE updated_at END,
                   last_seen_scan_id = %s, last_seen_at = clock_timestamp()
                   WHERE provider = %s AND account_key = %s AND external_id = %s
                   RETURNING id, revision, available""",
                (scan.get("id"), *_identity(config), unavailable_id),
            )
            row = cur.fetchone()
            if row:
                result = {"id": str(row["id"]), "revision": row["revision"], "status": "unavailable" if not row["available"] else "pending"}
        elif seen_id is not None:
            _mark_seen(cur, config, seen_id, scan)
        _save_scan(cur, config, scan)
        return result


def _save_tombstone(
    cur: RealDictCursor, config: SourceConfig, scan: dict, external_id: str,
    deleted_at: datetime, observed_updated_at: datetime,
) -> dict | None:
    old = _stored_summary(cur, config, external_id)
    if old is None:
        return None
    if observed_updated_at < old["provider_updated_at"]:
        _mark_seen(cur, config, external_id, scan)
        return {"id": str(old["id"]), "revision": old["revision"], "status": "stale"}
    deleted_at = deleted_at.astimezone(timezone.utc)
    snapshot = MeetingSummary(
        old["external_id"], old["title"], old["summary_text"], old["summary_markdown"],
        old["source_url"], old["provider_created_at"], observed_updated_at,
        deleted_at, old["metadata"],
    )
    content_hash = snapshot.payload_hash(old["project"])
    changed = old["available"] or old["content_hash"] != content_hash
    revision = old["revision"] + int(changed)
    cur.execute(
        """UPDATE meeting_summaries SET available = false, provider_deleted_at = %s,
           provider_updated_at = GREATEST(provider_updated_at, %s), content_hash = %s,
           revision = %s, missing_count = missing_count + 1,
           last_seen_scan_id = %s, last_seen_at = clock_timestamp(),
           updated_at = CASE WHEN %s THEN clock_timestamp() ELSE updated_at END
           WHERE id = %s""",
        (deleted_at, observed_updated_at, content_hash, revision, scan.get("id"), changed, old["id"]),
    )
    return {"id": str(old["id"]), "revision": revision, "status": "unavailable"}


def _save_summary(cur: RealDictCursor, config: SourceConfig, scan: dict, summary: MeetingSummary) -> dict:
    if not summary.external_id or not summary.summary_text.strip():
        raise ValueError("Meeting summary requires an external_id and nonblank summary_text")
    for field in ("provider_created_at", "provider_updated_at", "provider_deleted_at"):
        value = getattr(summary, field)
        if value is not None and (not isinstance(value, datetime) or value.utcoffset() is None):
            raise ValueError(f"Meeting summary {field} must include a timezone")
    old = _stored_summary(cur, config, summary.external_id)
    if old and summary.provider_updated_at < old["provider_updated_at"]:
        _mark_seen(cur, config, summary.external_id, scan)
        return {"id": str(old["id"]), "revision": old["revision"], "status": "stale"}
    content_hash = summary.payload_hash(config.project)
    available = summary.provider_deleted_at is None
    changed = old is None or content_hash != old["content_hash"] or available != old["available"]
    summary_id = str(old["id"]) if old else str(uuid.uuid4())
    revision = (old["revision"] + int(changed)) if old else 1
    calendar = summary.metadata.get("calendar_event") or {}
    meeting_start = _optional_date(calendar.get("scheduled_start_time"), "meeting_start")
    meeting_end = _optional_date(calendar.get("scheduled_end_time"), "meeting_end")
    cur.execute(
        """INSERT INTO meeting_summaries
           (id, provider, account_key, external_id, source_name, project, title,
            summary_text, summary_markdown, source_url, metadata, provider_created_at,
            provider_updated_at, provider_deleted_at, meeting_start, meeting_end,
            content_hash, revision, available, last_seen_scan_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (provider, account_key, external_id) DO UPDATE SET
             source_name = EXCLUDED.source_name, project = EXCLUDED.project, title = EXCLUDED.title,
             summary_text = EXCLUDED.summary_text, summary_markdown = EXCLUDED.summary_markdown,
             source_url = EXCLUDED.source_url, metadata = EXCLUDED.metadata,
             provider_created_at = EXCLUDED.provider_created_at, provider_updated_at = EXCLUDED.provider_updated_at,
             provider_deleted_at = EXCLUDED.provider_deleted_at, meeting_start = EXCLUDED.meeting_start,
             meeting_end = EXCLUDED.meeting_end, content_hash = EXCLUDED.content_hash,
             revision = EXCLUDED.revision, available = EXCLUDED.available, missing_count = 0,
             last_seen_scan_id = EXCLUDED.last_seen_scan_id, last_seen_at = clock_timestamp(),
             updated_at = CASE WHEN meeting_summaries.revision <> EXCLUDED.revision
                               THEN clock_timestamp() ELSE meeting_summaries.updated_at END""",
        (summary_id, *_identity(config), summary.external_id, config.name, config.project,
         summary.title, summary.summary_text, summary.summary_markdown, summary.source_url,
         Json(summary.metadata), summary.provider_created_at, summary.provider_updated_at,
         summary.provider_deleted_at, meeting_start, meeting_end, content_hash, revision, available, scan.get("id")),
    )
    status = "created" if old is None else "updated" if changed else "unchanged"
    if status == "created":
        from services.meetings.digestion_db import enroll

        enroll(cur, summary_id)
    return {"id": summary_id, "revision": revision, "status": status}


def finish_scan(config: SourceConfig, owner: str, scan: dict) -> None:
    _validate_scan(scan)
    started = _optional_date(scan.get("started_at"), "scan.started_at")
    if started is None or scan.get("phase") != "done":
        raise ValueError("Only a completed meeting scan with started_at can advance the pull boundary")
    with _cursor() as cur:
        _owned_state(cur, config, owner)
        cur.execute(
            """UPDATE meeting_sync_state SET scan = '{}'::jsonb,
               last_completed_at = clock_timestamp(),
               last_pull_started_at = GREATEST(last_pull_started_at, %s),
               updated_at = clock_timestamp()
               WHERE provider = %s AND account_key = %s""",
            (started, *_identity(config)),
        )


def release_source(config: SourceConfig, owner: str, outcome: str, error: str | None = None) -> None:
    if outcome not in {"completed", "completed_with_warnings", "continued", "failed", "interrupted"}:
        raise ValueError("Unknown meeting sync outcome")
    # Persist an error category, never an exception body that may contain remote data.
    safe_error = "Meeting synchronization failed; inspect redacted execution diagnostics" if error else None
    with _cursor() as cur:
        cur.execute(
            """UPDATE meeting_sync_state SET claim_owner = NULL, claim_until = NULL,
               outcome = %s, last_error = %s, updated_at = clock_timestamp()
               WHERE provider = %s AND account_key = %s AND claim_owner = %s
                 AND config_fingerprint = %s""",
            (outcome, safe_error, *_identity(config), owner, config.fingerprint),
        )


def get_stored_refs(config: SourceConfig) -> dict:
    with _cursor() as cur:
        cur.execute(
            """SELECT external_id, provider_updated_at, project, available, missing_count, last_seen_scan_id
               FROM meeting_summaries WHERE provider = %s AND account_key = %s""",
            _identity(config),
        )
        return {row["external_id"]: {key: value for key, value in row.items() if key != "external_id"} for row in cur.fetchall()}


def _optional_date(value: str | None, field: str) -> datetime | None:
    if value is None:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        raise ValueError(f"Meeting {field} must be an ISO 8601 timestamp") from None
    if result.utcoffset() is None:
        raise ValueError(f"Meeting {field} must include a timezone")
    return result


def _serialize(row: dict) -> dict:
    result = dict(row)
    for key, value in result.items():
        if isinstance(value, datetime):
            result[key] = value.isoformat()
        elif isinstance(value, uuid.UUID):
            result[key] = str(value)
    return result


def list_summaries(
    source: str | None = None, project: str | None = None, query: str | None = None,
    after: str | None = None, before: str | None = None, limit: int = 20, offset: int = 0,
) -> dict:
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        raise ValueError("Meeting limit must be 1-100 and offset must be nonnegative")
    clauses, params = ["available = true"], []
    for field, value in (("source_name", source), ("project", project)):
        if value is not None:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Meeting {field} filter must be nonblank")
            clauses.append(f"{field} = %s")
            params.append(value)
    if query is not None:
        if not isinstance(query, str) or not query.strip() or len(query) > 1000:
            raise ValueError("Meeting query must be nonblank and at most 1000 characters")
        clauses.append("(title ILIKE %s OR summary_text ILIKE %s)")
        params.extend([f"%{query}%"] * 2)
    start, end = _optional_date(after, "after"), _optional_date(before, "before")
    if start and end and start > end:
        raise ValueError("Meeting after must not be later than before")
    for operator, stamp in ((">=", start), ("<=", end)):
        if stamp is not None:
            clauses.append(f"COALESCE(meeting_start, provider_created_at) {operator} %s")
            params.append(stamp)
    where = " AND ".join(clauses)
    with _cursor() as cur:
        cur.execute(f"SELECT count(*) AS count FROM meeting_summaries WHERE {where}", params)
        total = cur.fetchone()["count"]
        cur.execute(
            f"""SELECT * FROM meeting_summaries WHERE {where}
                ORDER BY COALESCE(meeting_start, provider_created_at) DESC, id LIMIT %s OFFSET %s""",
            (*params, limit, offset),
        )
        return {"items": [_serialize(row) for row in cur.fetchall()], "total": total}


def get_summary(summary_id: str, include_unavailable: bool = False) -> dict | None:
    try:
        normalized = str(uuid.UUID(summary_id))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Meeting summary_id must be a UUID") from None
    with _cursor() as cur:
        cur.execute("SELECT * FROM meeting_summaries WHERE id = %s AND (available OR %s)", (normalized, include_unavailable))
        row = cur.fetchone()
        return _serialize(row) if row else None


def source_status(source: str | None = None) -> list[dict]:
    with _cursor() as cur:
        cur.execute(
            """SELECT provider, account_key, source_name, outcome, last_error,
               claim_until, last_completed_at, last_deep_completed_at, last_pull_started_at, updated_at,
               scan->>'started_at' AS scan_started_at,
               scan->'deep' AS scan_deep, scan->'counts' AS counts
               FROM meeting_sync_state WHERE (%s IS NULL OR source_name = %s)
               ORDER BY source_name""",
            (source, source),
        )
        results = []
        allowed_counts = {"listed", "fetched", "processed", "created", "updated", "unchanged", "stale", "pending", "unavailable", "failed"}
        for row in cur.fetchall():
            counts = row.get("counts") or {}
            row["counts"] = {
                key: value for key, value in counts.items()
                if key in allowed_counts and type(value) is int and value >= 0
            } if isinstance(counts, dict) else {}
            started = _optional_date(row["scan_started_at"], "scan_started_at")
            age = max(0, (datetime.now(timezone.utc) - started).total_seconds()) if started else None
            row["scan_age_seconds"] = int(age) if age is not None else None
            row["degraded"] = age is not None and age > 86400
            results.append(_serialize(row))
        return results
