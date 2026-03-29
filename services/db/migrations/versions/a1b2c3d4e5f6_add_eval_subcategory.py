"""add eval subcategory column

Revision ID: a1b2c3d4e5f6
Revises: 25243649fc8e
Create Date: 2026-03-27

Additive-only migration: adds a nullable column, backfills existing rows,
and creates an index. No columns are dropped, renamed, or altered.
No rows are deleted. No constraints are tightened.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '25243649fc8e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'eval_results',
        sa.Column('subcategory', sa.Text, nullable=True),
    )
    op.execute("UPDATE eval_results SET subcategory = 'plans' WHERE eval_type = 'rules'")
    op.create_index(
        'idx_eval_results_eval_type_subcategory',
        'eval_results',
        ['eval_type', 'subcategory'],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index('idx_eval_results_eval_type_subcategory')
    op.drop_column('eval_results', 'subcategory')
