from __future__ import annotations

import subprocess
from pathlib import Path

from lib.agent_smith_core.paths import get_repo_root
from src.settings import Settings


def test_agent_smith_enabled_flag_is_removed_from_runtime_and_docs():
    root = get_repo_root(__file__)
    checked_paths = [
        root / ".env.default",
        root / "README.md",
    ]

    assert not hasattr(Settings(_env_file=None), "AGENT_SMITH_ENABLED")
    for path in checked_paths:
        assert "AGENT_SMITH_ENABLED" not in path.read_text(encoding="utf-8")


def test_readme_is_agent_smith_branded():
    root = get_repo_root(__file__)
    readme = (root / "README.md").read_text(encoding="utf-8")

    assert "# agent-smith" in readme


def test_repository_tracks_no_python_cache_artifacts():
    root = Path(get_repo_root(__file__))
    result = subprocess.run(
        ["git", "ls-files", "*__pycache__*", "*.pyc"],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
    )

    assert result.stdout == ""
