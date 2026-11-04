from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

from scripts.shared import agents, fs, hook_utils, mcp_utils, paths
from services import db
from services.api.models import agent as agent_model
from services.api.models import hook as hook_model
from services.api.models import tool as tool_model
from services.api.models.hook import HookSettings
from services.api.models.shared import harness


CASES = [
    ("rule", False),
    ("rule", True),
    ("skill", False),
    ("tool", False),
    ("hook", False),
    ("agent", False),
]


def tree_snapshot(root: Path) -> dict:
    result = {}
    for path in sorted(root.rglob("*")):
        stat = path.stat()
        result[str(path.relative_to(root))] = (
            path.read_bytes() if path.is_file() else None,
            stat.st_mode,
            stat.st_mtime_ns,
            stat.st_ino,
        )
    return result


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    dest = tmp_path / "client"
    cfg = {
        **agents.AGENT_TARGETS["claude"],
        "rules_file": str(dest / "CLAUDE.md"),
        "rules_dir": str(dest / "rules"),
        "skills_dir": str(dest / "skills"),
        "agents_dir": str(dest / "agents"),
        "mcp_file": str(dest / "mcp.json"),
        "hooks_file": str(dest / "settings.json"),
    }
    targets = {"claude": cfg}
    for module in (agents, hook_utils, mcp_utils):
        monkeypatch.setattr(module, "AGENT_TARGETS", targets)
    monkeypatch.setattr(mcp_utils, "REPO_ROOT", tmp_path)
    initial = {
        "CLAUDE.md": "existing rules\n",
        "rules/manual.md": "manual rule\n",
        "skills/manual/SKILL.md": "manual skill\n",
        "agents/manual.md": "manual agent\n",
        "mcp.json": json.dumps(
            {
                "keep": True,
                "mcpServers": {"manual": {"url": "https://manual.invalid/mcp"}},
            }
        ),
        "settings.json": json.dumps({"keep": True, "hooks": {"Manual": []}}),
    }
    for relative, content in initial.items():
        path = dest / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    monkeypatch.setattr(db, "init_db", lambda: None)
    monkeypatch.setattr(paths, "bootstrap", lambda: None)
    monkeypatch.setenv("DEVICE_NAME", "preview-test")
    monkeypatch.setattr(sys, "path", list(sys.path))
    spec = importlib.util.spec_from_file_location(
        "item_sync_preview_cli", Path(__file__).resolve().parents[1] / "scripts/sync.py"
    )
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    return dest, cli


def configure_item(monkeypatch, item_type: str, clone: bool) -> None:
    item = {
        "id": 17,
        "name": "selected",
        "agents": ["claude"],
        "clone_as_skill": clone,
        "configs": [
            {
                "device": "*",
                "repo": "*",
                "agents": ["claude"],
                "enabled": True,
                "exclude": False,
            }
        ],
        "content": {
            "body": "selected content\n",
            "metadata": {"files": {"references/note.txt": "reference content\n"}},
        },
    }
    monkeypatch.setattr(harness, "get_item_by_id", lambda kind, identifier: item)
    monkeypatch.setattr(
        harness, "list_items_full", lambda kind: [item] if kind == item_type else []
    )
    monkeypatch.setattr(
        "services.api.models.harness_config.list_configs", lambda *args: item["configs"]
    )
    monkeypatch.setattr(
        tool_model,
        "collect_tools_from_db",
        lambda agent: {"selected": {"url": "https://selected.invalid/mcp"}},
    )
    monkeypatch.setattr(
        hook_model, "collect_hook_settings_from_db", lambda agent: HookSettings({}, [])
    )
    monkeypatch.setattr(
        agent_model,
        "collect_agents_from_db",
        lambda agent: {"selected": {"body": "selected agent\n", "metadata": {}}},
    )


@pytest.mark.parametrize("invalid", [None, "false", 0, 1])
def test_per_item_rejects_nonboolean_preview_before_reading_or_publishing(
    deployment, monkeypatch, invalid
):
    dest, _ = deployment
    before = tree_snapshot(dest)

    def forbidden_read(*args):
        pytest.fail("invalid dry_run reached the database")

    monkeypatch.setattr(harness, "get_item_by_id", forbidden_read)

    with pytest.raises(ValueError, match="dry_run must be a boolean"):
        fs.sync_item("rule", 17, dry_run=invalid)

    assert tree_snapshot(dest) == before


@pytest.mark.parametrize(("item_type", "clone"), CASES)
def test_per_item_cli_dry_run_preserves_deployment_tree(
    deployment, monkeypatch, capsys, item_type, clone
):
    dest, cli = deployment
    configure_item(monkeypatch, item_type, clone)
    before = tree_snapshot(dest)
    monkeypatch.setattr(
        sys,
        "argv",
        ["sync.py", "--dry-run", "--item-type", item_type, "--item-id", "17"],
    )

    assert cli.main() == 0

    assert tree_snapshot(dest) == before
    output = capsys.readouterr().out
    assert "would" in output.lower()
    assert "Would sync" in output


@pytest.mark.parametrize(("item_type", "clone"), CASES)
def test_per_item_default_still_publishes_to_temporary_targets(
    deployment, monkeypatch, item_type, clone
):
    dest, _ = deployment
    configure_item(monkeypatch, item_type, clone)

    result = fs.sync_item(item_type, 17, "preview-test")

    assert result["success"] is True
    assert result["message"].startswith("Synced to ")
    if item_type == "rule":
        assert (dest / "rules/selected.md").read_text() == "selected content\n"
        if clone:
            assert (
                dest / "skills/selected/SKILL.md"
            ).read_text() == "selected content\n"
    elif item_type == "skill":
        assert (dest / "skills/selected/SKILL.md").read_text() == "selected content\n"
        assert (
            dest / "skills/selected/references/note.txt"
        ).read_text() == "reference content\n"
    elif item_type == "tool":
        assert (
            json.loads((dest / "mcp.json").read_text())["mcpServers"]["selected"]["url"]
            == "https://selected.invalid/mcp"
        )
    elif item_type == "hook":
        assert json.loads((dest / "settings.json").read_text())["hooks"] == {}
    else:
        assert (dest / "agents/selected.md").read_text() == "selected agent\n"
