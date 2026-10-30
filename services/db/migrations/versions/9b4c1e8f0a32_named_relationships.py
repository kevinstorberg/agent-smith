"""Keep named relationships without manufacturing participant profiles."""
from alembic import op
import sqlalchemy as sa

revision = "9b4c1e8f0a32"
down_revision = "8a3b0d7e9f21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("profile_relationships", sa.Column("target_name", sa.Text(), nullable=False, server_default=""))
    op.alter_column("profile_relationships", "target_id", nullable=True)
    op.create_check_constraint("relationship_target_name", "profile_relationships",
                               "length(target_name)<=200 AND (target_id IS NOT NULL OR length(btrim(target_name))>0)")
    op.create_index("relationship_named_target", "profile_relationships", ["subject_id", sa.text("lower(target_name)")],
                    unique=True, postgresql_where=sa.text("target_id IS NULL AND NOT dismissed"))


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM profile_relationships WHERE target_id IS NULL)")).scalar():
        raise RuntimeError("Cannot downgrade while named relationships without profiles exist")
    op.drop_index("relationship_named_target", table_name="profile_relationships")
    op.drop_constraint("relationship_target_name", "profile_relationships", type_="check")
    op.alter_column("profile_relationships", "target_id", nullable=False)
    op.drop_column("profile_relationships", "target_name")
