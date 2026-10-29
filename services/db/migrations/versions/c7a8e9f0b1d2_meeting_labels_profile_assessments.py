"""Keep meeting topics and evolving profile assessments with revision history."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision = "c7a8e9f0b1d2"
down_revision = "9d2f6a8c1b40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("meeting_summaries", sa.Column("labels", ARRAY(sa.Text()), nullable=False,
                                                server_default=sa.text("'{}'::text[]")))
    op.add_column("meeting_summaries", sa.Column("labels_revision", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("meeting_summaries", sa.Column("labels_source", sa.Text()))
    op.create_check_constraint("meeting_labels_state", "meeting_summaries",
                               "labels_revision >= 0 AND (labels_source IS NULL OR labels_source IN ('human', 'agent'))")
    op.add_column("participant_profiles", sa.Column("section_evidence", JSONB, nullable=False,
                                                   server_default=sa.text("'{}'::jsonb")))
    op.add_column("participant_profiles", sa.Column("assessment_dirty", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("participant_profiles", sa.Column("assessment_input_hash", sa.Text()))
    op.add_column("participant_profiles", sa.Column("assessment_claim_owner", sa.Text()))
    op.add_column("participant_profiles", sa.Column("assessment_claim_until", sa.DateTime(timezone=True)))
    op.add_column("participant_profiles", sa.Column("assessment_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("participant_profiles", sa.Column("assessment_next_attempt_at", sa.DateTime(timezone=True), nullable=False,
                                                   server_default=sa.func.now()))
    op.add_column("participant_profiles", sa.Column("assessment_error", sa.Text()))
    op.create_check_constraint("profile_assessment_state", "participant_profiles",
                               "jsonb_typeof(section_evidence) = 'object' AND assessment_attempts >= 0 "
                               "AND ((assessment_claim_owner IS NULL) = (assessment_claim_until IS NULL))")
    op.create_index("profile_assessment_pending", "participant_profiles", ["assessment_next_attempt_at", "id"],
                    postgresql_where=sa.text("assessment_dirty AND NOT deleted AND merged_into IS NULL"))
    op.execute("""UPDATE participant_profiles p SET section_evidence =
        (SELECT coalesce(jsonb_object_agg(field, jsonb_build_object('human', true)), '{}'::jsonb)
         FROM jsonb_object_keys(p.section_notes) field)""")
    op.create_table(
        "profile_revisions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("profile_id", UUID(as_uuid=True), sa.ForeignKey("participant_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("base_revision", sa.Integer(), nullable=False),
        sa.Column("new_revision", sa.Integer(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text()),
        sa.Column("input_hash", sa.Text()),
        sa.Column("changes", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("base_revision >= 0 AND new_revision > base_revision", name="profile_revision_versions"),
        sa.CheckConstraint("actor IN ('agent', 'human', 'system')", name="profile_revision_actor"),
        sa.CheckConstraint("source IN ('meeting', 'assessment', 'manual', 'merge')", name="profile_revision_source"),
        sa.CheckConstraint("jsonb_typeof(changes) = 'object'", name="profile_revision_changes"),
    )
    op.create_index("profile_revisions_profile_id", "profile_revisions", ["profile_id", sa.text("id DESC")])


def _without_generated_sections(snapshot: dict) -> dict:
    proofs = snapshot.get("section_evidence", {})
    generated = {field for field, proof in proofs.items() if proof.get("human") is not True}
    cleaned = dict(snapshot)
    if "section_notes" in snapshot:
        cleaned["section_notes"] = {field: value for field, value in snapshot["section_notes"].items() if field not in generated}
    if "section_evidence" in snapshot:
        cleaned["section_evidence"] = {field: proof for field, proof in proofs.items() if field not in generated}
    if "merge_history" in snapshot:
        cleaned["merge_history"] = [
            {**entry, **{key: _without_generated_sections(entry[key]) for key in ("previous_source", "previous_target")
                         if isinstance(entry.get(key), dict)}} for entry in snapshot["merge_history"]
        ]
    return cleaned


def downgrade() -> None:
    profiles = sa.table("participant_profiles", sa.column("id", UUID), sa.column("section_notes", JSONB),
                        sa.column("section_evidence", JSONB), sa.column("merge_history", JSONB))
    connection = op.get_bind()
    # Older readers treat every section as human text and cannot enforce source withdrawal.
    with connection.execute(sa.select(profiles).execution_options(yield_per=100)) as rows:
        for row in rows.mappings():
            cleaned = _without_generated_sections(dict(row))
            if cleaned["section_notes"] != row["section_notes"] or cleaned["merge_history"] != row["merge_history"]:
                connection.execute(profiles.update().where(profiles.c.id == row["id"]).values(
                    section_notes=cleaned["section_notes"], merge_history=cleaned["merge_history"]))
    op.drop_table("profile_revisions")
    op.drop_index("profile_assessment_pending", table_name="participant_profiles")
    op.drop_constraint("profile_assessment_state", "participant_profiles", type_="check")
    for column in ("assessment_error", "assessment_next_attempt_at", "assessment_attempts", "assessment_claim_until",
                   "assessment_claim_owner", "assessment_input_hash", "assessment_dirty", "section_evidence"):
        op.drop_column("participant_profiles", column)
    op.drop_constraint("meeting_labels_state", "meeting_summaries", type_="check")
    for column in ("labels_source", "labels_revision", "labels"):
        op.drop_column("meeting_summaries", column)
