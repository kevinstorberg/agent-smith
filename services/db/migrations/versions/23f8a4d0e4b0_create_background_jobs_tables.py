"""create background jobs tables

Revision ID: 23f8a4d0e4b0
Revises: b4c5d6e7f8a9
Create Date: 2026-05-27 13:47:16.276095

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = '23f8a4d0e4b0'
down_revision: Union[str, Sequence[str], None] = 'b4c5d6e7f8a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create background_jobs table
    op.create_table(
        'background_jobs',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('name', sa.Text, nullable=False, unique=True),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('schedule_config', JSONB, nullable=False),
        sa.Column('input_params', JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('version', sa.Integer, nullable=False, server_default=sa.text('1')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Create job_configs table
    op.create_table(
        'job_configs',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('job_id', sa.Integer, sa.ForeignKey('background_jobs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('device', sa.Text, nullable=False, server_default=sa.text("'*'")),
        sa.Column('repo', sa.Text, nullable=False, server_default=sa.text("'*'")),
        sa.Column('enabled', sa.Boolean, nullable=False, server_default=sa.text('true')),
        sa.Column('exclude', sa.Boolean, nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_index('idx_job_configs_job_id', 'job_configs', ['job_id'])

    # Create job_executions table
    op.create_table(
        'job_executions',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('job_id', sa.Integer, sa.ForeignKey('background_jobs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.Text, nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('result', JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )

    op.create_index('idx_job_executions_job_id', 'job_executions', ['job_id', sa.text('started_at DESC')])
    op.create_index('idx_job_executions_status', 'job_executions', ['status'])


def downgrade() -> None:
    op.drop_index('idx_job_executions_status', table_name='job_executions')
    op.drop_index('idx_job_executions_job_id', table_name='job_executions')
    op.drop_table('job_executions')

    op.drop_index('idx_job_configs_job_id', table_name='job_configs')
    op.drop_table('job_configs')

    op.drop_table('background_jobs')
