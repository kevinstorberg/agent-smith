from __future__ import annotations


def seed_test_data():
    from services.config import ALL_AGENTS, MCP_BASE
    from services.api.models.rule import get_rule, upsert_rule
    from services.api.models.skill import get_skill, upsert_skill
    from services.api.models.tool import get_tool, upsert_tool
    from services.api.models.hook import get_hook, upsert_hook
    from services.api.models.agent import get_agent, upsert_agent
    from services.api.models.evals import get_suite_by_name, create_suite, create_scenario
    from services.api.models.plan import create_plan
    from services.db import get_connection

    if not get_rule("test_rule"):
        upsert_rule(
            "test_rule",
            content={
                "body": (
                    "## Test Rule\n"
                    "* **The Rule:** Be good.\n"
                    "* **Your Process:**\n"
                    "    1. First step.\n"
                    "    2. Second step.\n"
                    "    3. Third step.\n"
                    "* **Example:**\n"
                    "> Example here."
                ),
                "metadata": {},
            },
            agents=ALL_AGENTS,
        )

    if not get_skill("test_skill"):
        upsert_skill(
            "test_skill",
            content={"body": "Test skill body", "metadata": {"description": "A test skill"}},
            agents=ALL_AGENTS,
        )

    if not get_tool("test_tool"):
        upsert_tool(
            "test_tool",
            content={"body": "", "metadata": {"url": f"{MCP_BASE}/mcp/harness/", "description": "Test tool"}},
            agents=ALL_AGENTS,
        )

    if not get_hook("test_hook"):
        upsert_hook(
            "test_hook",
            content={"body": "", "metadata": {"event": "pre_tool_use", "matcher": "Bash", "hooks": []}},
            agents=ALL_AGENTS,
        )

    if not get_agent("test_agent"):
        upsert_agent(
            "test_agent",
            content={"body": "You are a test agent.", "metadata": {"description": "Test agent", "model": "haiku"}},
            agents=ALL_AGENTS,
        )

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM plans WHERE title = 'Test Plan' LIMIT 1")
            if not cur.fetchone():
                create_plan("Test Plan", "This is a test plan body.")

    suite = get_suite_by_name("test_suite")
    if not suite:
        suite_id = create_suite(
            name="test_suite",
            eval_type="rules",
            subcategory="plans",
            judge_prompt="Test judge prompt.",
            items={"source": "harness", "harness_type": "rule", "agent": "claude", "exclude": []},
        )
        scenario_id = create_scenario(
            suite_id=suite_id, name="test_scenario", prompt="Test scenario prompt.",
        )

        from evals.shared.db import save_result
        from datetime import datetime, timezone

        save_result(
            timestamp=datetime(2099, 1, 1, tzinfo=timezone.utc),
            eval_type="rules",
            scenario="test_scenario",
            test_model="test-model",
            judge_model="test-judge",
            threshold=0.8,
            output="test output",
            results=[{"rule": "test_rule", "score": 0.95, "reason": "test reason"}],
            subcategory="plans",
            eval_suite_id=suite_id,
            eval_scenario_id=scenario_id,
        )
