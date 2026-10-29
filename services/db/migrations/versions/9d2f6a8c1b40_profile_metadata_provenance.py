"""Record per-field profile metadata ownership and source evidence."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "9d2f6a8c1b40"
down_revision = "f8a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("participant_profiles", sa.Column("metadata_provenance", JSONB, nullable=False,
                                                  server_default=sa.text("'{}'::jsonb")))
    op.create_check_constraint("profile_metadata_provenance_object", "participant_profiles",
                               "jsonb_typeof(metadata_provenance) = 'object'")
    op.execute("""UPDATE participant_profiles p SET metadata_provenance =
        (SELECT coalesce(jsonb_object_agg(field, jsonb_build_object('human', true)), '{}'::jsonb)
         FROM jsonb_object_keys(p.metadata) field)""")


def _without_generated_metadata(snapshot: dict) -> dict:
    provenance = snapshot.get("metadata_provenance", {})
    generated = {field for field, source in provenance.items() if source.get("human") is not True}
    result = {**snapshot, "metadata": {field: value for field, value in snapshot.get("metadata", {}).items() if field not in generated}}
    if "metadata_provenance" in snapshot:
        result["metadata_provenance"] = {field: source for field, source in provenance.items() if field not in generated}
    if "merge_history" in snapshot:
        result["merge_history"] = [
            {**entry, **{key: _without_generated_metadata(entry[key]) for key in ("previous_source", "previous_target")
                         if isinstance(entry.get(key), dict)}} for entry in snapshot["merge_history"]
        ]
    return result


def downgrade() -> None:
    profiles = sa.table("participant_profiles", sa.column("id", UUID), sa.column("metadata", JSONB),
                        sa.column("metadata_provenance", JSONB), sa.column("merge_history", JSONB))
    connection = op.get_bind()
    # Older readers cannot distinguish generated values from human edits.
    with connection.execute(sa.select(profiles).execution_options(yield_per=100)) as rows:
        for row in rows.mappings():
            cleaned = _without_generated_metadata(dict(row))
            if cleaned["metadata"] != row["metadata"] or cleaned["merge_history"] != row["merge_history"]:
                connection.execute(profiles.update().where(profiles.c.id == row["id"]).values(
                    metadata=cleaned["metadata"], merge_history=cleaned["merge_history"]))
    op.drop_constraint("profile_metadata_provenance_object", "participant_profiles", type_="check")
    op.drop_column("participant_profiles", "metadata_provenance")
