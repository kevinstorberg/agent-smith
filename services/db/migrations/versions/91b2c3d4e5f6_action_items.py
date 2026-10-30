"""Add an independent shared action-item queue."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "91b2c3d4e5f6"
down_revision = "9b4c1e8f0a32"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("action_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("project", sa.Text),
        sa.Column("tags", sa.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("status", sa.Text, nullable=False, server_default="open"),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("sort_key", sa.Integer),
        sa.Column("revision", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("request_id", UUID, unique=True),
        sa.Column("create_payload", JSONB),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("char_length(title) BETWEEN 1 AND 200 AND title ~ '[^[:space:]]'", name="action_item_title"),
        sa.CheckConstraint("char_length(description)<=100000", name="action_item_description"),
        sa.CheckConstraint("project IS NULL OR char_length(project) BETWEEN 1 AND 200", name="action_item_project"),
        sa.CheckConstraint("cardinality(tags)<=20", name="action_item_tags"),
        sa.CheckConstraint("status IN ('open','completed') AND (status='completed')=(completed_at IS NOT NULL)", name="action_item_status"),
        sa.CheckConstraint("revision>0", name="action_item_revision"),
        sa.CheckConstraint("CASE WHEN deleted_at IS NULL AND status='open' THEN sort_key>0 AND sort_key IS NOT NULL ELSE sort_key IS NULL END", name="action_item_position"),
        sa.CheckConstraint("(request_id IS NULL AND create_payload IS NULL) OR (request_id IS NOT NULL AND create_payload IS NOT NULL AND jsonb_typeof(create_payload)='object')", name="action_item_request"),
        sa.UniqueConstraint("sort_key", name="action_item_order_unique", deferrable=True, initially="DEFERRED"))


def downgrade() -> None:
    op.drop_table("action_items")
