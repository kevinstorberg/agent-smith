from __future__ import annotations

from datetime import datetime

from psycopg2.extras import RealDictCursor

from services.api.models.shared.harness import (
    HarnessWriteConflict, _LATEST_VERSION_CLAUSE, _table, harness_write,
)


def _positive_id(value: int) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError("Move IDs must be positive integers")


def _timestamp(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Move timestamps must include a timezone")


def _latest_order(cursor, table: str) -> list[dict]:
    latest = _LATEST_VERSION_CLAUSE.format(table=table)
    cursor.execute(f"SELECT id, sort_key, updated_at FROM {table} WHERE {latest} ORDER BY sort_key, id")
    return list(cursor.fetchall())


def move_item(
    item_type: str, item_id: int, *, expected_updated_at: datetime,
    expected_anchor_updated_at: datetime, before_id: int | None = None, after_id: int | None = None,
) -> dict:
    table = _table(item_type)
    _positive_id(item_id)
    if (before_id is None) == (after_id is None):
        raise ValueError("Provide exactly one before_id or after_id")
    anchor_id = before_id if before_id is not None else after_id
    _positive_id(anchor_id)
    if item_id == anchor_id:
        raise ValueError("The move anchor must be a different item")
    _timestamp(expected_updated_at)
    _timestamp(expected_anchor_updated_at)

    with harness_write(item_type) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        latest = _latest_order(cur, table)
        original = [row["id"] for row in latest]
        if item_id not in original or anchor_id not in original:
            raise HarnessWriteConflict("The source or anchor is no longer a latest item. Refresh before moving again.")
        cur.execute(f"SELECT id, updated_at FROM {table} WHERE id = ANY(%s) ORDER BY id FOR UPDATE", ([item_id, anchor_id],))
        locked = {row["id"]: row["updated_at"] for row in cur.fetchall()}
        if locked.get(item_id) != expected_updated_at or locked.get(anchor_id) != expected_anchor_updated_at:
            raise HarnessWriteConflict("The source or anchor changed. Refresh before moving again.")

        reordered = [value for value in original if value != item_id]
        target = reordered.index(anchor_id) + (after_id is not None)
        reordered.insert(target, item_id)
        if len(reordered) != len(original) or set(reordered) != set(original):
            raise RuntimeError("Harness move changed queue membership")
        if [value for value in reordered if value != item_id] != [value for value in original if value != item_id]:
            raise RuntimeError("Harness move changed an unmoved item's relative order")

        if reordered != original:
            positions = {row["id"]: row["sort_key"] for row in latest}
            changed = [(value, index) for index, value in enumerate(reordered) if positions[value] != index]
            cur.execute(
                f"""UPDATE {table} AS item SET sort_key = position.sort_key, updated_at = clock_timestamp()
                FROM unnest(%s::int[], %s::int[]) AS position(id, sort_key)
                WHERE item.id = position.id""",
                ([value for value, _ in changed], [position for _, position in changed]),
            )
            if cur.rowcount != len(changed):
                raise RuntimeError("Harness move did not update every changed position")
            if [row["id"] for row in _latest_order(cur, table)] != reordered:
                raise RuntimeError("Harness move did not preserve the requested complete order")
        cur.execute(f"SELECT id, sort_key, updated_at FROM {table} WHERE id = %s", (item_id,))
        moved = dict(cur.fetchone())
        moved["updated_at"] = moved["updated_at"].isoformat()
        return moved
