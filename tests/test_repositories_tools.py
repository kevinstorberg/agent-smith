from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp.exceptions import ToolError

from scripts.shared import mcp_utils
from scripts.shared.agents import AGENT_TARGETS
from services.repositories import server
from scripts.repos_tool import register_tool
from services.api.models.shared.harness import get_item_by_id, update_content
from services.api.models.tool import get_tool
from services.db import get_connection
from tests.conftest import clean_harness_rows

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def isolated_repos_tool():
    clean_harness_rows("repos")
    yield
    clean_harness_rows("repos")


@pytest.mark.asyncio
async def test_cleanup_tool_has_strict_preview_defaults_and_destructive_annotation(
    monkeypatch,
):
    calls = []

    def cleanup(repository_path, **options):
        calls.append((repository_path, options))
        return {"summary": {}, "items": [], "errors": []}

    monkeypatch.setattr(server, "cleanup_repository", cleanup)
    mcp = server.create_server()
    tools = await mcp.list_tools()
    assert [tool.name for tool in tools] == ["cleanup_merged_worktrees"]
    tool = tools[0]
    assert tool.annotations.destructiveHint is True
    assert tool.annotations.readOnlyHint is False
    assert tool.inputSchema["additionalProperties"] is False
    await mcp.call_tool("cleanup_merged_worktrees", {"repository_path": "/tmp/example"})
    assert calls == [
        ("/tmp/example", {"execute": False, "force": False, "delete_remote": False})
    ]
    await mcp.call_tool(
        "cleanup_merged_worktrees",
        {
            "repository_path": "/tmp/example",
            "execute": True,
            "force": True,
            "delete_remote": True,
        },
    )
    assert calls[-1][1] == {"execute": True, "force": True, "delete_remote": True}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid",
    [
        {"execute": "true"},
        {"force": 1},
        {"delete_remote": []},
        {"unexpected": True},
        {"repository_path": 123},
    ],
)
async def test_invalid_mcp_arguments_never_reach_cleanup(monkeypatch, invalid):
    monkeypatch.setattr(
        server,
        "cleanup_repository",
        lambda *args, **kwargs: pytest.fail("Invalid call reached cleanup"),
    )
    with pytest.raises(ToolError):
        await server.create_server().call_tool(
            "cleanup_merged_worktrees", {"repository_path": "/tmp/example", **invalid}
        )


@pytest.mark.asyncio
async def test_real_stdio_process_initializes_without_app_database_or_provider_credentials():
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "services/repositories/server.py")],
        env={"APP_ENV": "not-an-application-environment"},
    )
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert [tool.name for tool in tools.tools] == ["cleanup_merged_worktrees"]
            result = await session.call_tool(
                "cleanup_merged_worktrees",
                {"repository_path": "/tmp/example", "execute": "true"},
            )
            assert result.isError


def test_registration_is_idempotent_and_preserves_custom_disabled_configuration(
    isolated_repos_tool,
):
    created = register_tool()
    assert created["created"] is True
    item = get_tool("repos")
    assert item["id"] == created["id"]
    assert item["content"]["metadata"]["command"] == "${AGENT_SMITH_PYTHON}"
    assert item["content"]["metadata"]["args"] == [
        "${AGENT_SMITH_ROOT}/services/repositories/server.py"
    ]
    update_content(
        "tool",
        item["id"],
        {
            "body": "My cleanup settings",
            "metadata": {"command": "my-wrapper", "args": ["keep"]},
        },
    )
    item = get_tool("repos")
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE harness_configs SET enabled=false WHERE item_type='tool' AND item_id=%s",
            (item["id"],),
        )
    before = get_item_by_id("tool", item["id"])
    assert register_tool() == {"id": item["id"], "created": False}
    assert get_item_by_id("tool", item["id"]) == before
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT enabled FROM harness_configs WHERE item_type='tool' AND item_id=%s",
            (item["id"],),
        )
        assert cursor.fetchone()[0] is False


@pytest.mark.parametrize("agent", ["claude", "codex", "gemini"])
def test_sync_resolves_local_interpreter_and_canonical_root_without_overwriting_other_settings(
    agent, tmp_path, monkeypatch
):
    canonical = tmp_path / "checkout"
    canonical.mkdir()
    subprocess.run(["git", "init", "-q", str(canonical)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(canonical),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.test",
            "commit",
            "--allow-empty",
            "-m",
            "initial",
        ],
        check=True,
        capture_output=True,
    )
    linked = tmp_path / "temporary-worktree"
    subprocess.run(
        ["git", "-C", str(canonical), "worktree", "add", "--detach", str(linked)],
        check=True,
        capture_output=True,
    )
    monkeypatch.setattr(mcp_utils, "REPO_ROOT", linked)
    monkeypatch.setenv("AGENT_SMITH_ROOT", "/stale/other-machine/worktree")
    monkeypatch.setenv("AGENT_SMITH_PYTHON", "/stale/other-machine/python")
    metadata = {
        "command": "${AGENT_SMITH_PYTHON}",
        "args": ["${AGENT_SMITH_ROOT}/services/repositories/server.py"],
    }
    monkeypatch.setattr(
        "services.api.models.tool.collect_tools_from_db", lambda _: {"repos": metadata}
    )
    destination = tmp_path / ("client.toml" if agent == "codex" else "client.json")
    destination.write_text(
        'unrelated = "keep"\n' if agent == "codex" else '{"unrelated":"keep"}'
    )
    monkeypatch.setitem(AGENT_TARGETS[agent], "mcp_file", str(destination))
    assert mcp_utils.sync_mcp(agent, dry_run=False) == []
    data = (
        tomllib.loads(destination.read_text())
        if agent == "codex"
        else json.loads(destination.read_text())
    )
    assert data["unrelated"] == "keep"
    configured = data[AGENT_TARGETS[agent]["mcp_key"]]["repos"]
    assert configured["command"] == str(canonical / ".venv/bin/python")
    assert configured["args"] == [str(canonical / "services/repositories/server.py")]
    assert "temporary-worktree" not in str(configured)


def test_cleanup_server_is_not_exposed_by_dashboard_http_mounts():
    from services.api.app import MCP_SERVERS

    assert not any(mcp.name.startswith("repos - ") for mcp in MCP_SERVERS)
