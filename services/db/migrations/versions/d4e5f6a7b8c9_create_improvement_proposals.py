"""create improvement proposals

Revision ID: d4e5f6a7b8c9
Revises: 7c1f9a2b3d4e
Create Date: 2026-06-12

Proposed harness items and jobs live in their real tables in a 'proposed'
state so approval promotes the existing row instead of copying content.
Proposed harness rows are unversioned (version IS NULL), which keeps them
invisible to every latest-version query (version = MAX(version) never
matches NULL). The unique constraints move to partial unique indexes scoped
to active rows so multiple proposed rows per item can coexist.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = '7c1f9a2b3d4e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STATE_CHECK = "state IN ('active', 'proposed', 'rejected')"
HARNESS_TABLES = ('harness_rules', 'harness_skills', 'harness_hooks')


def upgrade() -> None:
    for table in HARNESS_TABLES:
        op.add_column(
            table,
            sa.Column('state', sa.Text, nullable=False, server_default=sa.text("'active'")),
        )
        op.create_check_constraint(f'ck_{table}_state', table, STATE_CHECK)
        op.alter_column(table, 'version', nullable=True)
        op.drop_constraint(f'{table}_name_project_version_key', table, type_='unique')
        op.execute(
            f"CREATE UNIQUE INDEX {table}_active_name_project_version_key "
            f"ON {table} (name, project, version) NULLS NOT DISTINCT "
            f"WHERE state = 'active'"
        )

    op.add_column(
        'background_jobs',
        sa.Column('state', sa.Text, nullable=False, server_default=sa.text("'active'")),
    )
    op.create_check_constraint('ck_background_jobs_state', 'background_jobs', STATE_CHECK)
    op.drop_constraint('background_jobs_name_key', 'background_jobs', type_='unique')
    op.execute(
        "CREATE UNIQUE INDEX background_jobs_active_name_key "
        "ON background_jobs (name) WHERE state = 'active'"
    )

    op.create_table(
        'improvement_proposals',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('target_kind', sa.Text, nullable=False),
        sa.Column('action', sa.Text, nullable=False),
        sa.Column('proposed_item_id', sa.Integer, nullable=False),
        sa.Column('target_name', sa.Text, nullable=False),
        sa.Column('project', sa.Text, nullable=True),
        sa.Column('target_id', sa.Integer, nullable=True),
        sa.Column('base_version', sa.Integer, nullable=True),
        sa.Column('title', sa.Text, nullable=False),
        sa.Column('rationale', sa.Text, nullable=False),
        sa.Column('evidence', JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('status', sa.Text, nullable=False, server_default=sa.text("'pending'")),
        sa.Column('fingerprint', sa.Text, nullable=False),
        sa.Column('applied_ref', JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("target_kind IN ('rule', 'skill', 'hook', 'job')", name='ck_proposals_target_kind'),
        sa.CheckConstraint("action IN ('create', 'update')", name='ck_proposals_action'),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected')", name='ck_proposals_status'),
    )
    op.create_index(
        'idx_proposals_status_created',
        'improvement_proposals',
        ['status', sa.text('created_at DESC')],
    )
    op.create_index('idx_proposals_fingerprint', 'improvement_proposals', ['fingerprint'])
    op.execute(
        "CREATE UNIQUE INDEX uq_proposals_pending_fingerprint "
        "ON improvement_proposals (fingerprint) WHERE status = 'pending'"
    )


def downgrade() -> None:
    op.drop_table('improvement_proposals')

    # Non-active rows cannot survive the restored constraints (NULL versions,
    # duplicate names), so a downgrade discards them.
    op.execute("DELETE FROM background_jobs WHERE state != 'active'")
    op.execute("DROP INDEX background_jobs_active_name_key")
    op.create_unique_constraint('background_jobs_name_key', 'background_jobs', ['name'])
    op.drop_constraint('ck_background_jobs_state', 'background_jobs', type_='check')
    op.drop_column('background_jobs', 'state')

    for table in reversed(HARNESS_TABLES):
        op.execute(f"DELETE FROM {table} WHERE state != 'active'")
        op.execute(f"DROP INDEX {table}_active_name_project_version_key")
        op.alter_column(table, 'version', nullable=False)
        op.create_unique_constraint(
            f'{table}_name_project_version_key', table,
            ['name', 'project', 'version'],
            postgresql_nulls_not_distinct=True,
        )
        op.drop_constraint(f'ck_{table}_state', table, type_='check')
        op.drop_column(table, 'state')
