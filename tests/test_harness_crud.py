from __future__ import annotations

import pytest

from services.api.models.shared.harness import (
    create_item, update_content, update_metadata,
    get_item_by_id, get_version_history, list_items, list_items_full,
    delete_item, reorder_items,
)
from services.config import ALL_AGENTS
CONTENT = {"body": "## Test", "metadata": {}}


@pytest.fixture(autouse=True)
def _clean():
    yield
    from tests.conftest import clean_harness_rows
    clean_harness_rows("crud_%", "reorder_%", "to_delete", "clone_%")


def test_create_item_inserts_with_version_1():
    item_id = create_item("rule", "crud_new", content=CONTENT, agents=ALL_AGENTS)
    row = get_item_by_id("rule", item_id)
    assert row["version"] == 1
    assert row["name"] == "crud_new"


def test_create_item_rejects_duplicate_name():
    create_item("rule", "crud_dup", content=CONTENT, agents=ALL_AGENTS)
    with pytest.raises(Exception):
        create_item("rule", "crud_dup", content=CONTENT, agents=ALL_AGENTS)


def test_update_content_creates_new_version():
    item_id = create_item("rule", "crud_ver", content=CONTENT, agents=ALL_AGENTS)
    new_content = {"body": "## Updated", "metadata": {}}
    new_id = update_content("rule", item_id, new_content)
    assert new_id != item_id

    new_row = get_item_by_id("rule", new_id)
    assert new_row["version"] == 2
    assert new_row["content"]["body"] == "## Updated"

    old_row = get_item_by_id("rule", item_id)
    assert old_row["version"] == 1
    assert old_row["content"]["body"] == "## Test"


def test_update_content_latest_has_highest_version():
    item_id = create_item("rule", "crud_latest", content=CONTENT, agents=ALL_AGENTS)
    v2_id = update_content("rule", item_id, {"body": "v2", "metadata": {}})
    update_content("rule", v2_id, {"body": "v3", "metadata": {}})

    history = get_version_history("rule", "crud_latest")
    assert history[0]["version"] == 3
    assert history[-1]["version"] == 1


def test_update_metadata_does_not_change_version():
    item_id = create_item("rule", "crud_meta", content=CONTENT, agents=ALL_AGENTS)
    update_metadata("rule", item_id, agents=["claude"])
    row = get_item_by_id("rule", item_id)
    assert row["version"] == 1
    assert row["agents"] == ["claude"]


def test_update_metadata_toggle_enabled():
    item_id = create_item("rule", "crud_toggle", content=CONTENT, agents=ALL_AGENTS)
    update_metadata("rule", item_id, enabled=False)
    row = get_item_by_id("rule", item_id)
    assert row["enabled"] is False
    assert row["version"] == 1


def test_get_version_history_returns_all_versions_desc():
    item_id = create_item("rule", "crud_hist", content=CONTENT, agents=ALL_AGENTS)
    v2_id = update_content("rule", item_id, {"body": "v2", "metadata": {}})
    update_content("rule", v2_id, {"body": "v3", "metadata": {}})

    history = get_version_history("rule", "crud_hist")
    assert len(history) == 3
    versions = [h["version"] for h in history]
    assert versions == [3, 2, 1]


def test_list_items_full_returns_disabled():
    create_item("rule", "crud_dis", content=CONTENT, agents=ALL_AGENTS, enabled=False)
    rows = list_items_full("rule")
    names = [r["name"] for r in rows]
    assert "crud_dis" in names


def test_list_items_full_returns_latest_version_only():
    item_id = create_item("rule", "crud_lv", content=CONTENT, agents=ALL_AGENTS)
    update_content("rule", item_id, {"body": "v2", "metadata": {}})

    rows = list_items_full("rule")
    matches = [r for r in rows if r["name"] == "crud_lv"]
    assert len(matches) == 1
    assert matches[0]["version"] == 2


def test_sync_list_items_scopes_to_latest_enabled_agent():
    item_id = create_item("rule", "crud_sync", content=CONTENT, agents=["claude"])
    update_content("rule", item_id, {"body": "v2", "metadata": {}})

    rows = list_items("rule", agent="claude")
    matches = [r for r in rows if r["name"] == "crud_sync"]
    assert len(matches) == 1
    assert matches[0]["version"] == 2

    rows = list_items("rule", agent="codex")
    matches = [r for r in rows if r["name"] == "crud_sync"]
    assert len(matches) == 0


def test_delete_item_removes_row():
    item_id = create_item("rule", "to_delete", CONTENT, agents=ALL_AGENTS)
    assert get_item_by_id("rule", item_id) is not None
    delete_item("rule", item_id)
    assert get_item_by_id("rule", item_id) is None


def test_update_metadata_clone_as_skill():
    item_id = create_item("rule", "clone_toggle", content=CONTENT, agents=ALL_AGENTS)
    row = get_item_by_id("rule", item_id)
    assert row["clone_as_skill"] is False

    update_metadata("rule", item_id, clone_as_skill=True)
    row = get_item_by_id("rule", item_id)
    assert row["clone_as_skill"] is True

    update_metadata("rule", item_id, clone_as_skill=False)
    row = get_item_by_id("rule", item_id)
    assert row["clone_as_skill"] is False


def test_reorder_items_sets_sort_key():
    id1 = create_item("rule", "reorder_a", CONTENT, agents=ALL_AGENTS)
    id2 = create_item("rule", "reorder_b", CONTENT, agents=ALL_AGENTS)
    id3 = create_item("rule", "reorder_c", CONTENT, agents=ALL_AGENTS)

    reorder_items("rule", [id3, id1, id2])

    r3 = get_item_by_id("rule", id3)
    r1 = get_item_by_id("rule", id1)
    r2 = get_item_by_id("rule", id2)
    assert r3["sort_key"] < r1["sort_key"] < r2["sort_key"]


class TestCreateRequestValidation:
    def test_rejects_empty_name(self):
        from pydantic import ValidationError
        from services.api.routers.shared.validators import CreateRequest
        with pytest.raises(ValidationError, match="name"):
            CreateRequest(name="", content={"body": "", "metadata": {}})

    def test_rejects_long_name(self):
        from pydantic import ValidationError
        from services.api.routers.shared.validators import CreateRequest
        with pytest.raises(ValidationError, match="name"):
            CreateRequest(name="a" * 41, content={"body": "", "metadata": {}})

    def test_rejects_name_with_spaces(self):
        from pydantic import ValidationError
        from services.api.routers.shared.validators import CreateRequest
        with pytest.raises(ValidationError, match="name"):
            CreateRequest(name="my rule", content={"body": "", "metadata": {}})

    def test_rejects_name_with_uppercase(self):
        from pydantic import ValidationError
        from services.api.routers.shared.validators import CreateRequest
        with pytest.raises(ValidationError, match="name"):
            CreateRequest(name="MyRule", content={"body": "", "metadata": {}})

    def test_accepts_valid_name(self):
        from services.api.routers.shared.validators import CreateRequest
        req = CreateRequest(name="my_rule_1", content={"body": "test", "metadata": {}})
        assert req.name == "my_rule_1"

    def test_rejects_invalid_agent(self):
        from pydantic import ValidationError
        from services.api.routers.shared.validators import CreateRequest
        with pytest.raises(ValidationError, match="agents"):
            CreateRequest(name="valid", content={"body": "", "metadata": {}}, agents=["fake"])

    def test_rejects_bad_repo(self):
        from pydantic import ValidationError
        from services.api.routers.shared.validators import CreateRequest
        with pytest.raises(ValidationError, match="repo"):
            CreateRequest(name="valid", content={"body": "", "metadata": {}}, repo="relative/path")

    def test_rejects_content_without_body(self):
        from pydantic import ValidationError
        from services.api.routers.shared.validators import CreateRequest
        with pytest.raises(ValidationError, match="content"):
            CreateRequest(name="valid", content={"other": "val"})
