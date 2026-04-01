"""create harness_configs table and migrate existing deployment config

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-03-31

Non-destructive: creates harness_configs and populates from existing item columns.
Legacy columns (project, agents, subagents, enabled) are NOT dropped from item tables.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY


revision: str = 'f2a3b4c5d6e7'
down_revision: Union[str, Sequence[str], None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

HARNESS_TABLES = {
    'harness_rules': 'rule',
    'harness_skills': 'skill',
    'harness_tools': 'tool',
    'harness_hooks': 'hook',
    'harness_agents': 'agent',
}


def upgrade() -> None:
    op.create_table(
        'harness_configs',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('item_id', sa.Integer, nullable=False),
        sa.Column('item_type', sa.Text, nullable=False),
        sa.Column('device', sa.Text, nullable=False, server_default=sa.text("'*'")),
        sa.Column('repo', sa.Text, nullable=False, server_default=sa.text("'*'")),
        sa.Column('agents', ARRAY(sa.Text), nullable=False, server_default=sa.text("'{claude,codex,gemini}'")),
        sa.Column('subagents', ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'")),
        sa.Column('enabled', sa.Boolean, nullable=False, server_default=sa.text('true')),
        sa.Column('exclude', sa.Boolean, nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        if_not_exists=True,
    )
    op.create_index(
        'idx_harness_configs_item',
        'harness_configs',
        ['item_id', 'item_type'],
        if_not_exists=True,
    )

    # Ensure harness_agents has the subagents column (may be missing on production
    # if the prior migration's if_not_exists skipped the CREATE TABLE).
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'harness_agents' AND column_name = 'subagents'"
    ))
    if not result.fetchone():
        op.add_column(
            'harness_agents',
            sa.Column('subagents', ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'")),
        )

    # Migrate existing deployment config from each harness table into harness_configs.
    # Only migrate the latest version of each item to avoid duplicate configs.
    for table, item_type in HARNESS_TABLES.items():
        op.execute(sa.text(f"""
            INSERT INTO harness_configs (item_id, item_type, device, repo, agents, subagents, enabled, exclude)
            SELECT id, '{item_type}', '*', '*', agents, subagents, enabled, false
            FROM {table} t
            WHERE t.version = (
                SELECT MAX(v.version) FROM {table} v
                WHERE v.name = t.name
                  AND v.project IS NOT DISTINCT FROM t.project
            )
            AND NOT EXISTS (
                SELECT 1 FROM harness_configs c
                WHERE c.item_id = t.id AND c.item_type = '{item_type}'
            )
        """))


def downgrade() -> None:
    op.drop_index('idx_harness_configs_item', table_name='harness_configs')
    op.drop_table('harness_configs')
