"""create harness tables

Revision ID: c4f4597bb8a2
Revises: 7566da429faa
Create Date: 2026-03-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision: str = "c4f4597bb8a2"
down_revision: Union[str, Sequence[str], None] = "7566da429faa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("harness_rules", "harness_skills", "harness_tools", "harness_hooks")


def _harness_columns():
    return [
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("project", sa.Text, nullable=True),
        sa.Column("agents", ARRAY(sa.Text), nullable=False),
        sa.Column("content", JSONB, nullable=False),
        sa.Column("sort_key", sa.Text, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("version", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("name", "project", name=None, postgresql_nulls_not_distinct=True),
    ]


def upgrade() -> None:
    for table in TABLES:
        op.create_table(table, *_harness_columns(), if_not_exists=True)
        op.create_index(f"idx_{table}_project", table, ["project", "sort_key"], if_not_exists=True)


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_index(f"idx_{table}_project")
        op.drop_table(table)
