"""Store optional UTC deadlines for global action items."""

from alembic import op
import sqlalchemy as sa

revision = "f8d5c0e3b7a2"
down_revision = "e7c4b9d2a6f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "action_items", sa.Column("due_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        "action_item_due_global", "action_items", "profile_id IS NULL OR due_at IS NULL"
    )


def downgrade() -> None:
    op.drop_constraint("action_item_due_global", "action_items", type_="check")
    op.drop_column("action_items", "due_at")
