from __future__ import annotations

import pytest
from pathlib import Path

from scripts.shared.fs import atomic_write, compose_strings, extract_brief, _compose_agent_file, _sync_skills_to_target


def test_compose_strings_preserves_order():
    items = [("a", "first"), ("b", "second")]
    result = compose_strings(items)
    assert result.index("first") < result.index("second")


def test_compose_strings_with_transform():
    items = [("a", "hello")]
    result = compose_strings(items, transform=lambda text, name: text.upper())
    assert "HELLO" in result


def test_extract_brief_strips_process():
    content = "## Rule\n* **The Rule:** Be good.\n* **Your Process:**\n    1. Step one."
    result = extract_brief(content, Path("~/.claude/rules/test.md"))
    assert "Step one" not in result
    assert "See `~/.claude/rules/test.md`" in result


def test_extract_brief_passthrough_no_marker():
    content = "## Constraints\n* Be concise."
    result = extract_brief(content, Path("~/.claude/rules/test.md"))
    assert result == content


def test_atomic_write_creates_file(tmp_path: Path):
    path = tmp_path / "out.txt"
    changed, msg = atomic_write(path, "hello")
    assert changed is True
    assert path.read_text() == "hello"
    assert "updated" in msg


def test_atomic_write_skips_unchanged(tmp_path: Path):
    path = tmp_path / "out.txt"
    path.write_text("hello")
    changed, msg = atomic_write(path, "hello")
    assert changed is False
    assert "unchanged" in msg


def test_compose_agent_file_with_metadata():
    body = "You are a code reviewer."
    metadata = {"description": "Reviews code", "model": "sonnet"}
    result = _compose_agent_file(body, metadata)
    assert result.startswith("---\n")
    assert "description: Reviews code" in result
    assert "model: sonnet" in result
    assert "You are a code reviewer." in result


def test_compose_agent_file_no_metadata():
    body = "You are a helper."
    result = _compose_agent_file(body, {})
    assert result.strip() == "You are a helper."
    assert "---" not in result


def test_compose_agent_file_with_scoped_rules():
    body = "Agent prompt."
    metadata = {"description": "test"}
    rules = [{"content": {"body": "## Rule 1\nBe good."}}]
    result = _compose_agent_file(body, metadata, scoped_rules=rules)
    assert "# Rules" in result
    assert "## Rule 1" in result


def test_compose_agent_file_no_scoped_rules():
    body = "Agent prompt."
    metadata = {"description": "test"}
    result = _compose_agent_file(body, metadata, scoped_rules=None)
    assert "# Rules" not in result


# ---------------------------------------------------------------------------
# repo_config tests
# ---------------------------------------------------------------------------

class TestRepoConfig:
    def test_claude_paths(self):
        from scripts.shared.agents import repo_config
        paths = repo_config("claude", "/Users/me/proj")
        assert paths["rules_file"] == "/Users/me/proj/.claude/CLAUDE.md"
        assert paths["rules_dir"] == "/Users/me/proj/.claude/rules"
        assert paths["skills_dir"] == "/Users/me/proj/.claude/skills"
        assert paths["agents_dir"] == "/Users/me/proj/.claude/agents"

    def test_codex_paths(self):
        from scripts.shared.agents import repo_config
        paths = repo_config("codex", "/Users/me/proj")
        assert paths["rules_file"] == "/Users/me/proj/AGENTS.md"
        assert paths["skills_dir"] == "/Users/me/proj/.agents/skills"

    def test_gemini_paths(self):
        from scripts.shared.agents import repo_config
        paths = repo_config("gemini", "/Users/me/proj")
        assert paths["rules_file"] == "/Users/me/proj/.gemini/GEMINI.md"
        assert paths["skills_dir"] == "/Users/me/proj/.gemini/skills"

    def test_rejects_relative_path(self):
        from scripts.shared.agents import repo_config
        with pytest.raises(AssertionError, match="absolute"):
            repo_config("claude", "relative/path")

    def test_unknown_agent_returns_empty(self):
        from scripts.shared.agents import repo_config
        paths = repo_config("unknown_agent", "/Users/me/proj")
        assert paths == {}


# ---------------------------------------------------------------------------
# Repo-scoped sync tests
# ---------------------------------------------------------------------------

class TestSyncRulesRepoTarget:
    def test_repo_scoped_rule_writes_to_repo_dir(self, tmp_path: Path):
        """A rule with repo=/some/path should write to <repo>/.claude/rules/, not home."""
        from scripts.shared.fs import _sync_rules_to_target

        items = [("test_rule", "## Test Rule\nBe good.")]
        cfg = {
            "rules_file": str(tmp_path / ".claude" / "CLAUDE.md"),
            "rules_dir": str(tmp_path / ".claude" / "rules"),
        }
        _sync_rules_to_target(items, cfg, dry_run=False)

        rules_file = tmp_path / ".claude" / "CLAUDE.md"
        assert rules_file.exists()
        assert "Test Rule" in rules_file.read_text()

        rule_file = tmp_path / ".claude" / "rules" / "test_rule.md"
        assert rule_file.exists()

    def test_global_target_writes_to_home_style_dir(self, tmp_path: Path):
        from scripts.shared.fs import _sync_rules_to_target

        items = [("global_rule", "## Global\nStay consistent.")]
        cfg = {
            "rules_file": str(tmp_path / "CLAUDE.md"),
        }
        _sync_rules_to_target(items, cfg, dry_run=False)

        assert (tmp_path / "CLAUDE.md").exists()
        assert "Global" in (tmp_path / "CLAUDE.md").read_text()


# ---------------------------------------------------------------------------
# Skill clone tests
# ---------------------------------------------------------------------------

class TestSkillClone:
    def test_clone_writes_skill_directory(self, tmp_path: Path):
        skills = {"my_rule": {"skill_md": "## Cloned Rule\nContent here.", "files": {}}}
        _sync_skills_to_target(skills, tmp_path, dry_run=False)

        skill_md = tmp_path / "my_rule" / "SKILL.md"
        assert skill_md.exists()
        assert "Cloned Rule" in skill_md.read_text()

    def test_real_skill_wins_over_clone(self, tmp_path: Path):
        clones = {"shared": {"skill_md": "clone body", "files": {}}}
        real = {"shared": {"skill_md": "real body", "files": {}}}
        merged = {**clones, **real}
        _sync_skills_to_target(merged, tmp_path, dry_run=False)

        content = (tmp_path / "shared" / "SKILL.md").read_text()
        assert "real body" in content
        assert "clone body" not in content

    def test_clone_with_no_files(self, tmp_path: Path):
        skills = {"empty_clone": {"skill_md": "body", "files": {}}}
        _sync_skills_to_target(skills, tmp_path, dry_run=False)

        entries = list((tmp_path / "empty_clone").iterdir())
        assert len(entries) == 1
        assert entries[0].name == "SKILL.md"
