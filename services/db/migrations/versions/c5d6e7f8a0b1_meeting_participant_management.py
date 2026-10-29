"""Allow explicit historical processing and human participant attribution."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "c5d6e7f8a0b1"
down_revision = "b4c5d6e7f8a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("meeting_summaries", sa.Column("manual_participants", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("meeting_summaries", sa.Column("participants_revision", sa.Integer(), nullable=False, server_default="0"))
    op.create_check_constraint("meeting_manual_participants", "meeting_summaries", "jsonb_typeof(manual_participants) = 'array' AND participants_revision >= 0")
    op.add_column("meeting_digestions", sa.Column("requested_at", sa.DateTime(timezone=True)))
    op.add_column("meeting_digestions", sa.Column("participant_snapshot", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("meeting_digestions", sa.Column("participants_revision", sa.Integer(), nullable=False, server_default="0"))
    op.create_check_constraint("meeting_participant_snapshot", "meeting_digestions", "jsonb_typeof(participant_snapshot) = 'array' AND participants_revision >= 0")


def downgrade() -> None:
    op.drop_constraint("meeting_participant_snapshot", "meeting_digestions", type_="check")
    for column in ("participants_revision", "participant_snapshot", "requested_at"):
        op.drop_column("meeting_digestions", column)
    op.drop_constraint("meeting_manual_participants", "meeting_summaries", type_="check")
    op.drop_column("meeting_summaries", "participants_revision")
    op.drop_column("meeting_summaries", "manual_participants")
