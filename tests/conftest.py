from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def harness_dir(tmp_path: Path) -> Path:
    (tmp_path / ".env").write_text("FOO=bar\nSECRET=hunter2\n# comment\n")

    mcp = tmp_path / "mcp" / "shared"
    mcp.mkdir(parents=True)
    (mcp / "Alpha.json").write_text(json.dumps({"name": "Alpha", "url": "https://a.com/mcp"}))
    (mcp / "Beta.json").write_text(
        json.dumps({"name": "Beta", "url": "https://b.com/mcp", "headers": {"Authorization": "Bearer ${SECRET}"}})
    )

    rules = tmp_path / "rules" / "shared"
    rules.mkdir(parents=True)
    (rules / "aaa.md").write_text("# Rule A\nContent A.\n")
    (rules / "bbb.md").write_text("# Rule B\nContent B.\n")
    (rules / ".hidden.md").write_text("should be skipped")

    skills = tmp_path / "skills" / "shared"
    skills.mkdir(parents=True)
    skill_a = skills / "commit"
    skill_a.mkdir()
    (skill_a / "SKILL.md").write_text("---\nname: commit\n---\nCommit skill.\n")
    skill_b = skills / "pr"
    skill_b.mkdir()
    (skill_b / "SKILL.md").write_text("---\nname: pr\n---\nPR skill.\n")

    return tmp_path
