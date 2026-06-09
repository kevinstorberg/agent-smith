from __future__ import annotations

from pathlib import Path

import pytest

from db.unit_of_work import unit_of_work
from src.agent_smith.services.harness import HarnessService
from src.agent_smith.services.sync import AgentSmithSyncService
from src.settings import reset_settings


@pytest.mark.asyncio
async def test_single_item_sync_dry_run_does_not_write_files(clean_agent_smith_db, monkeypatch, tmp_path):
    sync_root = tmp_path / "sync-root"
    monkeypatch.setenv("AGENT_SMITH_SYNC_ROOT", str(sync_root))
    reset_settings()
    async with unit_of_work() as uow:
        item = await HarnessService().create_item(
            uow,
            "rule",
            name="dry_run_rule",
            content={"body": "Do not write this in dry-run."},
            project=None,
            agents=["codex"],
            sort_key=None,
            enabled=True,
        )

    message = await AgentSmithSyncService().sync_item(item_type="rule", item_id=item["id"], dry_run=True)

    assert "would " in message
    assert not sync_root.exists()


@pytest.mark.asyncio
async def test_single_item_sync_writes_to_sandbox_by_default(clean_agent_smith_db, monkeypatch, tmp_path):
    sync_root = tmp_path / "sync-root"
    monkeypatch.setenv("AGENT_SMITH_SYNC_ROOT", str(sync_root))
    reset_settings()
    async with unit_of_work() as uow:
        item = await HarnessService().create_item(
            uow,
            "rule",
            name="write_rule",
            content={"body": "Write this rule."},
            project=None,
            agents=["codex"],
            sort_key=None,
            enabled=True,
        )

    message = await AgentSmithSyncService().sync_item(item_type="rule", item_id=item["id"])

    assert "Synced to 1 agent" in message
    written = Path(sync_root / ".codex" / "AGENTS.md")
    assert written.exists()
    assert "Write this rule." in written.read_text(encoding="utf-8")
