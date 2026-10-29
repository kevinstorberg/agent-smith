"""Add profile organization and explicit identity links.

Revision ID: b4c5d6e7f8a0
Revises: a3b4c5d6e7f9
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision = "b4c5d6e7f8a0"
down_revision = "a3b4c5d6e7f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("participant_profiles", sa.Column("tags", ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'::text[]")))
    op.add_column("participant_profiles", sa.Column("starred", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("participant_profiles", sa.Column("merged_into", UUID(as_uuid=True), sa.ForeignKey("participant_profiles.id", ondelete="RESTRICT")))
    op.add_column("participant_profiles", sa.Column("merge_history", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.create_check_constraint("participant_profile_not_self_alias", "participant_profiles", "merged_into IS NULL OR merged_into <> id")
    op.create_check_constraint("participant_profile_merge_history", "participant_profiles", "jsonb_typeof(merge_history) = 'array'")
    op.create_index("participant_profiles_merged_into", "participant_profiles", ["merged_into"])


def downgrade() -> None:
    op.drop_index("participant_profiles_merged_into", table_name="participant_profiles")
    op.drop_constraint("participant_profile_merge_history", "participant_profiles", type_="check")
    op.drop_constraint("participant_profile_not_self_alias", "participant_profiles", type_="check")
    op.drop_column("participant_profiles", "merged_into")
    op.drop_column("participant_profiles", "merge_history")
    op.drop_column("participant_profiles", "starred")
    op.drop_column("participant_profiles", "tags")
