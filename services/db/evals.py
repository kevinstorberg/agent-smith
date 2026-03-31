from __future__ import annotations

from psycopg2.extras import Json, RealDictCursor

from scripts.shared.validation import assert_not_empty
from services.db import get_connection
from services.db.base_model import BaseModel


class SuiteModel(BaseModel):
    table = "eval_suites"

    @classmethod
    def update(
        cls,
        suite_id: int,
        *,
        name: str | None = None,
        eval_type: str | None = None,
        subcategory: str | None = None,
        judge_prompt: str | None = None,
        items: dict | None = None,
        config: dict | None = None,
        enabled: bool | None = None,
    ) -> None:
        fields = {}
        if name is not None:
            fields["name"] = name
        if eval_type is not None:
            fields["eval_type"] = eval_type
        if subcategory is not None:
            fields["subcategory"] = subcategory
        if judge_prompt is not None:
            fields["judge_prompt"] = judge_prompt
        if items is not None:
            fields["items"] = items
        if config is not None:
            fields["config"] = config
        if enabled is not None:
            fields["enabled"] = enabled
        cls.dynamic_update(suite_id, fields, json_fields={"items", "config"})


class ScenarioModel(BaseModel):
    table = "eval_scenarios"

    @classmethod
    def update(
        cls,
        scenario_id: int,
        *,
        name: str | None = None,
        prompt: str | None = None,
        enabled: bool | None = None,
    ) -> None:
        fields = {}
        if name is not None:
            fields["name"] = name
        if prompt is not None:
            fields["prompt"] = prompt
        if enabled is not None:
            fields["enabled"] = enabled
        cls.dynamic_update(scenario_id, fields)


def list_suites(
    enabled_only: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            where = "WHERE enabled = true" if enabled_only else ""
            cur.execute(f"SELECT count(*) as cnt FROM eval_suites {where}")
            total = cur.fetchone()["cnt"]

            cur.execute(
                f"SELECT * FROM eval_suites {where} "
                f"ORDER BY name LIMIT %s OFFSET %s",
                (limit, offset),
            )
            items = [SuiteModel.serialize_timestamps(r) for r in cur.fetchall()]

    return items, total


def get_suite(suite_id: int) -> dict | None:
    return SuiteModel.find_by_id(suite_id)


def get_suite_by_name(name: str) -> dict | None:
    assert_not_empty(name, "name")
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM eval_suites WHERE name = %s", (name,))
            row = cur.fetchone()
            return SuiteModel.serialize_timestamps(row) if row else None


def create_suite(
    name: str,
    eval_type: str,
    subcategory: str,
    judge_prompt: str,
    items: dict | None = None,
    config: dict | None = None,
    enabled: bool = True,
) -> int:
    assert_not_empty(name, "name")
    assert_not_empty(eval_type, "eval_type")
    assert_not_empty(subcategory, "subcategory")
    assert_not_empty(judge_prompt, "judge_prompt")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO eval_suites
                    (name, eval_type, subcategory, judge_prompt, items, config, enabled)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (name, eval_type, subcategory, judge_prompt,
                 Json(items or {}), Json(config or {}), enabled),
            )
            return cur.fetchone()[0]


def update_suite(
    suite_id: int,
    *,
    name: str | None = None,
    eval_type: str | None = None,
    subcategory: str | None = None,
    judge_prompt: str | None = None,
    items: dict | None = None,
    config: dict | None = None,
    enabled: bool | None = None,
) -> None:
    SuiteModel.update(
        suite_id,
        name=name, eval_type=eval_type, subcategory=subcategory,
        judge_prompt=judge_prompt, items=items, config=config, enabled=enabled,
    )


def delete_suite(suite_id: int) -> None:
    SuiteModel.delete_by_id(suite_id)


def upsert_suite(
    name: str,
    eval_type: str,
    subcategory: str,
    judge_prompt: str,
    items: dict | None = None,
    config: dict | None = None,
    enabled: bool = True,
) -> int:
    existing = get_suite_by_name(name)
    if existing:
        update_suite(
            existing["id"],
            eval_type=eval_type,
            subcategory=subcategory,
            judge_prompt=judge_prompt,
            items=items or {},
            config=config or {},
            enabled=enabled,
        )
        return existing["id"]
    return create_suite(name, eval_type, subcategory, judge_prompt, items, config, enabled)



def list_scenarios(suite_id: int, enabled_only: bool = True) -> list[dict]:
    ScenarioModel._validate_id(suite_id)
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            where = "WHERE suite_id = %s"
            if enabled_only:
                where += " AND enabled = true"
            cur.execute(
                f"SELECT * FROM eval_scenarios {where} ORDER BY sort_key, name",
                (suite_id,),
            )
            return [ScenarioModel.serialize_timestamps(r) for r in cur.fetchall()]


def get_scenario(scenario_id: int) -> dict | None:
    return ScenarioModel.find_by_id(scenario_id)


def create_scenario(
    suite_id: int,
    name: str,
    prompt: str,
    enabled: bool = True,
) -> int:
    assert suite_id > 0, "suite_id must be positive."
    assert_not_empty(name, "name")
    assert_not_empty(prompt, "prompt")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO eval_scenarios (suite_id, name, prompt, enabled)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (suite_id, name, prompt, enabled),
            )
            return cur.fetchone()[0]


def update_scenario(
    scenario_id: int,
    *,
    name: str | None = None,
    prompt: str | None = None,
    enabled: bool | None = None,
) -> None:
    ScenarioModel.update(scenario_id, name=name, prompt=prompt, enabled=enabled)


def delete_scenario(scenario_id: int) -> None:
    ScenarioModel.delete_by_id(scenario_id)


def upsert_scenario(
    suite_id: int,
    name: str,
    prompt: str,
    enabled: bool = True,
) -> int:
    assert suite_id > 0, "suite_id must be positive."
    assert_not_empty(name, "name")

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id FROM eval_scenarios WHERE suite_id = %s AND name = %s",
                (suite_id, name),
            )
            row = cur.fetchone()

    if row:
        update_scenario(row["id"], prompt=prompt, enabled=enabled)
        return row["id"]
    return create_scenario(suite_id, name, prompt, enabled)




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
        from services.db.harness import collect_rules_from_db
        harness_type = items.get("harness_type", "rule")
        agent = items.get("agent", "claude")
        exclude = set(items.get("exclude", []))

        if harness_type == "rule":
            all_items = collect_rules_from_db(agent)
        else:
            raise ValueError(f"Unsupported harness_type: {harness_type}")

        return [(name, body) for name, body in all_items if name not in exclude]

    if source == "skill":
        from services.db.harness import get_skill
        skill_name = items.get("skill_name")
        assert skill_name, "skill source requires 'skill_name'."
        skill = get_skill(skill_name)
        assert skill, f"Skill not found in harness DB: {skill_name}"
        return [(skill_name, skill["content"]["body"])]

    raise ValueError(f"Unknown items source: {source}")


def resolve_extra_context(items: dict) -> str | None:
    source = items.get("source")
    if source == "skill":
        from services.db.harness import get_skill
        skill_name = items.get("skill_name")
        assert skill_name, "skill source requires 'skill_name'."
        skill = get_skill(skill_name)
        assert skill, f"Skill not found in harness DB: {skill_name}"
        return skill["content"]["body"]
    return None
