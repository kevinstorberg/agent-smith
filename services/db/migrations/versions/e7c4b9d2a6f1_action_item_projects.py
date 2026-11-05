"""Give action item projects stable identities without duplicating their names."""

from alembic import op
import sqlalchemy as sa

revision = "e7c4b9d2a6f1"
down_revision = "d4a7e2c9f6b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "action_item_projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(collation="C"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("name", name="action_item_project_name_unique"),
    )
    op.add_column("action_items", sa.Column("project_id", sa.Integer(), nullable=True))
    connection = op.get_bind()
    connection.exec_driver_sql("""INSERT INTO action_item_projects(name)
        SELECT DISTINCT project COLLATE "C" AS name FROM action_items
        WHERE project IS NOT NULL ORDER BY name""")
    connection.exec_driver_sql('''UPDATE action_items a SET project_id=p.id
        FROM action_item_projects p WHERE p.name=a.project COLLATE "C"''')
    invalid = connection.exec_driver_sql("""SELECT EXISTS(
        SELECT 1 FROM action_items a LEFT JOIN action_item_projects p ON p.id=a.project_id
        WHERE (a.project IS NULL)<>(a.project_id IS NULL)
        OR p.name IS DISTINCT FROM a.project COLLATE "C")""").scalar()
    if invalid:
        raise RuntimeError(
            "Project migration could not preserve every exact legacy assignment"
        )
    op.create_foreign_key(
        "action_item_project_fk",
        "action_items",
        "action_item_projects",
        ["project_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("action_item_project_id", "action_items", ["project_id"])
    op.drop_column("action_items", "project")


def downgrade() -> None:
    op.add_column("action_items", sa.Column("project", sa.Text(), nullable=True))
    connection = op.get_bind()
    connection.exec_driver_sql("""UPDATE action_items a SET project=p.name
        FROM action_item_projects p WHERE p.id=a.project_id""")
    missing = connection.exec_driver_sql(
        "SELECT EXISTS(SELECT 1 FROM action_items WHERE project_id IS NOT NULL AND project IS NULL)"
    ).scalar()
    if missing:
        raise RuntimeError(
            "Project downgrade could not restore every legacy assignment"
        )
    op.create_check_constraint(
        "action_item_project",
        "action_items",
        "project IS NULL OR char_length(project) BETWEEN 1 AND 200",
    )
    op.drop_index("action_item_project_id", table_name="action_items")
    op.drop_constraint("action_item_project_fk", "action_items", type_="foreignkey")
    op.drop_column("action_items", "project_id")
    op.drop_table("action_item_projects")
