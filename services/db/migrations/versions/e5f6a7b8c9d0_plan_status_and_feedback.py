"""add plan status and plan_feedback table

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-13

Captures opinion-graph reviews: the plan sent to the opinion node is saved as a
draft (plans.status='draft') and the full feedback returned is stored in the new
plan_feedback table, linked by FK. Existing plans default to 'final'.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'plans',
        sa.Column('status', sa.Text, nullable=False, server_default=sa.text("'final'")),
    )
    op.create_check_constraint('ck_plans_status', 'plans', "status IN ('draft', 'final')")
    op.create_index('idx_plans_status', 'plans', ['status', sa.text('created_at DESC')])

    op.create_table(
        'plan_feedback',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('plan_id', sa.Integer, sa.ForeignKey('plans.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source', sa.Text, nullable=False, server_default=sa.text("'opinion'")),
        sa.Column('body', sa.Text, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('idx_plan_feedback_plan_id', 'plan_feedback', ['plan_id'])


def downgrade() -> None:
    op.drop_table('plan_feedback')
    op.drop_index('idx_plans_status', table_name='plans')
    op.drop_constraint('ck_plans_status', 'plans', type_='check')
    op.drop_column('plans', 'status')
