"""create harness_agents table and add subagents column to existing tables

Revision ID: e1f2a3b4c5d6
Revises: c5d6e7f8a9b0
Create Date: 2026-03-30

Adds harness_agents as a 5th harness item type for managing sub-agent definitions.
Adds a subagents ARRAY column to existing harness tables so items can be scoped
to specific sub-agents (empty = main agent only, ["*"] = all, ["name"] = specific).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB


revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, Sequence[str], None] = 'c5d6e7f8a9b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EXISTING_TABLES = ('harness_rules', 'harness_skills', 'harness_tools', 'harness_hooks')


def upgrade() -> None:
    # Create harness_agents table (same schema as other harness tables + versioning)
    op.create_table(
        'harness_agents',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('name', sa.Text, nullable=False),
        sa.Column('project', sa.Text, nullable=True),
        sa.Column('agents', ARRAY(sa.Text), nullable=False),
        sa.Column('subagents', ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'")),
        sa.Column('content', JSONB, nullable=False),
        sa.Column('sort_key', sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column('enabled', sa.Boolean, nullable=False, server_default=sa.text('true')),
        sa.Column('version', sa.Integer, nullable=False, server_default=sa.text('1')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            'name', 'project', 'version',
            name='harness_agents_name_project_version_key',
            postgresql_nulls_not_distinct=True,
        ),
        if_not_exists=True,
    )
    op.create_index(
        'idx_harness_agents_project',
        'harness_agents',
        ['project', 'sort_key'],
        if_not_exists=True,
    )

    # Add subagents column to existing harness tables
    for table in EXISTING_TABLES:
        op.add_column(
            table,
            sa.Column('subagents', ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'")),
        )


def downgrade() -> None:
    for table in reversed(EXISTING_TABLES):
        op.drop_column(table, 'subagents')

    op.drop_index('idx_harness_agents_project', table_name='harness_agents')
    op.drop_table('harness_agents')
