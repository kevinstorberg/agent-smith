from __future__ import annotations

import pytest

from services.api.models.tool import get_tool
from services.db import get_connection, seed
from tests.conftest import clean_harness_rows
from tests.test_action_items_registration import assert_seed_discovery_sync_preserves_custom_settings


@pytest.fixture(autouse=True)
def isolated_profiles_tool(monkeypatch):
    clean_harness_rows("profiles")
    monkeypatch.setattr(seed, "MCP_SERVERS", [entry for entry in seed.MCP_SERVERS if entry[0] == "profiles"])
    yield
    clean_harness_rows("profiles")


@pytest.mark.parametrize("agent", ["claude", "codex", "gemini"])
def test_profiles_seed_discovery_sync_and_custom_settings_survive(agent, tmp_path, monkeypatch):
    assert_seed_discovery_sync_preserves_custom_settings("profiles", agent, tmp_path, monkeypatch)


def test_profiles_seed_is_idempotent_without_registering_people_or_topics_as_tools():
    from uuid import uuid4

    from services.action_items import db
    from services.meetings import profile_db

    seed.seed_mcp_servers()
    first = get_tool("profiles")
    seed.seed_mcp_servers()
    assert get_tool("profiles") == first
    person = profile_db.create_profile("Protocol registration person " + uuid4().hex)
    try:
        topic = db.profile_queue(person["id"]).create({"title": "Unique discussion topic " + uuid4().hex})
        assert get_tool(topic["title"]) is None and get_tool(person["display_name"]) is None
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM harness_tools WHERE name='profiles'")
            assert cursor.fetchone()[0] == 1
    finally:
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM action_items WHERE profile_id=%s", (person["id"],))
            cursor.execute("DELETE FROM participant_profiles WHERE id=%s", (person["id"],))
