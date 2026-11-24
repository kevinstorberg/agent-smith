from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Siblings:
    table: str
    clause: str
    values: tuple

    def __post_init__(self) -> None:
        if (self.table, self.clause) not in {
            ("action_items", "scope_key=%s"),
            ("action_item_queue_entries", "sibling_scope=%s"),
        }:
            raise ValueError("Unknown internal ordering scope")

    def append_position(self, cursor) -> int:
        cursor.execute(
            f"SELECT COALESCE(MAX(sort_key),0)+1 AS position FROM {self.table} WHERE {self.clause}",
            self.values,
        )
        return cursor.fetchone()["position"]

    def compact(self, cursor, position: int) -> None:
        cursor.execute(
            f"UPDATE {self.table} SET sort_key=sort_key-1 WHERE {self.clause} AND sort_key>%s",
            (*self.values, position),
        )

    def move(self, cursor, entry_id: int, old: int, target: int) -> bool:
        if old == target:
            return False
        if target < old:
            expression, bounds = "sort_key+1", "sort_key>=%s AND sort_key<%s"
            limits = (target, old)
        else:
            expression, bounds = "sort_key-1", "sort_key>%s AND sort_key<=%s"
            limits = (old, target)
        cursor.execute(
            f"UPDATE {self.table} SET sort_key={expression} WHERE {self.clause} AND {bounds}",
            (*self.values, *limits),
        )
        cursor.execute(
            f"UPDATE {self.table} SET sort_key=%s WHERE id=%s", (target, entry_id)
        )
        return True
