"""create plans table

Revision ID: 25243649fc8e
Revises: 6ca1bae4f560
Create Date: 2026-03-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "25243649fc8e"
down_revision: Union[str, Sequence[str], None] = "6ca1bae4f560"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("project", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        if_not_exists=True,
    )
    op.create_index("idx_plans_title", "plans", ["title"], if_not_exists=True)
    op.create_index("idx_plans_project", "plans", ["project"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("idx_plans_project")
    op.drop_index("idx_plans_title")
    op.drop_table("plans")
