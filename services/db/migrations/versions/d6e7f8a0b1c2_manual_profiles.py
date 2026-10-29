"""Allow explicitly created profiles without a meeting or email identity.

Revision ID: d6e7f8a0b1c2
Revises: c5d6e7f8a0b1
"""
from alembic import op
import sqlalchemy as sa

revision = "d6e7f8a0b1c2"
down_revision = "c5d6e7f8a0b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("participant_profile_scope", "participant_profiles", type_="check")
    op.create_check_constraint("participant_profile_scope", "participant_profiles", "identity_scope IN ('email', 'meeting', 'manual')")


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT 1 FROM participant_profiles WHERE identity_scope = 'manual' LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade while manual profiles exist; no profiles were changed")
    op.drop_constraint("participant_profile_scope", "participant_profiles", type_="check")
    op.create_check_constraint("participant_profile_scope", "participant_profiles", "identity_scope IN ('email', 'meeting')")
