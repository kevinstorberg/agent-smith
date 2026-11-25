from __future__ import annotations

import hashlib
import json
import re
from uuid import UUID, uuid5

from psycopg2.errors import UniqueViolation
from psycopg2.extras import Json, RealDictCursor

from services.action_items import db as tasks, queue_db
from services.action_items.contracts import Create
from services.api.models.action_item_proposal import ActionItemProposalModel
from services.db import get_connection
from services.action_items.proposal_contracts import (
    ActionItemCandidate,
    ProposalApprove,
    ProposalPlacement,
    TASK_FIELDS,
)
from services.proposals.decisions import decision, record_decision
from services.proposals.errors import DuplicateProposalError, ProposalConflictError

_REQUEST_NAMESPACE = UUID("2052d8d4-8f84-55e7-9b45-0926e679c4ca")
_SOURCE_FIELDS = (
    "id",
    "revision",
    "content_hash",
    "title",
    "summary_text",
    "source_url",
    "meeting_start",
    "provider_created_at",
    "metadata",
)


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _identity(value: str) -> str:
    return " ".join(value.casefold().split())


def _snapshot(snapshot: dict) -> dict:
    if not isinstance(snapshot, dict):
        raise ValueError("Action Item proposals require a saved meeting snapshot")
    try:
        key = str(UUID(snapshot["id"]))
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ValueError("Action Item proposal meeting id must be a UUID") from None
    revision, digest, text = (
        snapshot.get(name) for name in ("revision", "content_hash", "summary_text")
    )
    if type(revision) is not int or revision <= 0:
        raise ValueError("Action Item proposal source revision must be positive")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Action Item proposal source hash must be a SHA-256 digest")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Action Item proposals require nonblank saved summary text")
    result = {field: snapshot.get(field) for field in _SOURCE_FIELDS}
    result["id"] = key
    if len(json.dumps(result).encode()) > 2_000_000:
        raise ValueError("Action Item proposal source snapshot exceeds 2000000 bytes")
    return result


def _assert_source(cursor, snapshot: dict) -> dict:
    cursor.execute(
        "SELECT * FROM meeting_summaries WHERE id=%s FOR SHARE", (snapshot["id"],)
    )
    source = cursor.fetchone()
    if (
        source is None
        or not source["available"]
        or source["revision"] != snapshot["revision"]
        or source["content_hash"] != snapshot["content_hash"]
        or source["summary_text"] != snapshot["summary_text"]
    ):
        raise ProposalConflictError(
            "The source meeting changed or became unavailable. Generate a new proposal before approving."
        )
    return source


def _known_project(cursor, value: str | None) -> str | None:
    name = tasks._project_name(cursor, value)
    if name is not None and tasks._find_project(cursor, name) is None:
        raise ValueError(
            "Action Item proposals must use an existing project or leave it unassigned"
        )
    return name


def _duplicate_task(cursor, title: str, project: str | None) -> bool:
    cursor.execute(
        """SELECT EXISTS(SELECT 1 FROM action_items a
        LEFT JOIN action_item_projects p ON p.id=a.project_id
        WHERE a.scope_key='global' AND a.deleted_at IS NULL
          AND lower(regexp_replace(btrim(a.title), '\\s+', ' ', 'g'))=%s
          AND p.name IS NOT DISTINCT FROM %s) AS found""",
        (" ".join(title.lower().split()), project),
    )
    return cursor.fetchone()["found"]


def _decision_key(candidate: ActionItemCandidate, changes: dict) -> str:
    normalized = {
        field: _identity(value)
        if field in {"title", "description"} and isinstance(value, str)
        else value
        for field, value in changes.items()
    }
    return _hash(["action_item", candidate.action, candidate.target_id, normalized])


def _task_values(task: dict) -> dict:
    return Create.model_validate(
        {field: task[field] for field in TASK_FIELDS}
    ).model_dump(mode="json", exclude={"request_id"})


def _was_dismissed(cursor, decision_key: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM action_item_proposal_receipts WHERE decision_key=%s",
        (decision_key,),
    )
    return cursor.fetchone() is not None


def _has_live_pending(cursor, decision_key: str) -> bool:
    cursor.execute(
        """SELECT 1 FROM action_item_proposal_payloads payload
        JOIN action_item_proposals proposal ON proposal.id=payload.proposal_id
        JOIN meeting_summaries meeting ON meeting.id=payload.meeting_id
        WHERE payload.decision_key=%s AND proposal.status='pending' AND meeting.available
          AND meeting.revision=payload.source_revision AND meeting.content_hash=payload.source_hash
          AND (proposal.action='create' OR EXISTS(SELECT 1 FROM action_items item
              WHERE item.id=proposal.target_id AND item.scope_key='global'
                AND item.deleted_at IS NULL AND item.revision=proposal.base_version))
        LIMIT 1""",
        (decision_key,),
    )
    return cursor.fetchone() is not None


def stage_and_persist(
    snapshot: dict,
    candidate: dict | ActionItemCandidate,
    *,
    lease_owner: str | None = None,
) -> dict:
    source, item, changes = _prepare_candidate(snapshot, candidate)
    if lease_owner is not None and (
        not isinstance(lease_owner, str)
        or not lease_owner.strip()
        or len(lease_owner) > 100
    ):
        raise ValueError(
            "Action Item publication requires a nonblank lease owner of at most 100 characters"
        )
    try:
        with (
            get_connection() as conn,
            conn.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute("SET LOCAL TIME ZONE 'UTC'")
            cursor.execute("SET LOCAL lock_timeout = '3s'")
            cursor.execute("SET LOCAL statement_timeout = '5s'")
            tasks.acquire_write_lock(cursor)
            _assert_source(cursor, source)
            if lease_owner is not None:
                from services.meetings.action_item_db import _owned

                _owned(cursor, source["id"], lease_owner)
            return _persist_candidate(cursor, conn, source, item, changes)
    except UniqueViolation:
        raise DuplicateProposalError(
            "An equivalent Action Item proposal was already filed"
        ) from None


def _prepare_candidate(snapshot: dict, candidate: dict | ActionItemCandidate):
    source = _snapshot(snapshot)
    item = ActionItemCandidate.model_validate(candidate)
    for evidence in item.evidence:
        if (
            evidence.segment_id != "summary-0"
            or not evidence.quote.strip()
            or evidence.quote not in source["summary_text"]
        ):
            raise ValueError(
                "Action Item proposal evidence must quote the exact saved summary-0 text"
            )
    changes = dict(item.changes)
    if item.action == "create":
        changes = Create.model_validate(changes).model_dump(
            mode="json", exclude={"request_id"}
        )
    return source, item, changes


def _changed_values(changes: dict, before: dict) -> dict:
    reviewed = _task_values(before)
    return {
        field: value for field, value in changes.items() if reviewed[field] != value
    }


def dismissed_candidate_indices(
    snapshot: dict, candidates: list[dict], corpus: dict
) -> set[int]:
    tasks_by_id = {
        record["data"]["id"]: record["data"]
        for record in corpus["records"]
        if record["kind"] == "task"
    }
    receipts = set(corpus["receipts"])
    dismissed = set()
    for index, raw in enumerate(candidates):
        _, item, changes = _prepare_candidate(snapshot, raw)
        if item.action == "update":
            before = tasks_by_id.get(item.target_id)
            if before is None or before["revision"] != item.expected_revision:
                raise ProposalConflictError(
                    "Dismissal matching requires current target grounding"
                )
            changes = _changed_values(changes, before)
        if _decision_key(item, changes) in receipts:
            dismissed.add(index)
    return dismissed


def _persist_candidate(
    cursor, conn, source: dict, item: ActionItemCandidate, changes: dict
) -> dict:
    if "project" in changes:
        changes["project"] = _known_project(cursor, changes["project"])
    before = None
    if item.action == "update":
        try:
            before = tasks._read(cursor, item.target_id, tasks._Scope(None))
        except tasks.NotFound:
            raise ProposalConflictError(
                "The proposed Action Item target is missing or deleted."
            ) from None
        if before["revision"] != item.expected_revision:
            raise ProposalConflictError(
                "The proposed Action Item changed. Generate a new proposal using its current revision."
            )
        changes = _changed_values(changes, before)
        if not changes:
            raise DuplicateProposalError(
                "The proposed Action Item update changes nothing"
            )
    elif _duplicate_task(cursor, changes["title"], changes["project"]):
        raise DuplicateProposalError(
            "This Action Item already exists, including completed tasks"
        )
    decision_key = _decision_key(item, changes)
    if _was_dismissed(cursor, decision_key) or _has_live_pending(cursor, decision_key):
        raise DuplicateProposalError(
            "An equivalent Action Item change is already pending or was decided by the User"
        )
    fingerprint = _hash(
        [
            decision_key,
            source["id"],
            source["revision"],
            source["content_hash"],
            item.expected_revision,
        ]
    )
    name = changes.get("title") or before["title"]
    proposal_id = ActionItemProposalModel.create(
        conn=conn,
        action=item.action,
        target_name=name,
        project=changes.get("project", before.get("project") if before else None),
        target_id=item.target_id,
        base_version=item.expected_revision,
        title=f"{'New' if item.action == 'create' else 'Update'}: {name}"[:200],
        rationale=item.rationale.strip(),
        fingerprint=fingerprint,
        evidence=[
            {
                "source": "meeting",
                "id": source["id"],
                "note": source.get("title") or "Meeting",
                "quote": entry.quote,
                "segment_id": entry.segment_id,
                "revision": source["revision"],
            }
            for entry in item.evidence
        ],
    )
    cursor.execute(
        """INSERT INTO action_item_proposal_payloads
        (proposal_id,meeting_id,source_revision,source_hash,source_snapshot,before_snapshot,changes,decision_key,create_request_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            proposal_id,
            source["id"],
            source["revision"],
            source["content_hash"],
            Json(source),
            Json(before) if before is not None else None,
            Json(changes),
            decision_key,
            str(uuid5(_REQUEST_NAMESPACE, fingerprint)),
        ),
    )
    cursor.execute("SELECT * FROM action_item_proposals WHERE id=%s", (proposal_id,))
    return ActionItemProposalModel.serialize_timestamps(dict(cursor.fetchone()))


def _payload(cursor, proposal_id: int) -> dict:
    cursor.execute(
        "SELECT * FROM action_item_proposal_payloads WHERE proposal_id=%s",
        (proposal_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise ProposalConflictError(
            "The Action Item proposal payload is missing. Refresh before deciding again."
        )
    return dict(row)


def reserve_dismissal(cursor, proposal: dict) -> dict:
    payload = _payload(cursor, proposal["id"])
    cursor.execute(
        "INSERT INTO action_item_proposal_receipts(decision_key,proposal_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",
        (payload["decision_key"], proposal["id"]),
    )
    return payload


def promote(cursor, proposal: dict, placement: ProposalPlacement | None = None) -> dict:
    payload = _payload(cursor, proposal["id"])
    if _was_dismissed(cursor, payload["decision_key"]):
        raise ProposalConflictError(
            "An equivalent Action Item change was dismissed. Refresh before deciding again."
        )
    _assert_source(cursor, payload["source_snapshot"])
    changes = dict(payload["changes"])
    if "project" in changes:
        try:
            changes["project"] = _known_project(cursor, changes["project"])
        except ValueError:
            raise ProposalConflictError(
                "The proposed project changed or was deleted. Generate a new proposal."
            ) from None
    try:
        membership_change = None
        if placement is not None:
            if proposal["action"] == "update":
                tasks._live(
                    cursor,
                    proposal["target_id"],
                    tasks._Scope(None),
                    proposal["base_version"],
                )
            membership_change = queue_db.validate_membership(
                cursor,
                proposal["target_id"],
                placement.expected_parent,
                placement.destination,
            )
        if proposal["action"] == "create":
            if _duplicate_task(cursor, changes["title"], changes["project"]):
                raise ProposalConflictError(
                    "An equivalent Action Item was created after this proposal. Refresh before deciding again."
                )
            task = tasks.create(
                {**changes, "request_id": str(payload["create_request_id"])},
                conn=cursor.connection,
            )
        else:
            task = tasks.update(
                proposal["target_id"],
                {**changes, "expected_revision": proposal["base_version"]},
                conn=cursor.connection,
            )
        if membership_change is not None:
            queue_db.apply_membership(cursor, task, membership_change)
    except (tasks.Conflict, tasks.NotFound) as error:
        raise ProposalConflictError(str(error)) from None
    return {
        "action_item_id": task["id"],
        **(
            {"placement": placement.model_dump(mode="json")}
            if placement is not None
            else {}
        ),
    }


def review_details(proposals: list[dict]) -> list[dict]:
    if not proposals:
        return []
    ids = [proposal["id"] for proposal in proposals]
    if len(ids) > 100 or any(type(key) is not int or key <= 0 for key in ids):
        raise ValueError("Review details require at most 100 positive proposal IDs")
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        cursor.execute(
            """SELECT payload.proposal_id, payload.before_snapshot, payload.changes,
                      coalesce(meeting.available, false) AS source_available,
                      (meeting.id IS NULL OR NOT meeting.available
                       OR meeting.revision <> payload.source_revision
                       OR meeting.content_hash <> payload.source_hash) AS source_stale,
                      (proposal.action = 'update' AND
                       (target.id IS NULL OR target.deleted_at IS NOT NULL
                        OR target.revision <> proposal.base_version)) AS target_stale
               FROM action_item_proposal_payloads payload
               JOIN action_item_proposals proposal ON proposal.id = payload.proposal_id
               LEFT JOIN meeting_summaries meeting ON meeting.id = payload.meeting_id
               LEFT JOIN action_items target ON target.id = proposal.target_id
               WHERE payload.proposal_id = ANY(%s)""",
            (ids,),
        )
        details = {row["proposal_id"]: dict(row) for row in cursor.fetchall()}
        parents = queue_db.parent_snapshots(
            cursor,
            [
                proposal["target_id"]
                for proposal in proposals
                if proposal["action"] == "update"
            ],
        )
    if set(ids) != details.keys():
        raise ProposalConflictError(
            "An Action Item proposal payload is missing; refresh before reviewing"
        )
    result = []
    for proposal in proposals:
        payload = details[proposal["id"]]
        before = payload["before_snapshot"] or {}
        result.append(
            {
                **proposal,
                **parents.get(
                    proposal["target_id"],
                    {"current_parent": None, "current_parent_title": None},
                ),
                **{
                    key: payload[key]
                    for key in (
                        "before_snapshot",
                        "source_available",
                        "source_stale",
                        "target_stale",
                    )
                },
                "proposed_item": {
                    **{field: before.get(field) for field in TASK_FIELDS},
                    **payload["changes"],
                },
            }
        )
    return result


def current_target(proposal: dict) -> dict | None:
    if proposal["action"] != "update":
        return None
    try:
        return tasks.get(proposal["target_id"])
    except tasks.NotFound:
        return None


def decision_context(limit: int = 200) -> dict:
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError("Action Item proposal context limit must be between 1 and 200")
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        cursor.execute("SET LOCAL statement_timeout = '5s'")
        cursor.execute("SELECT count(*) AS total FROM action_item_proposals")
        total = cursor.fetchone()["total"]
        cursor.execute(
            """SELECT proposal.id,proposal.status,proposal.action,proposal.target_id,proposal.target_name,
                      proposal.base_version,proposal.rationale,payload.changes,payload.meeting_id::text AS meeting_id,
                      (meeting.id IS NULL OR NOT meeting.available OR meeting.revision<>payload.source_revision
                          OR meeting.content_hash<>payload.source_hash) AS source_stale,
                      (proposal.action='update' AND (item.id IS NULL OR item.deleted_at IS NOT NULL
                          OR item.revision<>proposal.base_version)) AS target_stale
               FROM action_item_proposals proposal JOIN action_item_proposal_payloads payload ON payload.proposal_id=proposal.id
               LEFT JOIN meeting_summaries meeting ON meeting.id=payload.meeting_id
               LEFT JOIN action_items item ON item.id=proposal.target_id AND item.scope_key='global'
               ORDER BY proposal.id DESC LIMIT %s""",
            (limit,),
        )
        return {"items": [dict(row) for row in cursor.fetchall()], "total": total}


def _prepare_decision(cursor, stack, proposal):
    cursor.execute("SET LOCAL TIME ZONE 'UTC'")
    tasks.acquire_write_lock(cursor)


def _decision(
    proposal_id: int, *, replay_status: str | None, pending_only: bool = True
):
    return decision(
        proposal_id,
        model=ActionItemProposalModel,
        connect=get_connection,
        prepare=_prepare_decision,
        identity_fields=("action", "target_id", "base_version", "fingerprint"),
        replay_status=replay_status,
        pending_only=pending_only,
    )


def _record_decision(
    cursor, proposal_id: int, status: str, applied_ref: dict | None = None
) -> dict:
    return record_decision(
        cursor, proposal_id, status, applied_ref, model=ActionItemProposalModel
    )


def promote_proposal(
    proposal_id: int, payload: ProposalApprove | dict | None = None
) -> dict:
    request = ProposalApprove.model_validate({} if payload is None else payload)
    placement = request.placement.model_dump(mode="json") if request.placement else None
    with _decision(proposal_id, replay_status="approved") as (cursor, proposal):
        if proposal["status"] == "approved":
            if (proposal["applied_ref"] or {}).get("placement") != placement:
                raise ProposalConflictError(
                    "This proposal was approved with a different Epic placement. Replay the original approval request."
                )
            return ActionItemProposalModel.serialize_timestamps(proposal)
        applied = promote(cursor, proposal, request.placement)
        return _record_decision(cursor, proposal_id, "approved", applied)


def reject_proposal(proposal_id: int) -> dict:
    with _decision(proposal_id, replay_status="rejected") as (cursor, proposal):
        if proposal["status"] == "rejected":
            return ActionItemProposalModel.serialize_timestamps(proposal)
        reserve_dismissal(cursor, proposal)
        return _record_decision(cursor, proposal_id, "rejected")


def delete_proposal(proposal_id: int) -> None:
    with _decision(proposal_id, replay_status=None, pending_only=False) as (
        cursor,
        proposal,
    ):
        if proposal["status"] in {"pending", "rejected"}:
            reserve_dismissal(cursor, proposal)
        cursor.execute("DELETE FROM action_item_proposals WHERE id=%s", (proposal_id,))
        if cursor.rowcount != 1:
            raise RuntimeError(
                "Locked Action Item proposal disappeared during deletion"
            )


def _validate_replacements(result: dict, corpus: dict, candidate_count: int) -> None:
    kept = result["keep"]
    if (
        not isinstance(kept, list)
        or len(kept) != len(set(kept))
        or any(
            type(index) is not int or not 0 <= index < candidate_count for index in kept
        )
    ):
        raise ValueError(
            "Filtered publication requires unique supplied candidate indexes"
        )
    records = {record["key"]: record for record in corpus["records"]}
    losers = [entry["proposal_id"] for entry in result["supersede"]]
    if len(losers) != len(set(losers)):
        raise ValueError("A pending proposal cannot have competing replacements")
    for entry in result["supersede"]:
        loser = records.get(f"proposal:{entry['proposal_id']}")
        winner = records.get(entry["replacement"])
        if (
            loser is None
            or loser["kind"] != "proposal"
            or loser["data"]["status"] != "pending"
        ):
            raise ProposalConflictError("A superseded proposal must still be pending")
        if entry["replacement"].startswith("candidate:"):
            try:
                index = int(entry["replacement"].split(":")[1])
            except (ValueError, IndexError):
                raise ValueError(
                    "Replacement candidate identity is malformed"
                ) from None
            if index not in kept:
                raise ValueError("Replacement candidate must be kept by this filter")
        elif (
            winner is None
            or winner["kind"] != "proposal"
            or winner["data"]["status"] != "pending"
            or winner["data"]["id"] in losers
        ):
            raise ValueError(
                "Replacement must be a surviving pending proposal; cycles are forbidden"
            )


def publish_filtered_batch(
    snapshot: dict,
    candidates: list[dict],
    result: dict,
    *,
    expected_digest: str,
    artifact: dict,
    lease_owner: str,
) -> dict:
    from services.action_items import proposal_corpus
    from services.meetings import action_item_db, stage_db

    if not isinstance(lease_owner, str) or not lease_owner.startswith("v2:"):
        raise ValueError(
            "Filtered publication requires an owned version-two worker lease"
        )
    source = _snapshot(snapshot)
    prepared = []
    for index in result["keep"]:
        _, item, changes = _prepare_candidate(source, candidates[index])
        if item.action == "create" and changes.get("status") == "completed":
            raise ValueError("Meeting generation cannot create already-completed work")
        prepared.append((index, item, changes))
    try:
        with (
            get_connection() as conn,
            conn.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute("SET LOCAL TIME ZONE 'UTC'")
            cursor.execute("SET LOCAL lock_timeout='3s'")
            cursor.execute("SET LOCAL statement_timeout='5s'")
            tasks.acquire_write_lock(cursor)
            current = proposal_corpus.read(cursor)
            source_ids = sorted(set(current["source_ids"]) | {source["id"]})
            cursor.execute(
                "SELECT id FROM meeting_summaries WHERE id IN %s ORDER BY id FOR SHARE",
                (tuple(source_ids),),
            )
            _assert_source(cursor, source)
            action_item_db._owned(cursor, source["id"], lease_owner)
            current = proposal_corpus.read(cursor)
            if current["digest"] != expected_digest:
                return {"stale": True, "corpus": current}
            _validate_replacements(result, current, len(candidates))
            losers = sorted(entry["proposal_id"] for entry in result["supersede"])
            if losers:
                cursor.execute(
                    "SELECT id FROM action_item_proposals WHERE id IN %s ORDER BY id FOR UPDATE",
                    (tuple(losers),),
                )
                cursor.execute(
                    "UPDATE action_item_proposals SET status='superseded',updated_at=clock_timestamp() WHERE id IN %s AND status='pending'",
                    (tuple(losers),),
                )
                if cursor.rowcount != len(losers):
                    raise ProposalConflictError(
                        "A pending replacement changed during publication"
                    )
            published, skipped = {}, 0
            for index, item, changes in prepared:
                try:
                    row = _persist_candidate(cursor, conn, source, item, changes)
                except DuplicateProposalError:
                    if any(
                        entry["replacement"] == f"candidate:{index}"
                        for entry in result["supersede"]
                    ):
                        raise ProposalConflictError(
                            "A certified replacement was dismissed or already exists"
                        ) from None
                    skipped += 1
                else:
                    published[index] = row["id"]
            for entry in result["supersede"]:
                replacement = entry["replacement"]
                replacement_id = (
                    published[int(replacement.split(":")[1])]
                    if replacement.startswith("candidate:")
                    else int(replacement.split(":")[1])
                )
                cursor.execute(
                    "UPDATE action_item_proposals SET superseded_by_id=%s WHERE id=%s AND status='superseded'",
                    (replacement_id, entry["proposal_id"]),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError(
                        "Locked superseded Action Item audit disappeared"
                    )
            final = {
                **artifact,
                "phase": "done",
                "offset": len(candidates),
                "work_units": artifact.get("work_units", 1) + 1,
                "published_ids": sorted(
                    set(artifact.get("published_ids", [])) | set(published.values())
                ),
                "skipped_count": len(candidates) - len(published),
                "superseded_count": len(losers),
            }
            stage_db.validate_artifact(final)
            cursor.execute(
                "UPDATE meeting_action_item_runs SET action_items_artifact=%s,action_items_status='done',action_items_error=NULL,updated_at=clock_timestamp() WHERE meeting_id=%s AND claim_owner=%s",
                (Json(final), source["id"], lease_owner),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(
                    "Owned Action Item publication checkpoint disappeared"
                )
            return {
                "stale": False,
                "artifact": final,
                "proposals": len(final["published_ids"]),
                "skipped": final["skipped_count"],
                "superseded": len(losers),
            }
    except UniqueViolation:
        raise ProposalConflictError(
            "Action Item publication raced with an existing proposal; refilter current inputs"
        ) from None
