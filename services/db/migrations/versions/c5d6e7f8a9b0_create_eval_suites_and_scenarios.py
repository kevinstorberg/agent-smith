"""create eval_suites and eval_scenarios tables

Revision ID: c5d6e7f8a9b0
Revises: b3c4d5e6f7a8
Create Date: 2026-03-27

Creates eval_suites (suite-level config: judge prompt, items, eval_type/subcategory)
and eval_scenarios (individual test cases per suite). Adds FK columns to eval_results
for linking results back to their config.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = 'c5d6e7f8a9b0'
down_revision: Union[str, Sequence[str], None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'eval_suites',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('name', sa.Text, nullable=False, unique=True),
        sa.Column('eval_type', sa.Text, nullable=False),
        sa.Column('subcategory', sa.Text, nullable=False),
        sa.Column('judge_prompt', sa.Text, nullable=False),
        sa.Column('items', JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('config', JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('enabled', sa.Boolean, nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        if_not_exists=True,
    )

    op.create_table(
        'eval_scenarios',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('suite_id', sa.Integer, sa.ForeignKey('eval_suites.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.Text, nullable=False),
        sa.Column('prompt', sa.Text, nullable=False),
        sa.Column('enabled', sa.Boolean, nullable=False, server_default=sa.text('true')),
        sa.Column('sort_key', sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('suite_id', 'name', name='uq_eval_scenarios_suite_name'),
        if_not_exists=True,
    )
    op.create_index(
        'idx_eval_scenarios_suite',
        'eval_scenarios',
        ['suite_id', 'sort_key'],
        if_not_exists=True,
    )

    op.add_column('eval_results', sa.Column('eval_suite_id', sa.Integer, nullable=True))
    op.add_column('eval_results', sa.Column('eval_scenario_id', sa.Integer, nullable=True))
    op.create_foreign_key(
        'fk_eval_results_suite',
        'eval_results', 'eval_suites',
        ['eval_suite_id'], ['id'],
    )
    op.create_foreign_key(
        'fk_eval_results_scenario',
        'eval_results', 'eval_scenarios',
        ['eval_scenario_id'], ['id'],
    )
    op.create_index(
        'idx_eval_results_suite',
        'eval_results',
        ['eval_suite_id'],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index('idx_eval_results_suite', table_name='eval_results')
    op.drop_constraint('fk_eval_results_scenario', 'eval_results', type_='foreignkey')
    op.drop_constraint('fk_eval_results_suite', 'eval_results', type_='foreignkey')
    op.drop_column('eval_results', 'eval_scenario_id')
    op.drop_column('eval_results', 'eval_suite_id')
    op.drop_index('idx_eval_scenarios_suite', table_name='eval_scenarios')
    op.drop_table('eval_scenarios')
    op.drop_table('eval_suites')
