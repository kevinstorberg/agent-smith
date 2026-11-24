from __future__ import annotations

from psycopg2.extras import RealDictCursor

from services.action_items import db as tasks
from services.action_items.matching import digest
from services.action_items.proposal_contracts import TASK_FIELDS
from services.db import get_connection


def read(cursor) -> dict:
    scope = tasks._Scope(None)
    cursor.execute(
        f"SELECT {scope.columns(detail=True)} FROM {tasks._PROJECT_ROWS} "
        "WHERE a.scope_key='global' AND a.deleted_at IS NULL ORDER BY a.id"
    )
    records = []
    for row in cursor.fetchall():
        item = tasks._record(row)
        data = {field: item[field] for field in TASK_FIELDS | {"id", "revision"}}
        records.append({"key": f"task:{item['id']}", "kind": "task", "data": data})
    cursor.execute(
        """SELECT p.*,d.meeting_id::text AS meeting_id,d.source_revision,d.source_hash,
        d.before_snapshot,d.changes,d.decision_key,
        jsonb_build_object('meeting_start',d.source_snapshot->'meeting_start',
            'provider_created_at',d.source_snapshot->'provider_created_at') AS source_timing,
        (m.id IS NULL OR NOT m.available OR m.revision<>d.source_revision OR m.content_hash<>d.source_hash) AS source_stale,
        (p.action='update' AND (a.id IS NULL OR a.deleted_at IS NOT NULL OR a.revision<>p.base_version)) AS target_stale
        FROM action_item_proposals p JOIN action_item_proposal_payloads d ON d.proposal_id=p.id
        LEFT JOIN meeting_summaries m ON m.id=d.meeting_id
        LEFT JOIN action_items a ON a.id=p.target_id AND a.scope_key='global' ORDER BY p.id"""
    )
    source_ids = set()
    for row in cursor.fetchall():
        data = dict(row)
        source_ids.add(data["meeting_id"])
        data.pop("updated_at")
        if data["before_snapshot"]:
            data["before_snapshot"] = {
                field: value
                for field, value in data["before_snapshot"].items()
                if field in TASK_FIELDS | {"id", "revision"}
            }
        records.append(
            {"key": f"proposal:{data['id']}", "kind": "proposal", "data": data}
        )
    cursor.execute(
        "SELECT decision_key FROM action_item_proposal_receipts ORDER BY decision_key"
    )
    receipts = [row["decision_key"] for row in cursor.fetchall()]
    cursor.execute("SELECT id,name,revision FROM action_item_projects ORDER BY id")
    projects = [dict(row) for row in cursor.fetchall()]
    manifest = {record["key"]: digest(record) for record in records}
    manifest.update({f"receipt:{key}": key for key in receipts})
    manifest.update({f"project:{item['id']}": digest(item) for item in projects})
    return {
        "records": records,
        "manifest": manifest,
        "digest": digest(manifest),
        "source_ids": sorted(source_ids),
        "receipts": receipts,
        "projects": projects,
    }


def snapshot() -> dict:
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        cursor.execute("SET LOCAL TIME ZONE 'UTC'")
        cursor.execute("SET LOCAL statement_timeout='5s'")
        return read(cursor)
