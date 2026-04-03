from __future__ import annotations

from psycopg2.extras import RealDictCursor

from services.db import get_connection
from services.api.models.base import BaseModel
from services.api.models.shared.harness import _table, _sort_optional_list, _row_to_dict


class ConfigModel(BaseModel):
    table = "harness_configs"

    @classmethod
    def create(cls, item_id, item_type, device="*", repo="*", agents=None, subagents=None, enabled=True, exclude=False):
        cls._validate_id(item_id)
        _table(item_type)
        return super().create(
            item_id=item_id, item_type=item_type, device=device, repo=repo,
            agents=_sort_optional_list(agents) or [], subagents=_sort_optional_list(subagents) or [],
            enabled=enabled, exclude=exclude,
        )

    @classmethod
    def update(cls, config_id, **fields):
        for col in ("agents", "subagents"):
            if col in fields:
                fields[col] = _sort_optional_list(fields[col])
        cls.dynamic_update(config_id, fields)

    @classmethod
    def list_for_item(cls, item_id, item_type):
        cls._validate_id(item_id)
        _table(item_type)
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"SELECT * FROM {cls.table} WHERE item_id = %s AND item_type = %s ORDER BY id",
                    (item_id, item_type),
                )
                return [_row_to_dict(r) for r in cur.fetchall()]

    @classmethod
    def batch_list(cls, item_ids, item_type):
        if not item_ids:
            return {}
        _table(item_type)
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"SELECT * FROM {cls.table} WHERE item_id = ANY(%s) AND item_type = %s ORDER BY id",
                    (item_ids, item_type),
                )
                result: dict[int, list[dict]] = {}
                for r in cur.fetchall():
                    result.setdefault(r["item_id"], []).append(_row_to_dict(r))
                return result


# Backward compat aliases
list_configs = ConfigModel.list_for_item
batch_list_configs = ConfigModel.batch_list
create_config = ConfigModel.create
update_config = ConfigModel.update
delete_config = ConfigModel.destroy
