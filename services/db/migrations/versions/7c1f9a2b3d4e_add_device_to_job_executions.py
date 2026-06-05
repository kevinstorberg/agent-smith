"""add device column to job_executions

Revision ID: 7c1f9a2b3d4e
Revises: 23f8a4d0e4b0
Create Date: 2026-06-04 12:00:00.000000

Records which device ran each execution so startup reconciliation only touches
the local scheduler's executions, never another scheduler's in-flight runs.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7c1f9a2b3d4e'
down_revision: Union[str, Sequence[str], None] = '23f8a4d0e4b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'job_executions',
        sa.Column('device', sa.Text, nullable=False, server_default=sa.text("'*'")),
    )
    op.create_index('idx_job_executions_status_device', 'job_executions', ['status', 'device'])


def downgrade() -> None:
    op.drop_index('idx_job_executions_status_device', table_name='job_executions')
    op.drop_column('job_executions', 'device')
