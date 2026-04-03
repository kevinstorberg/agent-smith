from __future__ import annotations

from scripts.shared.validation import assert_not_empty
from services.db import get_connection


class SortableMixin:
    """Mixin for models with integer sort_key ordering.

    Requires: cls.table
    """

    @classmethod
    def reorder(cls, ids: list[int]) -> None:
        assert_not_empty(ids, "ids")

        with get_connection() as conn:
            with conn.cursor() as cur:
                for i, item_id in enumerate(ids):
                    cur.execute(
                        f"UPDATE {cls.table} SET sort_key = %s, updated_at = now() WHERE id = %s",
                        (i, item_id),
                    )
