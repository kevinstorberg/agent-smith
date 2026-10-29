"""Checkpoint lightweight statement attribution separately from meeting memories."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "7f2a9c6d8e10"
down_revision = "c7a8e9f0b1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("meeting_digestions", sa.Column("speaker_status", sa.Text(), nullable=False, server_default="pending"))
    op.add_column("meeting_digestions", sa.Column("speaker_artifact", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("meeting_digestions", sa.Column("speaker_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("meeting_digestions", sa.Column("speaker_next_attempt_at", sa.DateTime(timezone=True), nullable=False,
                                                server_default=sa.func.now()))
    op.add_column("meeting_digestions", sa.Column("speaker_error", sa.Text()))
    op.add_column("meeting_digestions", sa.Column("speaker_updated_at", sa.DateTime(timezone=True)))
    op.create_check_constraint("meeting_speaker_payload", "meeting_digestions",
                               "speaker_status IN ('pending', 'done', 'failed', 'legacy') "
                               "AND speaker_attempts >= 0 AND jsonb_typeof(speaker_artifact) = 'object'")
    # Completed memory work must never become an automatic historical model backfill.
    op.execute("UPDATE meeting_digestions SET speaker_status='legacy' WHERE memory_status='done'")


def downgrade() -> None:
    op.drop_constraint("meeting_speaker_payload", "meeting_digestions", type_="check")
    for column in ("speaker_updated_at", "speaker_error", "speaker_next_attempt_at", "speaker_attempts", "speaker_artifact", "speaker_status"):
        op.drop_column("meeting_digestions", column)
