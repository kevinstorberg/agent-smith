"""Enroll newly imported meetings for transcript capture.

Revision ID: e1f2a3b4c5d7
Revises: d0e1f2a3b4c5
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "e1f2a3b4c5d7"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "meeting_digestions",
        sa.Column("meeting_id", UUID(as_uuid=True), sa.ForeignKey("meeting_summaries.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("transcript_status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("transcript", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("snapshot", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("transcript_hash", sa.Text()),
        sa.Column("claim_owner", sa.Text()),
        sa.Column("claim_until", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("error_type", sa.Text()),
        sa.Column("captured_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("transcript_status IN ('pending', 'ready', 'unsupported', 'unavailable', 'failed', 'deleted')", name="meeting_transcript_status"),
        sa.CheckConstraint("attempts >= 0 AND jsonb_typeof(transcript) = 'object' AND jsonb_typeof(snapshot) = 'object'", name="meeting_digestion_payload"),
    )
    op.create_index("meeting_digestions_pending", "meeting_digestions", ["transcript_status", "next_attempt_at", "created_at"])


def downgrade() -> None:
    op.drop_table("meeting_digestions")
