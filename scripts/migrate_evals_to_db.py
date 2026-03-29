#!/usr/bin/env -S .venv/bin/python3
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.shared.paths import bootstrap, REPO_ROOT  # noqa: E402
bootstrap()

from services.db import get_connection, init_db  # noqa: E402
from services.db.evals import upsert_suite, upsert_scenario  # noqa: E402

EVALS_CONFIG = REPO_ROOT / "evals" / "config"

SUITES = [
    {
        "dir": "rules",
        "name": "rules_plans",
        "eval_type": "rules",
        "subcategory": "plans",
        "items": {
            "source": "harness",
            "harness_type": "rule",
            "agent": "claude",
            "exclude": ["memory"],
        },
        "config": {},
    },
    {
        "dir": "write_ticket",
        "name": "skills_write_ticket",
        "eval_type": "skills",
        "subcategory": "write_ticket",
        "items": {"source": "skill", "skill_name": "write_ticket"},
        "config": {},
    },
    {
        "dir": "write_epic",
        "name": "skills_write_epic",
        "eval_type": "skills",
        "subcategory": "write_epic",
        "items": {"source": "skill", "skill_name": "write_epic"},
        "config": {},
    },
]


def _read_judge_prompt(suite_dir: Path) -> str:
    judge_path = suite_dir / "judge.yaml"
    assert judge_path.exists(), f"Judge config not found: {judge_path}"
    data = yaml.safe_load(judge_path.read_text(encoding="utf-8"))
    assert "prompt" in data, f"No 'prompt' key in {judge_path}"
    return data["prompt"]


def _read_scenarios(suite_dir: Path) -> list[dict]:
    scenarios_path = suite_dir / "scenarios.yaml"
    assert scenarios_path.exists(), f"Scenarios file not found: {scenarios_path}"
    data = yaml.safe_load(scenarios_path.read_text(encoding="utf-8"))
    assert "scenarios" in data, f"No 'scenarios' key in {scenarios_path}"
    return data["scenarios"]


def _backfill_eval_results() -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE eval_results er
                SET eval_suite_id = su.id
                FROM eval_suites su
                WHERE er.eval_type = su.eval_type
                  AND er.subcategory = su.subcategory
                  AND er.eval_suite_id IS NULL
            """)
            suite_count = cur.rowcount

            cur.execute("""
                UPDATE eval_results er
                SET eval_scenario_id = sc.id
                FROM eval_scenarios sc
                WHERE sc.suite_id = er.eval_suite_id
                  AND sc.name = er.scenario
                  AND er.eval_scenario_id IS NULL
            """)
            scenario_count = cur.rowcount

    return suite_count, scenario_count


def main() -> None:
    print("[1/5] Initializing database...")
    init_db()

    total_suites = 0
    total_scenarios = 0

    for i, suite_def in enumerate(SUITES, start=2):
        suite_dir = EVALS_CONFIG / suite_def["dir"]
        step = f"[{i}/{len(SUITES) + 2}]"
        print(f"{step} Migrating {suite_def['name']}...")

        judge_prompt = _read_judge_prompt(suite_dir)
        suite_id = upsert_suite(
            name=suite_def["name"],
            eval_type=suite_def["eval_type"],
            subcategory=suite_def["subcategory"],
            judge_prompt=judge_prompt,
            items=suite_def["items"],
            config=suite_def["config"],
        )
        total_suites += 1
        print(f"  suite id={suite_id}")

        scenarios = _read_scenarios(suite_dir)
        count = 0
        for sc in scenarios:
            upsert_scenario(
                suite_id=suite_id,
                name=sc["name"],
                prompt=sc["prompt"],
                enabled=sc.get("enabled", True),
            )
            count += 1
        total_scenarios += count
        print(f"  {count} scenarios")

    step = f"[{len(SUITES) + 2}/{len(SUITES) + 2}]"
    print(f"{step} Backfilling eval_results FK columns...")
    suite_linked, scenario_linked = _backfill_eval_results()
    print(f"  {suite_linked} rows linked to suites, {scenario_linked} rows linked to scenarios")

    print(f"\nMigration complete: {total_suites} suites, {total_scenarios} scenarios.")
    print("YAML files have NOT been deleted.")


if __name__ == "__main__":
    main()
