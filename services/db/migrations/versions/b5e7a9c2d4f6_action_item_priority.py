"""Persist global task Priority without changing queue order."""

from alembic import op
import sqlalchemy as sa

revision = "b5e7a9c2d4f6"
down_revision = "a4b6c8d0e2f1"
branch_labels = None
depends_on = None


def _columns(connection) -> list[str]:
    return list(
        connection.exec_driver_sql(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema=current_schema() AND table_name='action_item_ordered_items' "
            "ORDER BY ordinal_position"
        ).scalars()
    )


def _view(connection, columns: list[str], *, replace: bool) -> None:
    quote = connection.dialect.identifier_preparer.quote
    fields = [
        "CASE WHEN item.profile_id IS NOT NULL THEN item.sort_key "
        "WHEN item.deleted_at IS NULL AND item.status='open' THEN "
        "row_number() OVER(PARTITION BY item.profile_id,(item.deleted_at IS NULL AND item.status='open') "
        "ORDER BY coalesce(parent.sort_key,child.sort_key),child.sort_key,item.id)::integer "
        "ELSE NULL END AS queue_priority"
        if name == "queue_priority"
        else f"item.{quote(name)}"
        for name in columns
    ]
    connection.exec_driver_sql(
        f"CREATE {'OR REPLACE ' if replace else ''}VIEW action_item_ordered_items AS SELECT {','.join(fields)} "
        "FROM action_items item "
        "LEFT JOIN action_item_queue_entries child ON child.action_item_id=item.id "
        "LEFT JOIN action_item_queue_entries parent ON parent.epic_id=child.parent_epic_id"
    )


def upgrade() -> None:
    connection = op.get_bind()
    columns = _columns(connection)
    if not columns or columns[-1] != "queue_priority" or "is_priority" in columns:
        raise RuntimeError(
            "Priority migration requires the existing ordered task view with queue_priority last"
        )
    op.add_column(
        "action_items",
        sa.Column(
            "is_priority", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.create_check_constraint(
        "action_item_priority_global",
        "action_items",
        "profile_id IS NULL OR NOT is_priority",
    )
    # PostgreSQL replaces views only when all existing column positions stay intact.
    _view(connection, [*columns, "is_priority"], replace=True)


def downgrade() -> None:
    connection = op.get_bind()
    columns = _columns(connection)
    if not columns or columns[-1] != "is_priority":
        raise RuntimeError(
            "Priority downgrade requires is_priority at the end of the ordered task view"
        )
    connection.exec_driver_sql("DROP VIEW action_item_global_positions")
    connection.exec_driver_sql("DROP VIEW action_item_ordered_items")
    op.drop_constraint("action_item_priority_global", "action_items", type_="check")
    op.drop_column("action_items", "is_priority")
    _view(connection, columns[:-1], replace=False)
    connection.exec_driver_sql(
        "CREATE VIEW action_item_global_positions AS "
        "SELECT id AS action_item_id,queue_priority AS priority FROM action_item_ordered_items "
        "WHERE profile_id IS NULL AND queue_priority IS NOT NULL"
    )
