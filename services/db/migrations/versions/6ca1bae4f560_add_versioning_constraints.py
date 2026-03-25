"""add versioning constraints

Revision ID: 6ca1bae4f560
Revises: c4f4597bb8a2
Create Date: 2026-03-25
"""
from typing import Sequence, Union

from alembic import op


revision: str = '6ca1bae4f560'
down_revision: Union[str, Sequence[str], None] = 'c4f4597bb8a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ('harness_rules', 'harness_skills', 'harness_tools', 'harness_hooks')


def upgrade() -> None:
    for table in TABLES:
        op.drop_constraint(f'{table}_name_project_key', table, type_='unique')
        op.create_unique_constraint(
            f'{table}_name_project_version_key', table,
            ['name', 'project', 'version'],
            postgresql_nulls_not_distinct=True,
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_constraint(f'{table}_name_project_version_key', table, type_='unique')
        op.create_unique_constraint(
            f'{table}_name_project_key', table,
            ['name', 'project'],
            postgresql_nulls_not_distinct=True,
        )
