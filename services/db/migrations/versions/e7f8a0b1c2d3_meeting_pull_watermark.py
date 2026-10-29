"""Track the start of each successfully completed incremental meeting pull."""
from alembic import op
import sqlalchemy as sa

revision = "e7f8a0b1c2d3"
down_revision = "d6e7f8a0b1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("meeting_sync_state", sa.Column("last_pull_started_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("meeting_sync_state", "last_pull_started_at")
