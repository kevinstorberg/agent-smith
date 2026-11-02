"""Allow automatic scheduling to pause independently of job configuration."""
from alembic import op
import sqlalchemy as sa

revision = "b6e2d9f4a1c7"
down_revision = "a2c5e8f1b4d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("background_jobs", sa.Column("schedule_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")))


def downgrade() -> None:
    op.execute("LOCK TABLE background_jobs IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM background_jobs WHERE NOT schedule_enabled)")).scalar():
        raise RuntimeError("Cannot downgrade while jobs have automatic scheduling paused; resume them before downgrading")
    op.drop_column("background_jobs", "schedule_enabled")
