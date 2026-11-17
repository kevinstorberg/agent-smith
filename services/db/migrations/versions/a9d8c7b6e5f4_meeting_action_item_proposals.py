"""Add detached Action Item proposals and independent meeting analysis runs.

Revision ID: a9d8c7b6e5f4
Revises: a9c6d3e8f1b2
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "a9d8c7b6e5f4"
down_revision: Union[str, Sequence[str], None] = "a9c6d3e8f1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_proposals_target_kind", "improvement_proposals", type_="check"
    )
    op.create_check_constraint(
        "ck_proposals_target_kind",
        "improvement_proposals",
        "target_kind IN ('rule', 'skill', 'hook', 'job', 'action_item')",
    )
    op.alter_column("improvement_proposals", "proposed_item_id", nullable=True)
    op.create_check_constraint(
        "ck_proposals_detached_payload",
        "improvement_proposals",
        "(target_kind = 'action_item' AND proposed_item_id IS NULL) OR "
        "(target_kind <> 'action_item' AND proposed_item_id IS NOT NULL)",
    )
    op.create_table(
        "action_item_proposal_payloads",
        sa.Column(
            "proposal_id",
            sa.Integer(),
            sa.ForeignKey("improvement_proposals.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("meeting_id", UUID(as_uuid=True), nullable=False),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("source_hash", sa.Text(), nullable=False),
        sa.Column("source_snapshot", JSONB, nullable=False),
        sa.Column("before_snapshot", JSONB),
        sa.Column("changes", JSONB, nullable=False),
        sa.Column("decision_key", sa.Text(), nullable=False),
        sa.Column("create_request_id", UUID(as_uuid=True), nullable=False, unique=True),
        sa.CheckConstraint(
            "source_revision > 0", name="action_item_proposal_source_revision"
        ),
        sa.CheckConstraint(
            "source_hash ~ '^[0-9a-f]{64}$' AND decision_key ~ '^[0-9a-f]{64}$'",
            name="action_item_proposal_hashes",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(source_snapshot) = 'object' AND jsonb_typeof(changes) = 'object'",
            name="action_item_proposal_objects",
        ),
        sa.CheckConstraint(
            "before_snapshot IS NULL OR jsonb_typeof(before_snapshot) = 'object'",
            name="action_item_proposal_before_object",
        ),
    )
    op.create_index(
        "action_item_proposals_decision_key",
        "action_item_proposal_payloads",
        ["decision_key"],
    )
    op.create_table(
        "action_item_proposal_receipts",
        sa.Column("decision_key", sa.Text(), primary_key=True),
        sa.Column(
            "proposal_id",
            sa.Integer(),
            sa.ForeignKey("improvement_proposals.id", ondelete="SET NULL"),
        ),
        sa.CheckConstraint(
            "decision_key ~ '^[0-9a-f]{64}$'", name="action_item_receipt_key"
        ),
    )
    op.create_table(
        "meeting_action_item_runs",
        sa.Column(
            "meeting_id",
            UUID(as_uuid=True),
            sa.ForeignKey("meeting_summaries.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("source_hash", sa.Text(), nullable=False),
        sa.Column(
            "action_items_status", sa.Text(), nullable=False, server_default="pending"
        ),
        sa.Column(
            "action_items_artifact",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "action_items_attempts", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("action_items_error", sa.Text()),
        sa.Column(
            "action_items_next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("claim_owner", sa.Text()),
        sa.Column("claim_until", sa.DateTime(timezone=True)),
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
            "source_revision > 0 AND action_items_attempts >= 0",
            name="meeting_action_item_counters",
        ),
        sa.CheckConstraint(
            "source_hash ~ '^[0-9a-f]{64}$'", name="meeting_action_item_source_hash"
        ),
        sa.CheckConstraint(
            "action_items_status IN ('pending', 'done', 'failed')",
            name="meeting_action_item_status",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(action_items_artifact) = 'object'",
            name="meeting_action_item_artifact",
        ),
        sa.CheckConstraint(
            "(claim_owner IS NULL) = (claim_until IS NULL)",
            name="meeting_action_item_lease",
        ),
    )
    op.create_index(
        "meeting_action_items_due",
        "meeting_action_item_runs",
        ["action_items_status", "action_items_next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_table("meeting_action_item_runs")
    op.drop_table("action_item_proposal_receipts")
    op.drop_table("action_item_proposal_payloads")
    # Approved tasks are independent live records and must survive removal of their audit proposals.
    op.execute("DELETE FROM improvement_proposals WHERE target_kind = 'action_item'")
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
        "target_kind IN ('rule', 'skill', 'hook', 'job')",
    )
