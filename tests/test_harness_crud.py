from __future__ import annotations

import pytest

from services.db.harness import (
    create_item, update_content, update_metadata,
    get_item_by_id, get_version_history, list_items, list_items_full,
)


def _postgres_available() -> bool:
    try:
        from services.db.connection import DATABASE_URL
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        conn.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_available(), reason="Postgres not available"
)

ALL_AGENTS = ["claude", "codex", "gemini"]
CONTENT = {"body": "## Test", "metadata": {}}


@pytest.fixture(autouse=True)
def _clean():
    from services.db import get_connection, init_db
    init_db()
    yield
    with get_connection() as conn:
        with conn.cursor() as cur:
            for t in ("harness_rules", "harness_skills", "harness_tools", "harness_hooks"):
                cur.execute(f"DELETE FROM {t} WHERE name LIKE 'crud_%'")


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
    v3_id = update_content("rule", v2_id, {"body": "v3", "metadata": {}})

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
    item_id = create_item("rule", "crud_dis", content=CONTENT, agents=ALL_AGENTS, enabled=False)
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
