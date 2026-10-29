"""Track generated meeting memories and resumable agent output.

Revision ID: f2a3b4c5d6e8
Revises: e1f2a3b4c5d7
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "f2a3b4c5d6e8"
down_revision = "e1f2a3b4c5d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("meeting_digestions", sa.Column("memory_status", sa.Text(), nullable=False, server_default="pending"))
    op.add_column("meeting_digestions", sa.Column("memory_artifact", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("meeting_digestions", sa.Column("memory_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("meeting_digestions", sa.Column("memory_next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.add_column("meeting_digestions", sa.Column("memory_error", sa.Text()))
    op.add_column("meeting_digestions", sa.Column("memory_updated_at", sa.DateTime(timezone=True)))
    op.create_check_constraint("meeting_memory_payload", "meeting_digestions",
                               "memory_status IN ('pending', 'done', 'failed') AND memory_attempts >= 0 AND jsonb_typeof(memory_artifact) = 'object'")


def downgrade() -> None:
    op.drop_constraint("meeting_memory_payload", "meeting_digestions", type_="check")
    for column in ("memory_updated_at", "memory_error", "memory_next_attempt_at", "memory_attempts", "memory_artifact", "memory_status"):
        op.drop_column("meeting_digestions", column)
