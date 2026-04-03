from __future__ import annotations

from psycopg2.extras import Json, RealDictCursor

from services.db import get_connection

TIMESTAMP_FIELDS = ("created_at", "updated_at", "timestamp")


class BaseModel:
    """ActiveRecord-style base. Subclasses set `table` and inherit full CRUD."""

    table: str
    json_fields: set[str] = set()

    @staticmethod
    def _validate_id(row_id: int) -> None:
        assert row_id > 0, "id must be positive."

    @staticmethod
    def _validate_required(fields: dict, required: list[str]) -> None:
        for field in required:
            assert fields.get(field), f"{field} must not be empty."

    @classmethod
    def serialize_timestamps(cls, row: dict) -> dict:
        result = dict(row)
        for field in TIMESTAMP_FIELDS:
            if result.get(field):
                result[field] = result[field].isoformat()
        return result

    @classmethod
    def create(cls, **fields) -> int:
        jf = cls.json_fields
        cols = list(fields.keys())
        vals = [Json(v) if c in jf else v for c, v in fields.items()]
        placeholders = ", ".join(["%s"] * len(cols))
        col_names = ", ".join(cols)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO {cls.table} ({col_names}) VALUES ({placeholders}) RETURNING id",
                    vals,
                )
                return cur.fetchone()[0]

    @classmethod
    def read(cls, row_id: int) -> dict | None:
        cls._validate_id(row_id)
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(f"SELECT * FROM {cls.table} WHERE id = %s", (row_id,))
                row = cur.fetchone()
                return cls.serialize_timestamps(dict(row)) if row else None

    @classmethod
    def update(cls, row_id: int, **fields) -> None:
        clean = cls._collect_fields(**fields)
        if clean:
            cls.dynamic_update(row_id, clean)

    @classmethod
    def destroy(cls, row_id: int) -> None:
        cls._validate_id(row_id)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM {cls.table} WHERE id = %s", (row_id,))

    @classmethod
    def list(
        cls,
        columns: str = "*",
        where: str = "",
        params: tuple = (),
        order_by: str = "updated_at DESC",
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(f"SELECT COUNT(*) as cnt FROM {cls.table} {where}", params)
                total = cur.fetchone()["cnt"]
                cur.execute(
                    f"SELECT {columns} FROM {cls.table} {where} ORDER BY {order_by} LIMIT %s OFFSET %s",
                    (*params, limit, offset),
                )
                items = [cls.serialize_timestamps(r) for r in cur.fetchall()]
        return items, total

    find_by_id = read
    delete_by_id = destroy

    @classmethod
    def dynamic_update(
        cls,
        row_id: int,
        fields: dict,
        json_fields: set[str] | None = None,
    ) -> None:
        cls._validate_id(row_id)
        jf = json_fields or cls.json_fields

        sets, params = [], []
        for col, val in fields.items():
            sets.append(f"{col} = %s")
            params.append(Json(val) if col in jf else val)

        assert sets, "At least one field must be provided."
        sets.append("updated_at = now()")
        params.append(row_id)

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE {cls.table} SET {', '.join(sets)} WHERE id = %s",
                    params,
                )

    @staticmethod
    def _collect_fields(**kwargs) -> dict:
        return {k: v for k, v in kwargs.items() if v is not None}

    @classmethod
    def count(cls, where: str = "", params: tuple = ()) -> int:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM {cls.table} {where}", params)
                return cur.fetchone()[0]
