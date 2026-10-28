"""Persist participant profiles and their resumable meeting stage.

Revision ID: a3b4c5d6e7f9
Revises: f2a3b4c5d6e8
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "a3b4c5d6e7f9"
down_revision = "f2a3b4c5d6e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("meeting_digestions", sa.Column("profile_status", sa.Text(), nullable=False, server_default="pending"))
    op.add_column("meeting_digestions", sa.Column("profile_artifact", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("meeting_digestions", sa.Column("profile_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("meeting_digestions", sa.Column("profile_next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.add_column("meeting_digestions", sa.Column("profile_error", sa.Text()))
    op.add_column("meeting_digestions", sa.Column("profile_updated_at", sa.DateTime(timezone=True)))
    op.create_check_constraint("meeting_profile_payload", "meeting_digestions",
                               "profile_status IN ('pending', 'done', 'failed') AND profile_attempts >= 0 AND jsonb_typeof(profile_artifact) = 'object'")
    op.create_table(
        "participant_profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("identity_key", sa.Text(), nullable=False, unique=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text()),
        sa.Column("identity_scope", sa.Text(), nullable=False),
        sa.Column("claims", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("identity_scope IN ('email', 'meeting')", name="participant_profile_scope"),
        sa.CheckConstraint("revision > 0 AND jsonb_typeof(claims) = 'array'", name="participant_profile_payload"),
    )


def downgrade() -> None:
    op.drop_table("participant_profiles")
    op.drop_constraint("meeting_profile_payload", "meeting_digestions", type_="check")
    for column in ("profile_updated_at", "profile_error", "profile_next_attempt_at", "profile_attempts", "profile_artifact", "profile_status"):
        op.drop_column("meeting_digestions", column)
