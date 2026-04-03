from __future__ import annotations

from psycopg2.extras import RealDictCursor

from scripts.shared.validation import assert_not_empty
from services.db import get_connection
from services.api.models.base import BaseModel


class SuiteModel(BaseModel):
    table = "eval_suites"
    json_fields = {"items", "config"}

    @classmethod
    def create(cls, name, eval_type, subcategory, judge_prompt, items=None, config=None, enabled=True):
        cls._validate_required(
            {"name": name, "eval_type": eval_type, "subcategory": subcategory, "judge_prompt": judge_prompt},
            ["name", "eval_type", "subcategory", "judge_prompt"],
        )
        return super().create(
            name=name, eval_type=eval_type, subcategory=subcategory,
            judge_prompt=judge_prompt, items=items or {}, config=config or {},
            enabled=enabled,
        )

    @classmethod
    def update(cls, suite_id, *, name=None, eval_type=None, subcategory=None,
               judge_prompt=None, items=None, config=None, enabled=None):
        fields = cls._collect_fields(
            name=name, eval_type=eval_type, subcategory=subcategory,
            judge_prompt=judge_prompt, items=items, config=config, enabled=enabled,
        )
        if fields:
            cls.dynamic_update(suite_id, fields)

    @classmethod
    def list(cls, enabled_only=True, limit=50, offset=0):
        where = "WHERE enabled = true" if enabled_only else ""
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(f"SELECT count(*) as cnt FROM {cls.table} {where}")
                total = cur.fetchone()["cnt"]
                cur.execute(
                    f"SELECT s.id, s.name, s.eval_type, s.subcategory, s.enabled, "
                    f"s.created_at, s.updated_at, "
                    f"(SELECT COUNT(*) FROM eval_scenarios WHERE suite_id = s.id) AS scenario_count "
                    f"FROM {cls.table} s {where} "
                    f"ORDER BY s.name LIMIT %s OFFSET %s",
                    (limit, offset),
                )
                items = [cls.serialize_timestamps(r) for r in cur.fetchall()]
        return items, total

    @classmethod
    def get_by_name(cls, name):
        assert_not_empty(name, "name")
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(f"SELECT * FROM {cls.table} WHERE name = %s", (name,))
                row = cur.fetchone()
                return cls.serialize_timestamps(row) if row else None

    @classmethod
    def upsert(cls, name, eval_type, subcategory, judge_prompt, items=None, config=None, enabled=True):
        existing = cls.get_by_name(name)
        if existing:
            cls.update(
                existing["id"], eval_type=eval_type, subcategory=subcategory,
                judge_prompt=judge_prompt, items=items or {}, config=config or {}, enabled=enabled,
            )
            return existing["id"]
        return cls.create(name, eval_type, subcategory, judge_prompt, items, config, enabled)


class ScenarioModel(BaseModel):
    table = "eval_scenarios"

    @classmethod
    def create(cls, suite_id, name, prompt, enabled=True):
        cls._validate_id(suite_id)
        cls._validate_required({"name": name, "prompt": prompt}, ["name", "prompt"])
        return super().create(suite_id=suite_id, name=name, prompt=prompt, enabled=enabled)

    @classmethod
    def update(cls, scenario_id, *, name=None, prompt=None, enabled=None):
        fields = cls._collect_fields(name=name, prompt=prompt, enabled=enabled)
        if fields:
            cls.dynamic_update(scenario_id, fields)

    @classmethod
    def list_for_suite(cls, suite_id, enabled_only=True):
        cls._validate_id(suite_id)
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                where = "WHERE suite_id = %s"
                if enabled_only:
                    where += " AND enabled = true"
                cur.execute(
                    f"SELECT * FROM {cls.table} {where} ORDER BY sort_key, name",
                    (suite_id,),
                )
                return [cls.serialize_timestamps(r) for r in cur.fetchall()]

    @classmethod
    def upsert(cls, suite_id, name, prompt, enabled=True):
        cls._validate_id(suite_id)
        assert_not_empty(name, "name")
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"SELECT id FROM {cls.table} WHERE suite_id = %s AND name = %s",
                    (suite_id, name),
                )
                row = cur.fetchone()
        if row:
            cls.update(row["id"], prompt=prompt, enabled=enabled)
            return row["id"]
        return cls.create(suite_id, name, prompt, enabled)


# Backward compat aliases
list_suites = SuiteModel.list
get_suite = SuiteModel.read
get_suite_by_name = SuiteModel.get_by_name
create_suite = SuiteModel.create
update_suite = SuiteModel.update
delete_suite = SuiteModel.destroy
upsert_suite = SuiteModel.upsert

list_scenarios = ScenarioModel.list_for_suite
get_scenario = ScenarioModel.read
create_scenario = ScenarioModel.create
update_scenario = ScenarioModel.update
delete_scenario = ScenarioModel.destroy
upsert_scenario = ScenarioModel.upsert


def list_enabled_scenarios_for_suite(suite_name: str) -> list[dict]:
    assert_not_empty(suite_name, "suite_name")
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    s.id, s.suite_id, s.name, s.prompt, s.enabled,
                    su.judge_prompt, su.items, su.config,
                    su.eval_type, su.subcategory,
                    su.id AS suite_id
                FROM eval_scenarios s
                JOIN eval_suites su ON su.id = s.suite_id
                WHERE su.name = %s
                  AND su.enabled = true
                  AND s.enabled = true
                ORDER BY s.sort_key, s.name
                """,
                (suite_name,),
            )
            return [dict(r) for r in cur.fetchall()]


def resolve_items(items: dict) -> list[tuple[str, str]]:
    source = items.get("source")
    assert source, "items must have a 'source' key."

    if source == "harness":
        from services.api.models.rule import collect_rules_from_db
        harness_type = items.get("harness_type", "rule")
        agent = items.get("agent", "claude")
        exclude = set(items.get("exclude", []))

        if harness_type == "rule":
            all_items = collect_rules_from_db(agent)
        else:
            raise ValueError(f"Unsupported harness_type: {harness_type}")

        return [(name, body) for name, body in all_items if name not in exclude]

    if source == "skill":
        from services.api.models.skill import get_skill
        skill_name = items.get("skill_name")
        assert skill_name, "skill source requires 'skill_name'."
        skill = get_skill(skill_name)
        assert skill, f"Skill not found in harness DB: {skill_name}"
        return [(skill_name, skill["content"]["body"])]

    raise ValueError(f"Unknown items source: {source}")


def resolve_extra_context(items: dict) -> str | None:
    source = items.get("source")
    if source == "skill":
        from services.api.models.skill import get_skill
        skill_name = items.get("skill_name")
        assert skill_name, "skill source requires 'skill_name'."
        skill = get_skill(skill_name)
        assert skill, f"Skill not found in harness DB: {skill_name}"
        return skill["content"]["body"]
    return None
