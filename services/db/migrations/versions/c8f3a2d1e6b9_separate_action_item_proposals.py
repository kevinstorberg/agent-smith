"""Give Action Item proposals independent review records.

Revision ID: c8f3a2d1e6b9
Revises: a9d8c7b6e5f4
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "c8f3a2d1e6b9"
down_revision = "a9d8c7b6e5f4"
branch_labels = None
depends_on = None

_FIELDS = "id,action,target_name,project,target_id,base_version,title,rationale,evidence,status,fingerprint,applied_ref,created_at,updated_at"
_LINKS = ("action_item_proposal_payloads", "action_item_proposal_receipts")


def _quiescent() -> None:
    active = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT meeting_id FROM meeting_action_item_runs WHERE claim_owner IS NOT NULL AND claim_until>clock_timestamp() LIMIT 1"
            )
        )
        .scalar()
    )
    if active is not None:
        raise RuntimeError(
            "Stop Action Item generation workers and wait for their leases to expire before migrating"
        )


def _retarget(parent: str) -> None:
    for child in _LINKS:
        name = child + "_proposal_id_fkey"
        op.drop_constraint(name, child, type_="foreignkey")
        op.create_foreign_key(
            name,
            child,
            parent,
            ["proposal_id"],
            ["id"],
            ondelete="CASCADE" if child.endswith("payloads") else "SET NULL",
        )


def _sequence(table: str) -> None:
    op.execute(
        sa.text(
            f"SELECT setval(pg_get_serial_sequence('{table}','id'), COALESCE(max(id),1), count(*)>0) FROM {table}"
        )
    )


def _validate_legacy() -> None:
    connection = op.get_bind()
    references = {
        tuple(row)
        for row in connection.execute(
            sa.text(
                "SELECT conrelid::regclass::text,conname FROM pg_constraint WHERE contype='f' AND confrelid='improvement_proposals'::regclass"
            )
        )
    }
    expected = {(child, child + "_proposal_id_fkey") for child in _LINKS}
    if references != expected:
        raise RuntimeError(
            f"Unexpected proposal foreign-key references; inspect before migrating: {sorted(references)}"
        )
    rows = connection.execute(
        sa.text("SELECT id,target_kind,proposed_item_id FROM improvement_proposals")
    ).mappings()
    legacy = set()
    for row in rows:
        if row["target_kind"] == "action_item":
            legacy.add(row["id"])
        elif (
            row["target_kind"] not in {"rule", "skill", "hook", "job"}
            or row["proposed_item_id"] is None
        ):
            raise RuntimeError(
                f"Harness proposal {row['id']} cannot satisfy the restored harness schema"
            )
    payloads = dict(
        connection.execute(
            sa.text(
                "SELECT proposal_id,meeting_id::text FROM action_item_proposal_payloads"
            )
        ).all()
    )
    if set(payloads) != legacy:
        raise RuntimeError(
            "Action Item proposal masters and payloads do not match; repair the missing or misplaced payload before migrating"
        )
    for meeting, artifact in connection.execute(
        sa.text(
            "SELECT meeting_id::text,action_items_artifact FROM meeting_action_item_runs"
        )
    ):
        published = artifact.get("published_ids", [])
        if not isinstance(published, list) or any(
            type(key) is not int or key <= 0 for key in published
        ):
            raise RuntimeError(
                f"Invalid saved Action Item proposal IDs for meeting {meeting}"
            )
        for key in published:
            # Deleted review records legitimately leave historical checkpoint IDs.
            if key in payloads and payloads[key] != meeting:
                raise RuntimeError(
                    f"Saved proposal {key} belongs to a different meeting"
                )
            if (
                key not in legacy
                and connection.execute(
                    sa.text("SELECT 1 FROM improvement_proposals WHERE id=:key"),
                    {"key": key},
                ).scalar()
            ):
                raise RuntimeError(
                    f"Saved Action Item proposal {key} resolves to a harness proposal"
                )


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        "LOCK TABLE improvement_proposals,action_item_proposal_payloads,action_item_proposal_receipts,meeting_action_item_runs IN ACCESS EXCLUSIVE MODE"
    )
    _quiescent()
    _validate_legacy()
    op.create_table(
        "action_item_proposals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_name", sa.Text(), nullable=False),
        sa.Column("project", sa.Text()),
        sa.Column("target_id", sa.Integer()),
        sa.Column("base_version", sa.Integer()),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column(
            "evidence", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("applied_ref", JSONB),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "action IN ('create','update')", name="action_item_proposal_action"
        ),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected')",
            name="action_item_proposal_status",
        ),
        sa.CheckConstraint(
            "(action='create' AND target_id IS NULL AND base_version IS NULL) OR (action='update' AND target_id>0 AND base_version>0 AND target_id IS NOT NULL AND base_version IS NOT NULL)",
            name="action_item_proposal_target",
        ),
    )
    op.create_index(
        "action_item_proposals_status_created",
        "action_item_proposals",
        ["status", sa.text("created_at DESC")],
    )
    op.create_index(
        "action_item_proposals_pending_fingerprint",
        "action_item_proposals",
        ["fingerprint"],
        unique=True,
        postgresql_where=sa.text("status='pending'"),
    )
    op.execute(
        f"INSERT INTO action_item_proposals ({_FIELDS}) SELECT {_FIELDS} FROM improvement_proposals WHERE target_kind='action_item'"
    )
    # Reparent first so deleting legacy masters cannot cascade into retained drafts.
    _retarget("action_item_proposals")
    op.execute("DELETE FROM improvement_proposals WHERE target_kind='action_item'")
    op.drop_constraint(
        "ck_proposals_detached_payload", "improvement_proposals", type_="check"
    )
    op.alter_column("improvement_proposals", "proposed_item_id", nullable=False)
    op.drop_constraint(
        "ck_proposals_target_kind", "improvement_proposals", type_="check"
    )
    op.create_check_constraint(
        "ck_proposals_target_kind",
        "improvement_proposals",
        "target_kind IN ('rule','skill','hook','job')",
    )
    _sequence("action_item_proposals")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        "LOCK TABLE improvement_proposals,action_item_proposals,action_item_proposal_payloads,action_item_proposal_receipts,meeting_action_item_runs IN ACCESS EXCLUSIVE MODE"
    )
    _quiescent()
    collision = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT item.id FROM action_item_proposals item JOIN improvement_proposals harness ON harness.id=item.id LIMIT 1"
            )
        )
        .scalar()
    )
    if collision is not None:
        raise RuntimeError(
            f"Cannot downgrade: independent proposal IDs overlap at {collision}; restore a pre-upgrade backup instead"
        )
    op.drop_constraint(
        "ck_proposals_target_kind", "improvement_proposals", type_="check"
    )
    op.create_check_constraint(
        "ck_proposals_target_kind",
        "improvement_proposals",
        "target_kind IN ('rule','skill','hook','job','action_item')",
    )
    op.alter_column("improvement_proposals", "proposed_item_id", nullable=True)
    op.create_check_constraint(
        "ck_proposals_detached_payload",
        "improvement_proposals",
        "(target_kind='action_item' AND proposed_item_id IS NULL) OR (target_kind<>'action_item' AND proposed_item_id IS NOT NULL)",
    )
    tail = _FIELDS.removeprefix("id,")
    op.execute(
        f"INSERT INTO improvement_proposals(id,target_kind,proposed_item_id,{tail}) SELECT id,'action_item',NULL,{tail} FROM action_item_proposals"
    )
    _retarget("improvement_proposals")
    _sequence("improvement_proposals")
    op.drop_table("action_item_proposals")
