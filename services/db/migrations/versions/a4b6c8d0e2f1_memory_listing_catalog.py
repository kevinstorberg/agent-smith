"""Index memory listing metadata without copying content or embeddings."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision = "a4b6c8d0e2f1"
down_revision = "f7a2d8c4b9e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_catalog_sources",
        sa.Column("source_key", sa.Text(), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="empty"),
        sa.Column("generation", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "active_version", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("build_version", sa.BigInteger()),
        sa.Column("build_token", UUID(as_uuid=True)),
        sa.Column("build_expected_count", sa.BigInteger()),
        sa.Column("initialized_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('empty','building','ready','failed') AND generation>=0 AND active_version>=0",
            name="memory_catalog_source_state",
        ),
    )
    op.create_table(
        "memory_catalog_entries",
        sa.Column(
            "source_key",
            sa.Text(),
            sa.ForeignKey("memory_catalog_sources.source_key", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "catalog_version", sa.BigInteger(), primary_key=True, server_default="0"
        ),
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("repo", sa.Text()),
        sa.Column(
            "tags",
            ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("source_type", sa.Text()),
        sa.Column("source_id", sa.Text()),
        sa.Column("meeting_id", UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    for field in ("created_at", "updated_at"):
        op.create_index(
            f"memory_catalog_{field}",
            "memory_catalog_entries",
            ["source_key", "catalog_version", field, "id"],
        )
    op.create_index(
        "memory_catalog_repo",
        "memory_catalog_entries",
        ["source_key", "catalog_version", "repo"],
    )
    op.create_table(
        "memory_catalog_pending",
        sa.Column(
            "source_key",
            sa.Text(),
            sa.ForeignKey("memory_catalog_sources.source_key", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("operation_token", UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("phase", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("projection", JSONB()),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.CheckConstraint(
            "kind IN ('upsert','delete') AND phase IN ('pending','acknowledged')",
            name="memory_catalog_pending_state",
        ),
    )


def downgrade() -> None:
    op.drop_table("memory_catalog_pending")
    op.drop_table("memory_catalog_entries")
    op.drop_table("memory_catalog_sources")
