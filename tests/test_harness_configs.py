from __future__ import annotations

import pytest

from services.api.models.shared.harness import (
    create_item, get_item_by_id, update_content, delete_item,
)
from services.config import ALL_AGENTS

CONTENT = {"body": "## Test Config", "metadata": {}}


@pytest.fixture(autouse=True)
def _clean_config_test_data():
    yield
    from tests.conftest import clean_harness_rows
    clean_harness_rows("cfg_%")


def _count_configs(item_id: int, item_type: str = "rule") -> int:
    from services.db import get_connection
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM harness_configs WHERE item_id = %s AND item_type = %s",
                (item_id, item_type),
            )
            return cur.fetchone()[0]


class TestCreateItemAutoCreatesConfig:
    def test_creates_default_config_row(self):
        from services.api.models.harness_config import list_configs
        item_id = create_item("rule", "cfg_auto", content=CONTENT, agents=ALL_AGENTS)
        configs = list_configs(item_id, "rule")
        assert len(configs) == 1

    def test_default_config_has_wildcard_device_and_repo(self):
        from services.api.models.harness_config import list_configs
        item_id = create_item("rule", "cfg_defaults", content=CONTENT, agents=ALL_AGENTS)
        cfg = list_configs(item_id, "rule")[0]
        assert cfg["device"] == "*"
        assert cfg["repo"] == "*"

    def test_default_config_is_additive(self):
        from services.api.models.harness_config import list_configs
        item_id = create_item("rule", "cfg_additive", content=CONTENT, agents=ALL_AGENTS)
        cfg = list_configs(item_id, "rule")[0]
        assert cfg["exclude"] is False
        assert cfg["enabled"] is True

    def test_default_config_inherits_agents(self):
        from services.api.models.harness_config import list_configs
        item_id = create_item("rule", "cfg_agents", content=CONTENT, agents=["claude"])
        cfg = list_configs(item_id, "rule")[0]
        assert cfg["agents"] == ["claude"]


class TestGetItemIncludesConfigs:
    def test_item_has_configs_key(self):
        item_id = create_item("rule", "cfg_get", content=CONTENT, agents=ALL_AGENTS)
        item = get_item_by_id("rule", item_id)
        assert "configs" in item
        assert isinstance(item["configs"], list)
        assert len(item["configs"]) == 1

    def test_config_fields_present(self):
        item_id = create_item("rule", "cfg_fields", content=CONTENT, agents=ALL_AGENTS)
        item = get_item_by_id("rule", item_id)
        cfg = item["configs"][0]
        assert "id" in cfg
        assert "device" in cfg
        assert "repo" in cfg
        assert "agents" in cfg
        assert "subagents" in cfg
        assert "enabled" in cfg
        assert "exclude" in cfg


class TestConfigCRUD:
    def test_create_additional_config(self):
        from services.api.models.harness_config import create_config, list_configs
        item_id = create_item("rule", "cfg_multi", content=CONTENT, agents=ALL_AGENTS)
        create_config(item_id, "rule", device="work-laptop", repo="/Users/me/proj", agents=["claude"])
        configs = list_configs(item_id, "rule")
        assert len(configs) == 2

    def test_update_config(self):
        from services.api.models.harness_config import create_config, list_configs, update_config
        item_id = create_item("rule", "cfg_update", content=CONTENT, agents=ALL_AGENTS)
        cfg_id = create_config(item_id, "rule", device="old-device")
        update_config(cfg_id, device="new-device", repo="/new/path")
        configs = list_configs(item_id, "rule")
        updated = [c for c in configs if c["id"] == cfg_id][0]
        assert updated["device"] == "new-device"
        assert updated["repo"] == "/new/path"

    def test_delete_config(self):
        from services.api.models.harness_config import create_config, list_configs, delete_config
        item_id = create_item("rule", "cfg_delete", content=CONTENT, agents=ALL_AGENTS)
        cfg_id = create_config(item_id, "rule", device="temp")
        assert len(list_configs(item_id, "rule")) == 2
        delete_config(cfg_id)
        assert len(list_configs(item_id, "rule")) == 1

    def test_delete_item_cascades_configs(self):
        item_id = create_item("rule", "cfg_cascade", content=CONTENT, agents=ALL_AGENTS)
        assert _count_configs(item_id) == 1
        delete_item("rule", item_id)
        assert _count_configs(item_id) == 0


class TestMigrationPreservesData:

    def test_seed_rule_has_config(self):
        from services.api.models.shared.harness import get_item
        from services.api.models.harness_config import list_configs
        item = get_item("rule", "test_rule")
        assert item is not None
        configs = list_configs(item["id"], "rule")
        assert len(configs) >= 1

    def test_seed_config_matches_legacy_agents(self):
        from services.api.models.shared.harness import get_item
        from services.api.models.harness_config import list_configs
        item = get_item("rule", "test_rule")
        configs = list_configs(item["id"], "rule")
        cfg = configs[0]
        assert set(cfg["agents"]) == set(item["agents"])

    def test_seed_config_matches_legacy_enabled(self):
        from services.api.models.shared.harness import get_item
        from services.api.models.harness_config import list_configs
        item = get_item("rule", "test_rule")
        configs = list_configs(item["id"], "rule")
        cfg = configs[0]
        assert cfg["enabled"] == item["enabled"]

    def test_seed_config_uses_wildcard_device_and_repo(self):
        from services.api.models.shared.harness import get_item
        from services.api.models.harness_config import list_configs
        item = get_item("rule", "test_rule")
        configs = list_configs(item["id"], "rule")
        cfg = configs[0]
        assert cfg["device"] == "*"
        assert cfg["repo"] == "*"

    def test_all_seed_items_have_wildcard_configs(self):
        from services.api.models.shared.harness import get_item
        from services.api.models.harness_config import list_configs
        for item_type, name in [("rule", "test_rule"), ("skill", "test_skill"), ("tool", "test_tool"), ("hook", "test_hook"), ("agent", "test_agent")]:
            item = get_item(item_type, name)
            assert item is not None, f"Seed {item_type} '{name}' not found"
            configs = list_configs(item["id"], item_type)
            assert len(configs) >= 1, f"Seed {item_type} '{name}' has no configs"
            assert configs[0]["device"] == "*", f"Seed {item_type} '{name}' device is not wildcard"
            assert configs[0]["repo"] == "*", f"Seed {item_type} '{name}' repo is not wildcard"


class TestLegacyColumnsUntouched:
    def test_item_still_has_project_column(self):
        item_id = create_item("rule", "cfg_legacy", content=CONTENT, agents=ALL_AGENTS)
        item = get_item_by_id("rule", item_id)
        assert "project" in item

    def test_item_still_has_agents_column(self):
        item_id = create_item("rule", "cfg_legacy2", content=CONTENT, agents=["claude"])
        item = get_item_by_id("rule", item_id)
        assert "agents" in item
        assert item["agents"] == ["claude"]

    def test_item_still_has_enabled_column(self):
        item_id = create_item("rule", "cfg_legacy3", content=CONTENT, agents=ALL_AGENTS, enabled=False)
        item = get_item_by_id("rule", item_id)
        assert "enabled" in item
        assert item["enabled"] is False


class TestVersionBumpPreservesAllFields:
    def test_update_content_preserves_subagents(self):
        from services.api.models.shared.harness import update_metadata
        item_id = create_item("rule", "cfg_vbump", content=CONTENT, agents=ALL_AGENTS)
        update_metadata("rule", item_id, subagents=["research"])
        new_id = update_content("rule", item_id, {"body": "## V2", "metadata": {}})
        new_item = get_item_by_id("rule", new_id)
        assert new_item["subagents"] == ["research"]

    def test_update_content_preserves_agents(self):
        item_id = create_item("rule", "cfg_vbump2", content=CONTENT, agents=["claude"])
        new_id = update_content("rule", item_id, {"body": "## V2", "metadata": {}})
        new_item = get_item_by_id("rule", new_id)
        assert new_item["agents"] == ["claude"]

    def test_update_content_preserves_enabled(self):
        item_id = create_item("rule", "cfg_vbump3", content=CONTENT, agents=ALL_AGENTS, enabled=False)
        new_id = update_content("rule", item_id, {"body": "## V2", "metadata": {}})
        new_item = get_item_by_id("rule", new_id)
        assert new_item["enabled"] is False


class TestResolveNoConfigs:

    def test_resolve_no_configs_returns_empty(self):
        from services.api.models.shared.sync import resolve_sync_targets
        item = {"agents": ALL_AGENTS, "enabled": True, "configs": []}
        targets = resolve_sync_targets(item, agent="claude", device_name="work")
        assert targets == []

    def test_resolve_no_configs_ignores_legacy_agent_field(self):
        from services.api.models.shared.sync import resolve_sync_targets
        item = {"agents": ["gemini"], "enabled": True, "configs": []}
        targets = resolve_sync_targets(item, agent="claude", device_name="work")
        assert targets == []

    def test_resolve_no_configs_ignores_legacy_enabled_field(self):
        from services.api.models.shared.sync import resolve_sync_targets
        item = {"agents": ALL_AGENTS, "enabled": False, "configs": []}
        targets = resolve_sync_targets(item, agent="claude", device_name="work")
        assert targets == []


class TestResolveAdditiveWildcard:
    def test_wildcard_device_and_repo(self):
        from services.api.models.shared.sync import resolve_sync_targets
        item = {"configs": [
            {"device": "*", "repo": "*", "agents": ["claude"], "subagents": [], "enabled": True, "exclude": False},
        ], "agents": ALL_AGENTS, "enabled": True}
        targets = resolve_sync_targets(item, agent="claude", device_name="work")
        assert targets == ["*"]

    def test_wildcard_matches_when_no_device_set(self):
        from services.api.models.shared.sync import resolve_sync_targets
        item = {"configs": [
            {"device": "*", "repo": "*", "agents": ["claude"], "subagents": [], "enabled": True, "exclude": False},
        ], "agents": ALL_AGENTS, "enabled": True}
        targets = resolve_sync_targets(item, agent="claude", device_name="")
        assert targets == ["*"]

    def test_specific_device_skipped_when_no_device_set(self):
        from services.api.models.shared.sync import resolve_sync_targets
        item = {"configs": [
            {"device": "work-laptop", "repo": "/proj", "agents": ["claude"], "subagents": [], "enabled": True, "exclude": False},
        ], "agents": ALL_AGENTS, "enabled": True}
        targets = resolve_sync_targets(item, agent="claude", device_name="")
        assert targets == []


class TestResolveAdditiveSpecificRepo:
    def test_specific_repo_returned(self):
        from services.api.models.shared.sync import resolve_sync_targets
        item = {"configs": [
            {"device": "*", "repo": "/Users/me/proj", "agents": ["claude"], "subagents": [], "enabled": True, "exclude": False},
        ], "agents": ALL_AGENTS, "enabled": True}
        targets = resolve_sync_targets(item, agent="claude", device_name="work")
        assert targets == ["/Users/me/proj"]

    def test_multiple_repos(self):
        from services.api.models.shared.sync import resolve_sync_targets
        item = {"configs": [
            {"device": "*", "repo": "/proj/a", "agents": ["claude"], "subagents": [], "enabled": True, "exclude": False},
            {"device": "*", "repo": "/proj/b", "agents": ["claude"], "subagents": [], "enabled": True, "exclude": False},
        ], "agents": ALL_AGENTS, "enabled": True}
        targets = resolve_sync_targets(item, agent="claude", device_name="work")
        assert sorted(targets) == ["/proj/a", "/proj/b"]


class TestResolveSubtractive:
    def test_subtractive_removes_matching_target(self):
        from services.api.models.shared.sync import resolve_sync_targets
        item = {"configs": [
            {"device": "*", "repo": "*", "agents": ["claude"], "subagents": [], "enabled": True, "exclude": False},
            {"device": "work", "repo": "/Users/me/projX", "agents": ["claude"], "subagents": [], "enabled": True, "exclude": True},
        ], "agents": ALL_AGENTS, "enabled": True}
        targets = resolve_sync_targets(item, agent="claude", device_name="work")
        assert "*" in targets

    def test_subtractive_removes_specific_repo(self):
        from services.api.models.shared.sync import resolve_sync_targets
        item = {"configs": [
            {"device": "*", "repo": "/proj/a", "agents": ["claude"], "subagents": [], "enabled": True, "exclude": False},
            {"device": "*", "repo": "/proj/b", "agents": ["claude"], "subagents": [], "enabled": True, "exclude": False},
            {"device": "*", "repo": "/proj/b", "agents": ["claude"], "subagents": [], "enabled": True, "exclude": True},
        ], "agents": ALL_AGENTS, "enabled": True}
        targets = resolve_sync_targets(item, agent="claude", device_name="work")
        assert targets == ["/proj/a"]

    def test_subtractive_removes_global(self):
        from services.api.models.shared.sync import resolve_sync_targets
        item = {"configs": [
            {"device": "*", "repo": "*", "agents": ["claude"], "subagents": [], "enabled": True, "exclude": False},
            {"device": "work", "repo": "*", "agents": ["claude"], "subagents": [], "enabled": True, "exclude": True},
        ], "agents": ALL_AGENTS, "enabled": True}
        targets = resolve_sync_targets(item, agent="claude", device_name="work")
        assert targets == []

    def test_subtractive_only_applies_on_matching_device(self):
        from services.api.models.shared.sync import resolve_sync_targets
        item = {"configs": [
            {"device": "*", "repo": "*", "agents": ["claude"], "subagents": [], "enabled": True, "exclude": False},
            {"device": "home", "repo": "*", "agents": ["claude"], "subagents": [], "enabled": True, "exclude": True},
        ], "agents": ALL_AGENTS, "enabled": True}
        targets = resolve_sync_targets(item, agent="claude", device_name="work")
        assert targets == ["*"]


class TestResolveDeviceMismatch:
    def test_device_mismatch_excludes_config(self):
        from services.api.models.shared.sync import resolve_sync_targets
        item = {"configs": [
            {"device": "home", "repo": "/proj", "agents": ["claude"], "subagents": [], "enabled": True, "exclude": False},
        ], "agents": ALL_AGENTS, "enabled": True}
        targets = resolve_sync_targets(item, agent="claude", device_name="work")
        assert targets == []

    def test_device_match_includes_config(self):
        from services.api.models.shared.sync import resolve_sync_targets
        item = {"configs": [
            {"device": "work", "repo": "/proj", "agents": ["claude"], "subagents": [], "enabled": True, "exclude": False},
        ], "agents": ALL_AGENTS, "enabled": True}
        targets = resolve_sync_targets(item, agent="claude", device_name="work")
        assert targets == ["/proj"]


class TestResolveAgentFilter:
    def test_config_for_wrong_agent_ignored(self):
        from services.api.models.shared.sync import resolve_sync_targets
        item = {"configs": [
            {"device": "*", "repo": "*", "agents": ["gemini"], "subagents": [], "enabled": True, "exclude": False},
        ], "agents": ALL_AGENTS, "enabled": True}
        targets = resolve_sync_targets(item, agent="claude", device_name="work")
        assert targets == []

    def test_config_for_correct_agent_included(self):
        from services.api.models.shared.sync import resolve_sync_targets
        item = {"configs": [
            {"device": "*", "repo": "*", "agents": ["claude", "codex"], "subagents": [], "enabled": True, "exclude": False},
        ], "agents": ALL_AGENTS, "enabled": True}
        targets = resolve_sync_targets(item, agent="claude", device_name="work")
        assert targets == ["*"]


class TestResolveDisabledIgnored:
    def test_disabled_config_skipped(self):
        from services.api.models.shared.sync import resolve_sync_targets
        item = {"configs": [
            {"device": "*", "repo": "*", "agents": ["claude"], "subagents": [], "enabled": False, "exclude": False},
        ], "agents": ALL_AGENTS, "enabled": True}
        targets = resolve_sync_targets(item, agent="claude", device_name="work")
        # No enabled configs → no sync (configs are sole authority)
        assert targets == []

    def test_disabled_config_with_enabled_config(self):
        from services.api.models.shared.sync import resolve_sync_targets
        item = {"configs": [
            {"device": "*", "repo": "*", "agents": ["claude"], "subagents": [], "enabled": False, "exclude": False},
            {"device": "*", "repo": "/proj", "agents": ["claude"], "subagents": [], "enabled": True, "exclude": False},
        ], "agents": ALL_AGENTS, "enabled": True}
        targets = resolve_sync_targets(item, agent="claude", device_name="work")
        assert targets == ["/proj"]
