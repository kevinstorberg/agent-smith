"""create tool_call_events audit trail

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-15

Append-only audit trail of coding-agent tool calls. A PreToolUse hook inserts a
'pending' row; the matching PostToolUse hook fills in status/result/completed_at
on the same row (correlated by the agent's native tool id when available, else a
content hash). Immutable history: only the completion fields are ever written.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'tool_call_events',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('correlation_key', sa.Text, nullable=False),
        sa.Column('agent', sa.Text, nullable=False),
        sa.Column('session_id', sa.Text, nullable=False),
        sa.Column('tool_name', sa.Text, nullable=False),
        sa.Column('tool_input', JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('cwd', sa.Text, nullable=True),
        sa.Column('project', sa.Text, nullable=True),
        sa.Column('status', sa.Text, nullable=False, server_default=sa.text("'pending'")),
        sa.Column('result', JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.Integer, nullable=True),
        # Frozen snapshot of services.api.models.audit.AUDIT_AGENTS (migrations must
        # not import app code); kept in sync by tests/test_audit_consistency.py.
        sa.CheckConstraint("agent IN ('claude', 'codex', 'gemini')", name='ck_tool_call_events_agent'),
        sa.CheckConstraint("status IN ('pending', 'success', 'error')", name='ck_tool_call_events_status'),
    )
    op.create_index('idx_tool_call_events_session_created', 'tool_call_events', ['session_id', sa.text('created_at DESC')])
    op.create_index('idx_tool_call_events_agent_created', 'tool_call_events', ['agent', sa.text('created_at DESC')])
    op.create_index('idx_tool_call_events_tool_created', 'tool_call_events', ['tool_name', sa.text('created_at DESC')])
    op.create_index('idx_tool_call_events_project_created', 'tool_call_events', ['project', sa.text('created_at DESC')])
    op.create_index('idx_tool_call_events_correlation', 'tool_call_events', ['correlation_key'])


def downgrade() -> None:
    op.drop_table('tool_call_events')
