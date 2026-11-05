from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


def test_repository_cli_help_is_available_without_initializing_services():
    result = subprocess.run(
        [sys.executable, "scripts/repos.py", "--help"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert "--execute" in result.stdout
    assert "--force" in result.stdout
    assert "--delete-remote" in result.stdout


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        ([], {"execute": False, "force": False, "delete_remote": False}),
        (["--force"], {"execute": False, "force": True, "delete_remote": False}),
        (
            ["--execute", "--force", "--delete-remote"],
            {"execute": True, "force": True, "delete_remote": True},
        ),
    ],
)
def test_cli_requires_explicit_execution_and_prints_json(
    monkeypatch, capsys, flags, expected
):
    cli = importlib.import_module("scripts.repos")
    calls = []

    def cleanup(path, **options):
        calls.append((path, options))
        return {"items": [], "errors": [], "summary": {"removed": 0}}

    monkeypatch.setattr(cli, "cleanup_repository", cleanup)
    assert cli.main(["/repository with spaces", *flags]) == 0
    assert calls == [("/repository with spaces", expected)]
    assert json.loads(capsys.readouterr().out)["summary"]["removed"] == 0


def test_cli_reports_partial_failures_with_unsuccessful_exit(monkeypatch, capsys):
    cli = importlib.import_module("scripts.repos")
    report = {
        "items": [{"state": "failed"}],
        "errors": ["branch changed"],
        "summary": {"failed": 1},
    }
    monkeypatch.setattr(cli, "cleanup_repository", lambda *args, **kwargs: report)
    assert cli.main(["/repository", "--execute"]) == 1
    assert json.loads(capsys.readouterr().out) == report


def test_cli_discovery_failure_stays_json(monkeypatch, capsys):
    cli = importlib.import_module("scripts.repos")

    def cleanup(*args, **kwargs):
        raise ValueError("GitHub origin is required")

    monkeypatch.setattr(cli, "cleanup_repository", cleanup)
    assert cli.main(["/repository"]) == 1
    assert "GitHub origin is required" in json.loads(capsys.readouterr().out)["error"]
