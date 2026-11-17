from __future__ import annotations

from uuid import UUID

from psycopg2.extras import Json

from services.action_items import db as tasks
from services.meetings import db, management_db, stage_db
from services.proposals.action_item_contracts import (
    ActionItemContextTooLarge,
    MAX_CONTEXT_ITEMS,
)

_ELIGIBLE = """m.available AND r.source_revision=m.revision AND r.source_hash=m.content_hash
    AND r.action_items_status='pending' AND r.action_items_next_attempt_at<=clock_timestamp()
    AND (r.claim_until IS NULL OR r.claim_until<=clock_timestamp())"""


class NoWorkerError(RuntimeError):
    pass


def enroll(
    cur, meeting_id: str, revision: int, content_hash: str, *, create: bool
) -> None:
    if create:
        cur.execute(
            """INSERT INTO meeting_action_item_runs(meeting_id,source_revision,source_hash)
            VALUES(%s,%s,%s) ON CONFLICT DO NOTHING""",
            (meeting_id, revision, content_hash),
        )
    else:
        cur.execute(
            """UPDATE meeting_action_item_runs SET source_revision=%s,source_hash=%s,
            action_items_status='pending',action_items_artifact='{}'::jsonb,action_items_attempts=0,
            action_items_error=NULL,action_items_next_attempt_at=clock_timestamp(),
            claim_owner=NULL,claim_until=NULL,updated_at=clock_timestamp()
            WHERE meeting_id=%s AND (source_revision<>%s OR source_hash<>%s)""",
            (revision, content_hash, meeting_id, revision, content_hash),
        )


def _record(cur, meeting_id: str) -> dict | None:
    cur.execute(
        """SELECT r.*,row_to_json(m) AS snapshot,
        coalesce(r.claim_until>clock_timestamp(),false) AS running
        FROM meeting_action_item_runs r JOIN meeting_summaries m ON m.id=r.meeting_id
        WHERE r.meeting_id=%s""",
        (meeting_id,),
    )
    row = cur.fetchone()
    return db._serialize(dict(row)) if row else None


def get_record(meeting_id: str) -> dict | None:
    with db._cursor() as cur:
        return _record(cur, str(UUID(meeting_id)))


def claim(identities: list[tuple[str, str]], owner: str) -> dict | None:
    if not identities:
        return None
    if not isinstance(owner, str) or not owner.strip() or len(owner) > 100:
        raise ValueError(
            "Action Item analysis requires a nonblank lease owner of at most 100 characters"
        )
    with db._cursor() as cur:
        cur.execute(
            f"""SELECT r.meeting_id FROM meeting_action_item_runs r
            JOIN meeting_summaries m ON m.id=r.meeting_id WHERE {_ELIGIBLE}
            AND (m.provider,m.account_key) IN %s
            ORDER BY r.created_at,r.meeting_id LIMIT 1 FOR UPDATE OF r SKIP LOCKED""",
            (tuple(identities),),
        )
        row = cur.fetchone()
        if row is None:
            return None
        cur.execute(
            """UPDATE meeting_action_item_runs SET claim_owner=%s,
            claim_until=clock_timestamp()+interval '10 minutes',updated_at=clock_timestamp()
            WHERE meeting_id=%s""",
            (owner, row["meeting_id"]),
        )
        return _record(cur, str(row["meeting_id"]))


def has_work(identities: list[tuple[str, str]]) -> bool:
    if not identities:
        return False
    with db._cursor() as cur:
        cur.execute(
            f"""SELECT EXISTS(SELECT 1 FROM meeting_action_item_runs r
            JOIN meeting_summaries m ON m.id=r.meeting_id WHERE {_ELIGIBLE}
            AND (m.provider,m.account_key) IN %s) AS found""",
            (tuple(identities),),
        )
        return cur.fetchone()["found"]


def release_owner(owner: str) -> None:
    with db._cursor() as cur:
        cur.execute(
            "UPDATE meeting_action_item_runs SET claim_owner=NULL,claim_until=NULL WHERE claim_owner=%s",
            (owner,),
        )


def _owned(cur, meeting_id: str, owner: str) -> dict:
    cur.execute("SELECT * FROM meeting_summaries WHERE id=%s FOR SHARE", (meeting_id,))
    source = cur.fetchone()
    cur.execute(
        "SELECT *,claim_until>clock_timestamp() AS running FROM meeting_action_item_runs WHERE meeting_id=%s FOR UPDATE",
        (meeting_id,),
    )
    row = cur.fetchone()
    if (
        not source
        or not source["available"]
        or not row
        or row["claim_owner"] != owner
        or not row["running"]
        or row["action_items_status"] != "pending"
        or row["source_revision"] != source["revision"]
        or row["source_hash"] != source["content_hash"]
    ):
        raise db.ClaimLostError("Action Item analysis lease or source changed")
    return dict(row)


def assert_current(meeting_id: str, owner: str) -> None:
    with db._cursor() as cur:
        _owned(cur, meeting_id, owner)


def save_progress(
    meeting_id: str, owner: str, artifact: dict, *, complete: bool = False
) -> None:
    stage_db.validate_artifact(artifact)
    with db._cursor() as cur:
        _owned(cur, meeting_id, owner)
        cur.execute(
            """UPDATE meeting_action_item_runs SET action_items_artifact=%s,action_items_status=%s,
            action_items_error=NULL,updated_at=clock_timestamp() WHERE meeting_id=%s""",
            (Json(artifact), "done" if complete else "pending", meeting_id),
        )


def record_failure(meeting_id: str, owner: str, error_type: str) -> None:
    if (
        not isinstance(error_type, str)
        or not error_type
        or not error_type.replace("_", "").isalnum()
        or len(error_type) > 100
    ):
        raise ValueError("Action Item failure must be a safe error category")
    with db._cursor() as cur:
        row = _owned(cur, meeting_id, owner)
        attempts = row["action_items_attempts"] + 1
        cur.execute(
            """UPDATE meeting_action_item_runs SET action_items_status=%s,action_items_attempts=%s,
            action_items_error=%s,action_items_next_attempt_at=clock_timestamp()+%s*interval '1 second',
            updated_at=clock_timestamp() WHERE meeting_id=%s""",
            (
                "failed" if attempts >= stage_db.MAX_STAGE_ATTEMPTS else "pending",
                attempts,
                error_type,
                stage_db.retry_delay(attempts),
                meeting_id,
            ),
        )


def inventory() -> tuple[list[dict], list[str]]:
    with tasks._cursor(None, write=False) as (cur, scope):
        cur.execute(
            f"""SELECT {scope.columns(detail=True)} FROM {tasks._PROJECT_ROWS}
            WHERE a.scope_key='global' AND a.deleted_at IS NULL ORDER BY a.id LIMIT %s""",
            (MAX_CONTEXT_ITEMS + 1,),
        )
        rows = [tasks._record(row) for row in cur.fetchall()]
        if len(rows) > MAX_CONTEXT_ITEMS:
            raise ActionItemContextTooLarge(
                "The complete task inventory exceeds 200 items; no partial matching was attempted"
            )
        cur.execute("SELECT name FROM action_item_projects ORDER BY name")
        return rows, [row["name"] for row in cur.fetchall()]


def proposal_ids(snapshot: dict) -> list[int]:
    with db._cursor() as cur:
        cur.execute(
            """SELECT proposal_id FROM action_item_proposal_payloads WHERE meeting_id=%s
            AND source_revision=%s AND source_hash=%s ORDER BY proposal_id""",
            (snapshot["id"], snapshot["revision"], snapshot["content_hash"]),
        )
        return [row["proposal_id"] for row in cur.fetchall()]


def has_worker(meeting: dict) -> bool:
    from services.meetings.manual_analysis import covering_job, worker_jobs

    return covering_job(worker_jobs(), meeting, "memory") is not None


def request(meeting_id: str, expected_revision: int) -> dict:
    key = str(UUID(meeting_id))
    if type(expected_revision) is not int or expected_revision <= 0:
        raise ValueError("Meeting revision must be a positive integer")
    meeting = db.get_summary(key)
    if not meeting:
        raise management_db.MeetingNotFoundError("Meeting summary is unavailable")
    if not has_worker(meeting):
        raise NoWorkerError(
            "Enable a Meetings graph job for this connection before generating proposals"
        )
    with db._cursor() as cur:
        cur.execute(
            "SELECT * FROM meeting_summaries WHERE id=%s AND available FOR SHARE",
            (key,),
        )
        source = cur.fetchone()
        if source is None:
            raise management_db.MeetingNotFoundError("Meeting summary is unavailable")
        if source["revision"] != expected_revision:
            raise management_db.MeetingManagementConflict(
                "Meeting changed; refresh before generating proposals"
            )
        cur.execute(
            """INSERT INTO meeting_action_item_runs(meeting_id,source_revision,source_hash) VALUES(%s,%s,%s)
            ON CONFLICT(meeting_id) DO UPDATE SET source_revision=EXCLUDED.source_revision,source_hash=EXCLUDED.source_hash,
            action_items_status='pending',action_items_artifact='{}'::jsonb,action_items_attempts=0,
            action_items_error=NULL,action_items_next_attempt_at=clock_timestamp(),claim_owner=NULL,claim_until=NULL,
            updated_at=clock_timestamp() WHERE meeting_action_item_runs.claim_until IS NULL
            OR meeting_action_item_runs.claim_until<=clock_timestamp() RETURNING meeting_id""",
            (key, source["revision"], source["content_hash"]),
        )
        if cur.fetchone() is None:
            raise management_db.MeetingManagementConflict(
                "Action Item proposals are already being generated"
            )
    return status(key, worker_available=True)


def status(meeting_id: str, *, worker_available: bool | None = None) -> dict:
    record = get_record(meeting_id)
    meeting = record["snapshot"] if record else db.get_summary(meeting_id)
    if meeting is None:
        raise management_db.MeetingNotFoundError("Meeting summary is unavailable")
    if worker_available is None:
        worker_available = has_worker(meeting)
    artifact = (record or {}).get("action_items_artifact") or {}
    state = (
        "running"
        if record and record["running"]
        else (record or {}).get("action_items_status", "not_queued")
    )
    return {
        "status": state,
        "worker_available": worker_available,
        "proposal_count": len(proposal_ids(meeting)),
        "attempts": (record or {}).get("action_items_attempts", 0),
        "error_type": (record or {}).get("action_items_error"),
        "reason": artifact.get("reason"),
        "next_attempt_at": (record or {}).get("action_items_next_attempt_at"),
    }
