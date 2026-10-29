"""Separate persona leases and add editable profile context and relationships."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "f8a0b1c2d3e4"
down_revision = "e7f8a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("memories", sa.Column("source_type", sa.Text()))
    op.add_column("memories", sa.Column("source_id", sa.Text()))
    op.add_column("meeting_digestions", sa.Column("profile_claim_owner", sa.Text()))
    op.add_column("meeting_digestions", sa.Column("profile_claim_until", sa.DateTime(timezone=True)))
    op.add_column("participant_profiles", sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("participant_profiles", sa.Column("section_notes", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("participant_profiles", sa.Column("nicknames", sa.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'::text[]")))
    op.create_check_constraint("profile_context_objects", "participant_profiles", "jsonb_typeof(metadata) = 'object' AND jsonb_typeof(section_notes) = 'object'")
    op.create_table(
        "profile_relationships",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("subject_id", UUID(as_uuid=True), sa.ForeignKey("participant_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_id", UUID(as_uuid=True), sa.ForeignKey("participant_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.Text(), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("dismissed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("human_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("history", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("subject_id", "target_id", name="profile_relationship_pair"),
        sa.CheckConstraint("subject_id <> target_id", name="profile_relationship_distinct_people"),
        sa.CheckConstraint("revision >= 1 AND jsonb_typeof(history) = 'array'", name="profile_relationship_payload"),
    )
    op.create_index("profile_relationship_target", "profile_relationships", ["target_id"])
    op.execute("""INSERT INTO profile_relationships (subject_id, target_id)
        SELECT DISTINCT p.id, coalesce(target.merged_into, target.id)
        FROM participant_profiles p
        CROSS JOIN LATERAL jsonb_array_elements(p.claims) claim
        JOIN participant_profiles target ON target.id = (claim->>'target_id')::uuid
        WHERE NOT p.deleted AND p.merged_into IS NULL AND NOT target.deleted
          AND claim->>'category' IN ('perception', 'interaction')
          AND p.id <> coalesce(target.merged_into, target.id)
        ON CONFLICT (subject_id, target_id) DO NOTHING""")
    op.create_table(
        "meeting_vocabulary",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("term", sa.Text(), nullable=False),
        sa.Column("normalized_term", sa.Text(), nullable=False, unique=True),
        sa.Column("definition", sa.Text(), nullable=False, server_default=""),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("revision >= 1 AND length(btrim(term)) > 0", name="meeting_vocabulary_payload"),
    )


def downgrade() -> None:
    op.drop_table("meeting_vocabulary")
    op.drop_table("profile_relationships")
    op.drop_constraint("profile_context_objects", "participant_profiles", type_="check")
    for column in ("nicknames", "section_notes", "metadata"):
        op.drop_column("participant_profiles", column)
    op.drop_column("meeting_digestions", "profile_claim_until")
    op.drop_column("meeting_digestions", "profile_claim_owner")
    op.drop_column("memories", "source_id")
    op.drop_column("memories", "source_type")
