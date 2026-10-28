"""Create source-independent meeting context and resumable sync state.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "meeting_sync_state",
        sa.Column("provider", sa.Text(), primary_key=True),
        sa.Column("account_key", sa.Text(), primary_key=True),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("config_fingerprint", sa.Text(), nullable=False),
        sa.Column("claim_owner", sa.Text()),
        sa.Column("claim_until", sa.DateTime(timezone=True)),
        sa.Column("scan", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("outcome", sa.Text(), nullable=False, server_default="idle"),
        sa.Column("last_error", sa.Text()),
        sa.Column("last_completed_at", sa.DateTime(timezone=True)),
        sa.Column("last_deep_completed_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("jsonb_typeof(scan) = 'object'", name="meeting_scan_object"),
    )
    op.create_table(
        "meeting_summaries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("account_key", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("project", sa.Text()),
        sa.Column("title", sa.Text()),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("summary_markdown", sa.Text()),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("provider_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_deleted_at", sa.DateTime(timezone=True)),
        sa.Column("meeting_start", sa.DateTime(timezone=True)),
        sa.Column("meeting_end", sa.DateTime(timezone=True)),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("missing_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_seen_scan_id", sa.Text()),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("provider", "account_key", "external_id", name="meeting_summary_identity"),
        sa.CheckConstraint("revision > 0 AND missing_count >= 0", name="meeting_summary_counters"),
        sa.CheckConstraint("length(btrim(summary_text)) > 0", name="meeting_summary_not_blank"),
    )
    op.create_index("meeting_summaries_source_updated", "meeting_summaries", ["source_name", "updated_at"])
    op.create_index("meeting_summaries_project_start", "meeting_summaries", ["project", "meeting_start"])


def downgrade() -> None:
    op.drop_table("meeting_summaries")
    op.drop_table("meeting_sync_state")
