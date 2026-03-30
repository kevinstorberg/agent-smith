from __future__ import annotations

from psycopg2.extras import Json, RealDictCursor

from services.db import get_connection

TIMESTAMP_FIELDS = ("created_at", "updated_at", "timestamp")


class BaseModel:
    """ActiveRecord-style base for all DB modules.

    Subclasses set `table` and inherit shared CRUD primitives.
    """

    table: str

    @classmethod
    def _validate_id(cls, row_id: int) -> None:
        assert row_id > 0, f"{cls.table} id must be positive."

    @classmethod
    def serialize_timestamps(cls, row: dict) -> dict:
        result = dict(row)
        for field in TIMESTAMP_FIELDS:
            if result.get(field):
                result[field] = result[field].isoformat()
        return result

    @classmethod
    def find_by_id(cls, row_id: int) -> dict | None:
        cls._validate_id(row_id)
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(f"SELECT * FROM {cls.table} WHERE id = %s", (row_id,))
                row = cur.fetchone()
                return cls.serialize_timestamps(dict(row)) if row else None

    @classmethod
    def delete_by_id(cls, row_id: int) -> None:
        cls._validate_id(row_id)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM {cls.table} WHERE id = %s", (row_id,))

    @classmethod
    def dynamic_update(
        cls,
        row_id: int,
        fields: dict,
        json_fields: set[str] | None = None,
    ) -> None:
        cls._validate_id(row_id)
        json_fields = json_fields or set()

        sets, params = [], []
        for col, val in fields.items():
            if val is None:
                continue
            sets.append(f"{col} = %s")
            params.append(Json(val) if col in json_fields else val)

        assert sets, "At least one field must be provided."
        sets.append("updated_at = now()")
        params.append(row_id)

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE {cls.table} SET {', '.join(sets)} WHERE id = %s",
                    params,
                )

    @classmethod
    def count(cls, where: str = "", params: tuple = ()) -> int:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM {cls.table} {where}", params)
                return cur.fetchone()[0]
