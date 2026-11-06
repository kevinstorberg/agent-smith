"""Add editable descriptions and revisions to the existing project catalog."""

from alembic import op
import sqlalchemy as sa

revision = "a9c6d3e8f1b2"
down_revision = "f8d5c0e3b7a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "action_item_projects",
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "action_item_projects",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "action_item_projects",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE action_item_projects SET updated_at=created_at")
    op.alter_column(
        "action_item_projects",
        "updated_at",
        nullable=False,
        server_default=sa.func.now(),
    )
    op.create_check_constraint(
        "project_revision_positive", "action_item_projects", "revision > 0"
    )


def downgrade() -> None:
    op.drop_constraint(
        "project_revision_positive", "action_item_projects", type_="check"
    )
    for column in ("updated_at", "revision", "description"):
        op.drop_column("action_item_projects", column)
