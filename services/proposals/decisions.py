from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager
from typing import Literal

import psycopg2
from psycopg2 import sql
from psycopg2.errors import DeadlockDetected, LockNotAvailable, QueryCanceled
from psycopg2.extras import Json, RealDictCursor

from services.api.models.base import BaseModel
from services.proposals.errors import ProposalConflictError, ProposalNotFoundError


@contextmanager
def decision(
    proposal_id: int,
    *,
    model: type[BaseModel],
    connect: Callable[[], AbstractContextManager],
    prepare: Callable[[RealDictCursor, ExitStack, dict], None],
    identity_fields: tuple[str, ...],
    replay_status: Literal["approved", "rejected"] | None,
    pending_only: bool = True,
    busy_errors: tuple[type[Exception], ...] = (),
) -> Iterator[tuple[RealDictCursor, dict]]:
    if type(proposal_id) is not int or proposal_id <= 0:
        raise ValueError("Proposal id must be a positive integer")
    table = sql.Identifier(model.table)
    try:
        with connect() as conn, ExitStack() as stack:
            cur = stack.enter_context(conn.cursor(cursor_factory=RealDictCursor))
            cur.execute("SET LOCAL lock_timeout = '3s'")
            cur.execute("SET LOCAL statement_timeout = '5s'")
            cur.execute(
                sql.SQL("SELECT * FROM {} WHERE id=%s").format(table), (proposal_id,)
            )
            hint = cur.fetchone()
            if hint is None:
                raise ProposalNotFoundError(f"Proposal {proposal_id} not found")
            prepare(cur, stack, dict(hint))
            cur.execute(
                sql.SQL("SELECT * FROM {} WHERE id=%s FOR UPDATE").format(table),
                (proposal_id,),
            )
            proposal = cur.fetchone()
            if proposal is None:
                raise ProposalNotFoundError(f"Proposal {proposal_id} not found")
            if any(proposal[field] != hint[field] for field in identity_fields):
                raise ProposalConflictError(
                    "Proposal identity changed. Refresh before deciding again."
                )
            replay = replay_status is not None and proposal["status"] == replay_status
            if pending_only and proposal["status"] != "pending" and not replay:
                raise ProposalConflictError(
                    f"Proposal {proposal_id} is {proposal['status']}, not pending"
                )
            yield cur, dict(proposal)
    except (LockNotAvailable, QueryCanceled, DeadlockDetected, *busy_errors):
        raise ProposalConflictError(
            "Proposal is busy. Refresh before trying again."
        ) from None
    except psycopg2.IntegrityError as error:
        raise ProposalConflictError(
            "Proposal target changed concurrently. Refresh before trying again."
        ) from error


def record_decision(
    cur: RealDictCursor,
    proposal_id: int,
    status: Literal["approved", "rejected"],
    applied_ref: dict | None = None,
    *,
    model: type[BaseModel],
) -> dict:
    cur.execute(
        sql.SQL(
            "UPDATE {} SET status=%s, applied_ref=%s, updated_at=clock_timestamp() "
            "WHERE id=%s AND status='pending' RETURNING *"
        ).format(sql.Identifier(model.table)),
        (status, Json(applied_ref) if applied_ref is not None else None, proposal_id),
    )
    result = cur.fetchone()
    if result is None:
        raise ProposalConflictError(
            "Proposal was already decided. Refresh before deciding again."
        )
    return model.serialize_timestamps(dict(result))
