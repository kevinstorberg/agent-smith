"""Scope ordered action items to the global queue or a participant profile."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "d4a7e2c9f6b1"
down_revision = "b6e2d9f4a1c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("action_items", sa.Column("profile_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("action_item_profile_fk", "action_items", "participant_profiles", ["profile_id"], ["id"], ondelete="RESTRICT")
    op.add_column("action_items", sa.Column("scope_key", sa.Text(), sa.Computed("coalesce(profile_id::text, 'global')", persisted=True), nullable=False))
    op.drop_constraint("action_item_order_unique", "action_items", type_="unique")
    op.create_unique_constraint("action_item_order_unique", "action_items", ["scope_key", "sort_key"], deferrable=True, initially="DEFERRED")


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql("LOCK TABLE action_items IN ACCESS EXCLUSIVE MODE")
    if connection.exec_driver_sql("SELECT EXISTS(SELECT 1 FROM action_items WHERE profile_id IS NOT NULL)").scalar():
        raise RuntimeError("Cannot remove discussion-topic ownership while profile-owned action items exist")
    op.drop_constraint("action_item_order_unique", "action_items", type_="unique")
    op.create_unique_constraint("action_item_order_unique", "action_items", ["sort_key"], deferrable=True, initially="DEFERRED")
    op.drop_column("action_items", "scope_key")
    op.drop_constraint("action_item_profile_fk", "action_items", type_="foreignkey")
    op.drop_column("action_items", "profile_id")
