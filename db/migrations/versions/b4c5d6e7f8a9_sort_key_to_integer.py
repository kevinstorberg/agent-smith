"""convert sort_key from text to integer

Revision ID: b4c5d6e7f8a9
Revises: a2b3c4d5e6f7
Create Date: 2026-04-02

Converts sort_key columns from TEXT to INTEGER across all harness tables
and eval_scenarios. Existing numeric strings are cast; non-numeric values
default to 0. Drops and recreates composite indexes that reference sort_key.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, Sequence[str], None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = (
    "harness_rules",
    "harness_skills",
    "harness_tools",
    "harness_hooks",
    "harness_agents",
    "eval_scenarios",
)

INDEXES = [
    ("idx_harness_rules_project", "harness_rules", ["project", "sort_key"]),
    ("idx_harness_skills_project", "harness_skills", ["project", "sort_key"]),
    ("idx_harness_tools_project", "harness_tools", ["project", "sort_key"]),
    ("idx_harness_hooks_project", "harness_hooks", ["project", "sort_key"]),
    ("idx_harness_agents_project", "harness_agents", ["project", "sort_key"]),
    ("idx_eval_scenarios_suite", "eval_scenarios", ["suite_id", "sort_key"]),
]


def upgrade() -> None:
    for idx_name, table, _cols in INDEXES:
        op.drop_index(idx_name, table_name=table)

    for table in TABLES:
        op.add_column(table, sa.Column("sort_order", sa.Integer, nullable=True))
        op.execute(f"""
            UPDATE {table} SET sort_order = CASE
                WHEN sort_key ~ '^[0-9]+$' THEN sort_key::integer
                ELSE 0
            END
        """)
        op.alter_column(table, "sort_order", nullable=False, server_default=sa.text("0"))
        op.drop_column(table, "sort_key")
        op.alter_column(table, "sort_order", new_column_name="sort_key")

    for idx_name, table, cols in INDEXES:
        op.create_index(idx_name, table, cols)


def downgrade() -> None:
    for idx_name, table, _cols in INDEXES:
        op.drop_index(idx_name, table_name=table)

    for table in TABLES:
        op.add_column(table, sa.Column("sort_key_text", sa.Text, nullable=True))
        op.execute(f"UPDATE {table} SET sort_key_text = sort_key::text")
        op.alter_column(table, "sort_key_text", nullable=False, server_default=sa.text("''"))
        op.drop_column(table, "sort_key")
        op.alter_column(table, "sort_key_text", new_column_name="sort_key")

    for idx_name, table, cols in INDEXES:
        op.create_index(idx_name, table, cols)
