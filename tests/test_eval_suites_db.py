from __future__ import annotations

import uuid

import pytest


def _unique(prefix: str = "test") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@pytest.fixture()
def suite_id():
    from services.db.evals import create_suite, delete_suite
    name = _unique("suite")
    sid = create_suite(
        name=name,
        eval_type="rules",
        subcategory="plans",
        judge_prompt="Judge this.",
        items={"source": "harness", "harness_type": "rule", "agent": "claude", "exclude": []},
    )
    yield sid
    try:
        delete_suite(sid)
    except Exception:
        pass


@pytest.fixture()
def scenario_id(suite_id):
    from services.db.evals import create_scenario, delete_scenario
    scid = create_scenario(suite_id, "test_scenario", "Do something.")
    yield scid
    try:
        delete_scenario(scid)
    except Exception:
        pass




def test_create_suite(suite_id):
    from services.db.evals import get_suite
    suite = get_suite(suite_id)
    assert suite is not None
    assert suite["name"].startswith("suite_")
    assert suite["eval_type"] == "rules"
    assert suite["subcategory"] == "plans"
    assert suite["judge_prompt"] == "Judge this."
    assert suite["enabled"] is True


def test_get_suite_by_name(suite_id):
    from services.db.evals import get_suite, get_suite_by_name
    original = get_suite(suite_id)
    suite = get_suite_by_name(original["name"])
    assert suite is not None
    assert suite["id"] == suite_id


def test_get_suite_by_name_not_found():
    from services.db.evals import get_suite_by_name
    assert get_suite_by_name("nonexistent") is None


def test_update_suite_partial(suite_id):
    from services.db.evals import update_suite, get_suite
    update_suite(suite_id, judge_prompt="New prompt.")
    suite = get_suite(suite_id)
    assert suite["judge_prompt"] == "New prompt."


def test_delete_suite_cascades_scenarios(suite_id):
    from services.db.evals import create_scenario, delete_suite, get_scenario
    scid = create_scenario(suite_id, "cascade_test", "prompt")
    delete_suite(suite_id)
    assert get_scenario(scid) is None


def test_upsert_suite_creates_new():
    from services.db.evals import upsert_suite, get_suite, delete_suite
    name = _unique("upsert")
    sid = upsert_suite(name, "rules", "plans", "Judge.")
    try:
        suite = get_suite(sid)
        assert suite is not None
        assert suite["name"] == name
    finally:
        delete_suite(sid)


def test_upsert_suite_updates_existing(suite_id):
    from services.db.evals import upsert_suite, get_suite
    suite = get_suite(suite_id)
    returned_id = upsert_suite(
        suite["name"], "skills", "write_ticket", "Updated judge.",
        items={"source": "skill", "skill_name": "write_ticket"},
    )
    assert returned_id == suite_id
    updated = get_suite(suite_id)
    assert updated["eval_type"] == "skills"
    assert updated["judge_prompt"] == "Updated judge."


def test_list_suites_pagination(suite_id):
    from services.db.evals import list_suites
    items, total = list_suites(limit=1, offset=0)
    assert total >= 1
    assert len(items) <= 1


def test_list_suites_enabled_filter(suite_id):
    from services.db.evals import update_suite, list_suites
    update_suite(suite_id, enabled=False)
    items, _ = list_suites(enabled_only=True)
    assert all(s["id"] != suite_id for s in items)

    items_all, _ = list_suites(enabled_only=False)
    assert any(s["id"] == suite_id for s in items_all)


def test_create_suite_rejects_empty_name():
    from services.db.evals import create_suite
    with pytest.raises(AssertionError):
        create_suite("", "rules", "plans", "Judge.")


def test_create_suite_rejects_empty_judge_prompt():
    from services.db.evals import create_suite
    with pytest.raises(AssertionError):
        create_suite("empty_judge", "rules", "plans", "")



def test_create_scenario(suite_id, scenario_id):
    from services.db.evals import get_scenario
    sc = get_scenario(scenario_id)
    assert sc is not None
    assert sc["name"] == "test_scenario"
    assert sc["prompt"] == "Do something."
    assert sc["suite_id"] == suite_id


def test_list_scenarios_for_suite(suite_id, scenario_id):
    from services.db.evals import list_scenarios
    scenarios = list_scenarios(suite_id)
    assert len(scenarios) >= 1
    assert any(s["id"] == scenario_id for s in scenarios)


def test_update_scenario_partial(scenario_id):
    from services.db.evals import update_scenario, get_scenario
    update_scenario(scenario_id, prompt="Updated prompt.")
    sc = get_scenario(scenario_id)
    assert sc["prompt"] == "Updated prompt."
    assert sc["name"] == "test_scenario"


def test_delete_scenario(suite_id):
    from services.db.evals import create_scenario, delete_scenario, get_scenario
    scid = create_scenario(suite_id, "to_delete", "prompt")
    delete_scenario(scid)
    assert get_scenario(scid) is None


def test_upsert_scenario(suite_id):
    from services.db.evals import upsert_scenario, get_scenario, delete_scenario
    scid = upsert_scenario(suite_id, "upsert_sc", "Initial prompt.")
    try:
        sc = get_scenario(scid)
        assert sc["prompt"] == "Initial prompt."

        returned_id = upsert_scenario(suite_id, "upsert_sc", "Updated prompt.")
        assert returned_id == scid
        sc = get_scenario(scid)
        assert sc["prompt"] == "Updated prompt."
    finally:
        delete_scenario(scid)


def test_create_scenario_rejects_duplicate_name_in_suite(suite_id, scenario_id):
    from services.db.evals import create_scenario
    with pytest.raises(Exception):
        create_scenario(suite_id, "test_scenario", "Dupe prompt.")


def test_list_enabled_scenarios_merges_suite_config(suite_id, scenario_id):
    from services.db.evals import list_enabled_scenarios_for_suite, get_suite
    suite = get_suite(suite_id)
    scenarios = list_enabled_scenarios_for_suite(suite["name"])
    assert len(scenarios) >= 1
    sc = scenarios[0]
    assert "judge_prompt" in sc
    assert sc["judge_prompt"] == "Judge this."
    assert "items" in sc
    assert "eval_type" in sc
    assert sc["eval_type"] == "rules"
    assert "subcategory" in sc
    assert sc["subcategory"] == "plans"




def test_resolve_items_harness_source():
    from services.db.evals import resolve_items
    items_config = {
        "source": "harness",
        "harness_type": "rule",
        "agent": "claude",
        "exclude": ["memory"],
    }
    result = resolve_items(items_config)
    assert isinstance(result, list)
    assert len(result) > 0
    for name, body in result:
        assert name != "memory"
        assert isinstance(body, str)
        assert len(body) > 0


def test_resolve_items_harness_with_exclude():
    from services.db.evals import resolve_items
    items_config = {
        "source": "harness",
        "harness_type": "rule",
        "agent": "claude",
        "exclude": ["memory", "dry"],
    }
    result = resolve_items(items_config)
    names = [name for name, _ in result]
    assert "memory" not in names
    assert "dry" not in names


def test_resolve_items_unknown_source_crashes():
    from services.db.evals import resolve_items
    with pytest.raises(ValueError, match="Unknown items source"):
        resolve_items({"source": "unknown_source"})


def test_resolve_items_missing_source_crashes():
    from services.db.evals import resolve_items
    with pytest.raises(AssertionError):
        resolve_items({})


def test_resolve_extra_context_harness_returns_none():
    from services.db.evals import resolve_extra_context
    result = resolve_extra_context({
        "source": "harness",
        "harness_type": "rule",
        "agent": "claude",
    })
    assert result is None
