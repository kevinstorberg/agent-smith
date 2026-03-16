"""Tests for scripts/shared/mcp_utils.py."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.shared.mcp_utils import collect_mcp_servers


def test_collect_loads_and_strips_name(harness_dir: Path):
    servers = collect_mcp_servers(["mcp/shared/"], harness_dir)
    assert "Alpha" in servers
    assert "url" in servers["Alpha"]
    assert "name" not in servers["Alpha"]


def test_collect_expands_env_vars(harness_dir: Path, monkeypatch: object):
    monkeypatch.setenv("SECRET", "tok_123")
    servers = collect_mcp_servers(["mcp/shared/"], harness_dir)
    assert servers["Beta"]["headers"]["Authorization"] == "Bearer tok_123"


def test_collect_later_source_overrides(tmp_path: Path):
    base = tmp_path / "base"
    base.mkdir()
    (base / "X.json").write_text(json.dumps({"name": "X", "url": "https://old.com"}))

    override = tmp_path / "override"
    override.mkdir()
    (override / "X.json").write_text(json.dumps({"name": "X", "url": "https://new.com"}))

    servers = collect_mcp_servers(["base/", "override/"], tmp_path)
    assert servers["X"]["url"] == "https://new.com"


def test_collect_skips_missing_dirs(tmp_path: Path):
    servers = collect_mcp_servers(["nonexistent/"], tmp_path)
    assert servers == {}


def test_collect_excludes_disabled_server(harness_dir: Path, monkeypatch: object):
    monkeypatch.setenv("Alpha_ENABLED", "false")
    servers = collect_mcp_servers(["mcp/shared/"], harness_dir)
    assert "Alpha" not in servers
    assert "Beta" in servers
