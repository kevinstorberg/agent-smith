"""create eval_results table

Revision ID: 7566da429faa
Revises:
Create Date: 2026-03-23 19:15:10.072742

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = '7566da429faa'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'eval_results',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('eval_type', sa.Text, nullable=False),
        sa.Column('scenario', sa.Text, nullable=False),
        sa.Column('test_model', sa.Text, nullable=False),
        sa.Column('judge_model', sa.Text, nullable=False),
        sa.Column('threshold', sa.Float, nullable=False),
        sa.Column('output', JSONB, nullable=False),
        sa.Column('results', JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        if_not_exists=True,
    )
    op.create_index('idx_eval_results_timestamp', 'eval_results', ['timestamp'], if_not_exists=True)


def downgrade() -> None:
    op.drop_index('idx_eval_results_timestamp')
    op.drop_table('eval_results')
