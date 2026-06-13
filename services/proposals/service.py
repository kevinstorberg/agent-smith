"""Stage, persist, promote, and reject improvement proposals.

This module is the single boundary between proposal producers (the improve
graph) and consumers (the proposals API router). Proposed content is stored
as a state='proposed' row in the real target table — harness rows
additionally unversioned (version IS NULL) so they are invisible to every
latest-version query — and approval PROMOTES that row in place instead of
copying content.

The LLM agent is a trust boundary: every proposal passes ``stage_proposal``
before anything is written, and ``promote_proposal`` re-validates the target
inside the promoting transaction.
"""
from __future__ import annotations

import hashlib
import json

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from services.api.models.proposal import ProposalModel, existing_fingerprints, get_proposal
from services.api.models.shared.harness import VALID_TABLES, _copy_configs, get_item, get_item_by_id
from services.db import get_connection
from services.jobs.models.job import get_job, get_job_by_name
from services.jobs.schedule import parse_interval
from services.jobs.service import validate_input_params

HARNESS_KINDS = ("rule", "skill", "hook")
VALID_KINDS = (*HARNESS_KINDS, "job")
VALID_ACTIONS = ("create", "update")
JOB_FIELDS = ("schedule_config", "input_params", "description")

TITLE_MAX = 200
RATIONALE_MAX = 2000
BODY_MAX = 20000


class DuplicateProposalError(ValueError):
    """The same change is already pending or was recently rejected."""


class ProposalConflictError(RuntimeError):
    """The target moved (deleted, renamed, or re-versioned) since the proposal was filed."""


def compute_fingerprint(
    target_kind: str, action: str, target_name: str, project: str | None, content: dict
) -> str:
    canonical = json.dumps(
        [target_kind, action, target_name, project, content],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _clean_evidence(evidence) -> list[dict]:
    """Keep well-formed evidence entries; malformed entries are dropped, not fatal."""
    cleaned = []
    for entry in evidence if isinstance(evidence, list) else []:
        if not isinstance(entry, dict) or entry.get("source") not in ("plan", "memory"):
            continue
        if not entry.get("id"):
            continue
        cleaned.append(
            {"source": entry["source"], "id": str(entry["id"]), "note": str(entry.get("note", ""))}
        )
    return cleaned


def _validate_common(p: dict) -> None:
    _require(p.get("target_kind") in VALID_KINDS, f"target_kind must be one of {VALID_KINDS}")
    _require(p.get("action") in VALID_ACTIONS, f"action must be one of {VALID_ACTIONS}")
    _require(bool(p.get("target_name")), "target_name must not be empty")
    title = p.get("title")
    _require(isinstance(title, str) and 0 < len(title) <= TITLE_MAX, f"title must be a 1-{TITLE_MAX} char string")
    rationale = p.get("rationale")
    _require(
        isinstance(rationale, str) and 0 < len(rationale) <= RATIONALE_MAX,
        f"rationale must be a 1-{RATIONALE_MAX} char string",
    )


def _stage_harness(p: dict) -> dict:
    kind, action, name = p["target_kind"], p["action"], p["target_name"]
    project = p.get("project") or None
    body = p.get("body")
    _require(isinstance(body, str) and body.strip() != "", "body must be a non-empty string")
    _require(len(body) <= BODY_MAX, f"body must be at most {BODY_MAX} chars")

    target = get_item(kind, name, project=project)
    if action == "update":
        _require(target is not None, f"{kind} '{name}' does not exist; use action 'create'")
        _require(
            body != target["content"].get("body"),
            "proposed body is identical to the current body — the proposal changes nothing",
        )
        content = {"body": body, "metadata": target["content"].get("metadata", {})}
        seed = {
            "project": target["project"],
            "agents": target["agents"],
            "subagents": target.get("subagents") or [],
            "sort_key": target["sort_key"],
            "enabled": target["enabled"],
            "target_id": target["id"],
            "base_version": target["version"],
        }
    else:
        _require(target is None, f"{kind} '{name}' already exists; use action 'update'")
        content = {"body": body, "metadata": {}}
        seed = {
            "project": project,
            "agents": [],
            "subagents": [],
            "sort_key": 0,
            "enabled": True,
            "target_id": None,
            "base_version": None,
        }
    return {"content": content, "seed": seed, "fingerprint_content": {"body": body}}


def _stage_job(p: dict) -> dict:
    action, name = p["action"], p["target_name"]
    provided = {k: p[k] for k in JOB_FIELDS if p.get(k) is not None}
    _require(bool(provided), f"a job proposal must set at least one of {JOB_FIELDS}")
    if "schedule_config" in provided:
        parse_interval(provided["schedule_config"])
    if "input_params" in provided:
        validate_input_params(provided["input_params"])
    if "description" in provided:
        _require(isinstance(provided["description"], str), "description must be a string")

    target = get_job_by_name(name)
    if action == "update":
        _require(target is not None, f"job '{name}' does not exist; use action 'create'")
        # The proposed row stores the complete intended end-state so the diff
        # UI and promote path never deal with partial rows.
        row = {field: provided.get(field, target[field]) for field in JOB_FIELDS}
        _require(
            any(row[field] != target[field] for field in JOB_FIELDS),
            "proposed job fields are identical to the current job — the proposal changes nothing",
        )
        seed = {"target_id": target["id"], "base_version": target["version"]}
    else:
        _require(target is None, f"job '{name}' already exists; use action 'update'")
        _require(
            "schedule_config" in provided and "input_params" in provided,
            "a new job requires schedule_config and input_params",
        )
        row = {field: provided.get(field) for field in JOB_FIELDS}
        seed = {"target_id": None, "base_version": None}
    return {"content": row, "seed": seed, "fingerprint_content": row}


def stage_proposal(p: dict) -> dict:
    """Validate a raw proposal (LLM output — a trust boundary) into a staged dict.

    Raises ValueError naming the offending field, or DuplicateProposalError if
    the same change is already pending / recently rejected. Writes nothing.
    """
    _require(isinstance(p, dict), "proposal must be an object")
    _validate_common(p)

    kind = p["target_kind"]
    staged_part = _stage_job(p) if kind == "job" else _stage_harness(p)
    project = staged_part["seed"].get("project") if kind != "job" else None

    fingerprint = compute_fingerprint(
        kind, p["action"], p["target_name"], project, staged_part["fingerprint_content"]
    )
    if fingerprint in existing_fingerprints():
        raise DuplicateProposalError(
            f"an equivalent proposal for {kind} '{p['target_name']}' is already pending or was recently rejected"
        )

    return {
        "target_kind": kind,
        "action": p["action"],
        "target_name": p["target_name"],
        "project": project,
        "target_id": staged_part["seed"]["target_id"],
        "base_version": staged_part["seed"]["base_version"],
        "title": p["title"],
        "rationale": p["rationale"],
        "evidence": _clean_evidence(p.get("evidence")),
        "fingerprint": fingerprint,
        "content": staged_part["content"],
        "seed": staged_part["seed"],
    }


def persist_proposal(staged: dict) -> int:
    """Insert the proposed row + master record in one transaction.

    A pending-fingerprint race (two runs filing the same change) surfaces as
    DuplicateProposalError for the caller to count as a skip.
    """
    kind = staged["target_kind"]
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                if kind == "job":
                    cur.execute(
                        """
                        INSERT INTO background_jobs (name, description, schedule_config, input_params, state)
                        VALUES (%s, %s, %s, %s, 'proposed')
                        RETURNING id
                        """,
                        (
                            staged["target_name"],
                            staged["content"]["description"],
                            Json(staged["content"]["schedule_config"]),
                            Json(staged["content"]["input_params"]),
                        ),
                    )
                else:
                    seed = staged["seed"]
                    cur.execute(
                        f"""
                        INSERT INTO {VALID_TABLES[kind]}
                            (name, project, agents, subagents, content, sort_key, enabled, version, state)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, 'proposed')
                        RETURNING id
                        """,
                        (
                            staged["target_name"],
                            seed["project"],
                            seed["agents"] or [],
                            seed["subagents"] or [],
                            Json(staged["content"]),
                            seed["sort_key"],
                            seed["enabled"],
                        ),
                    )
                proposed_item_id = cur.fetchone()[0]

            return ProposalModel.create(
                conn=conn,
                target_kind=kind,
                action=staged["action"],
                proposed_item_id=proposed_item_id,
                target_name=staged["target_name"],
                project=staged["project"],
                target_id=staged["target_id"],
                base_version=staged["base_version"],
                title=staged["title"],
                rationale=staged["rationale"],
                evidence=staged["evidence"],
                fingerprint=staged["fingerprint"],
            )
    except psycopg2.IntegrityError as exc:
        raise DuplicateProposalError(
            f"an equivalent proposal for '{staged['target_name']}' was filed concurrently"
        ) from exc


def _latest_active_row(cur, kind: str, name: str, project: str | None) -> dict | None:
    table = VALID_TABLES[kind]
    cur.execute(
        f"""
        SELECT * FROM {table}
        WHERE name = %s AND project IS NOT DISTINCT FROM %s AND state = 'active'
          AND version = (
              SELECT MAX(v.version) FROM {table} v
              WHERE v.name = %s AND v.project IS NOT DISTINCT FROM %s AND v.state = 'active'
          )
        """,
        (name, project, name, project),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def _promote_harness(cur, proposal: dict) -> dict:
    kind = proposal["target_kind"]
    table = VALID_TABLES[kind]
    name, project = proposal["target_name"], proposal["project"]
    proposed_id = proposal["proposed_item_id"]

    cur.execute(f"SELECT state FROM {table} WHERE id = %s", (proposed_id,))
    row = cur.fetchone()
    if not row or row["state"] != "proposed":
        raise ProposalConflictError("the proposed row no longer exists or was already resolved")

    current = _latest_active_row(cur, kind, name, project)
    if proposal["action"] == "update":
        if current is None:
            raise ProposalConflictError(f"{kind} '{name}' was deleted after this proposal was filed")
        if current["version"] != proposal["base_version"]:
            raise ProposalConflictError(
                f"{kind} '{name}' changed (v{proposal['base_version']} -> v{current['version']}) "
                "after this proposal was filed"
            )
        new_version = current["version"] + 1
    else:
        if current is not None:
            raise ProposalConflictError(f"a {kind} named '{name}' was created after this proposal was filed")
        new_version = 1

    cur.execute(
        f"UPDATE {table} SET state = 'active', version = %s, updated_at = now() WHERE id = %s",
        (new_version, proposed_id),
    )
    if proposal["action"] == "update":
        _copy_configs(cur, current["id"], proposed_id, kind)
    else:
        cur.execute(
            """
            INSERT INTO harness_configs (item_id, item_type, device, repo, agents, subagents, enabled, exclude)
            VALUES (%s, %s, '*', '*', %s, %s, true, false)
            """,
            (proposed_id, kind, [], []),
        )
    return {"item_type": kind, "item_id": proposed_id}


def _promote_job(cur, proposal: dict) -> dict:
    proposed_id = proposal["proposed_item_id"]
    cur.execute("SELECT * FROM background_jobs WHERE id = %s", (proposed_id,))
    proposed = cur.fetchone()
    if not proposed or proposed["state"] != "proposed":
        raise ProposalConflictError("the proposed job row no longer exists or was already resolved")

    if proposal["action"] == "create":
        cur.execute(
            "SELECT 1 FROM background_jobs WHERE name = %s AND state = 'active'",
            (proposal["target_name"],),
        )
        if cur.fetchone():
            raise ProposalConflictError(
                f"a job named '{proposal['target_name']}' was created after this proposal was filed"
            )
        cur.execute(
            "UPDATE background_jobs SET state = 'active', updated_at = now() WHERE id = %s",
            (proposed_id,),
        )
        cur.execute(
            """
            INSERT INTO job_configs (job_id, device, repo, enabled, exclude)
            VALUES (%s, '*', '*', true, false)
            """,
            (proposed_id,),
        )
        return {"job_id": proposed_id}

    cur.execute(
        "SELECT * FROM background_jobs WHERE id = %s AND state = 'active'", (proposal["target_id"],)
    )
    target = cur.fetchone()
    if not target:
        raise ProposalConflictError(
            f"job '{proposal['target_name']}' was deleted after this proposal was filed"
        )
    if target["version"] != proposal["base_version"]:
        raise ProposalConflictError(
            f"job '{proposal['target_name']}' changed (v{proposal['base_version']} -> "
            f"v{target['version']}) after this proposal was filed"
        )

    # Raw SQL instead of update_job so the apply + proposed-row cleanup share
    # this transaction; the version bump mirrors BackgroundJobModel.update.
    cur.execute(
        """
        UPDATE background_jobs
        SET schedule_config = %s, input_params = %s, description = %s,
            version = version + 1, updated_at = now()
        WHERE id = %s
        """,
        (
            Json(proposed["schedule_config"]),
            Json(proposed["input_params"]),
            proposed["description"],
            target["id"],
        ),
    )
    cur.execute("DELETE FROM background_jobs WHERE id = %s", (proposed_id,))
    return {"job_id": target["id"]}


def promote_proposal(proposal_id: int) -> dict:
    """Approve: promote the proposed row in place and mark the proposal applied.

    Re-validates the target inside the transaction; raises ProposalConflictError
    when the target moved (the proposal stays pending for the user to decide).
    Returns the updated proposal record.
    """
    proposal = get_proposal(proposal_id)
    assert proposal, f"Proposal not found: {proposal_id}"
    _require(proposal["status"] == "pending", f"proposal {proposal_id} is not pending")

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if proposal["target_kind"] == "job":
                    applied_ref = _promote_job(cur, proposal)
                else:
                    applied_ref = _promote_harness(cur, proposal)
                assert applied_ref, "promotion produced no applied_ref"
                cur.execute(
                    "UPDATE improvement_proposals SET status = 'approved', applied_ref = %s, updated_at = now() WHERE id = %s",
                    (Json(applied_ref), proposal_id),
                )
    except psycopg2.IntegrityError as exc:
        raise ProposalConflictError(
            "promotion hit a uniqueness conflict — the target changed concurrently"
        ) from exc

    return get_proposal(proposal_id)


def reject_proposal(proposal_id: int) -> dict:
    """Reject: keep both rows for audit/dedup, flip their states."""
    proposal = get_proposal(proposal_id)
    assert proposal, f"Proposal not found: {proposal_id}"
    _require(proposal["status"] == "pending", f"proposal {proposal_id} is not pending")

    table = "background_jobs" if proposal["target_kind"] == "job" else VALID_TABLES[proposal["target_kind"]]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE {table} SET state = 'rejected', updated_at = now() WHERE id = %s AND state = 'proposed'",
                (proposal["proposed_item_id"],),
            )
            cur.execute(
                "UPDATE improvement_proposals SET status = 'rejected', updated_at = now() WHERE id = %s",
                (proposal_id,),
            )
    return get_proposal(proposal_id)


def delete_proposal(proposal_id: int) -> None:
    """Delete the master row and its proposed row — unless that row was
    promoted, in which case it is live content and must survive."""
    proposal = get_proposal(proposal_id)
    assert proposal, f"Proposal not found: {proposal_id}"

    table = "background_jobs" if proposal["target_kind"] == "job" else VALID_TABLES[proposal["target_kind"]]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {table} WHERE id = %s AND state != 'active'",
                (proposal["proposed_item_id"],),
            )
            cur.execute("DELETE FROM improvement_proposals WHERE id = %s", (proposal_id,))


def proposed_item(proposal: dict) -> dict | None:
    """The proposed row backing a proposal (content for the diff UI)."""
    if proposal["target_kind"] == "job":
        return get_job(proposal["proposed_item_id"])
    return get_item_by_id(proposal["target_kind"], proposal["proposed_item_id"])


def current_target(proposal: dict) -> dict | None:
    """The latest active version of the proposal's target, or None if deleted."""
    if proposal["target_kind"] == "job":
        return get_job_by_name(proposal["target_name"])
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            return _latest_active_row(
                cur, proposal["target_kind"], proposal["target_name"], proposal["project"]
            )
