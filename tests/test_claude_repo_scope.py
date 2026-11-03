from __future__ import annotations

import os
import subprocess

import pytest

from scripts.shared import claude_repo_scope


def _git(directory, *arguments):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    return subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgSign=false", "-C", str(directory), *arguments],
        check=True, capture_output=True, text=True, timeout=3, env=env,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    directory = tmp_path / "canonical-project"
    directory.mkdir()
    _git(directory, "init", "--template=")
    _git(directory, "-c", "user.name=Scope Test", "-c", "user.email=scope@example.invalid", "commit", "--allow-empty", "-m", "fixture")
    return directory.resolve()


def test_main_repo_nested_directory_and_file_use_same_scope(tmp_path, repo):
    directory = repo / "nested"
    directory.mkdir()
    file = directory / "module.py"
    file.write_text("pass\n")
    expected = {"repo": repo.name, "root": str(repo), "canonical_root": str(repo)}
    for path in (repo, directory, file):
        assert claude_repo_scope.resolve_repo(str(path), (tmp_path.resolve(),)) == expected


def test_linked_worktree_keeps_main_repo_scope_and_current_worktree_root(tmp_path, repo):
    worktree = tmp_path / "branch-alias"
    _git(repo, "worktree", "add", "--detach", str(worktree))
    directory = worktree / "nested"
    directory.mkdir()
    assert claude_repo_scope.resolve_repo(str(directory), (tmp_path.resolve(),)) == {
        "repo": repo.name, "root": str(worktree.resolve()), "canonical_root": str(repo),
    }


def test_submodule_style_git_directory_does_not_alias_superproject(tmp_path, repo):
    submodule = repo / "submodule"
    submodule.mkdir()
    git_directory = repo / ".git" / "modules" / "submodule"
    git_directory.parent.mkdir()
    _git(submodule, "init", "--template=", f"--separate-git-dir={git_directory}")
    assert claude_repo_scope.resolve_repo(str(submodule), (tmp_path.resolve(),)) == {
        "repo": "submodule", "root": str(submodule), "canonical_root": str(submodule),
    }


def test_non_repo_does_not_turn_directory_name_into_scope(tmp_path):
    path = tmp_path / "repos"
    path.mkdir()
    assert claude_repo_scope.resolve_repo(str(path), (tmp_path.resolve(),)) is None


def test_symlink_escape_and_missing_paths_are_rejected_without_git(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    (allowed / "escape").symlink_to(outside, target_is_directory=True)
    calls = []
    monkeypatch.setattr(claude_repo_scope.subprocess, "run", lambda *args, **kwargs: calls.append(args))
    assert claude_repo_scope.resolve_repo(str(allowed / "escape"), (allowed,)) is None
    assert claude_repo_scope.resolve_repo(str(allowed / "missing"), (allowed,)) is None
    assert not calls


def test_outside_path_is_rejected_before_resolving_or_calling_git(tmp_path, monkeypatch):
    from pathlib import Path

    def reject_resolve(*args, **kwargs):
        pytest.fail("Outside path was resolved")

    monkeypatch.setattr(Path, "resolve", reject_resolve)
    assert claude_repo_scope.resolve_repo("/outside/untrusted/network/path", (tmp_path,)) is None
    assert claude_repo_scope.resolve_repo(str(tmp_path / ".." / "outside"), (tmp_path,)) is None
    assert claude_repo_scope.resolve_repo("relative/path", (tmp_path,)) is None


def test_resolution_uses_at_most_two_bounded_git_calls_and_ignores_git_dir_env(tmp_path, repo, monkeypatch):
    run = claude_repo_scope.subprocess.run
    calls = []

    def record(*args, **kwargs):
        calls.append((args, kwargs))
        return run(*args, **kwargs)

    monkeypatch.setattr(claude_repo_scope.subprocess, "run", record)
    monkeypatch.setenv("GIT_DIR", "/outside/other/.git")
    monkeypatch.setenv("GIT_WORK_TREE", "/outside/other")
    assert claude_repo_scope.resolve_repo(str(repo), (tmp_path.resolve(),))["repo"] == repo.name
    assert len(calls) == 2
    for args, kwargs in calls:
        assert args[0][:2] == ["git", "-C"]
        assert kwargs["timeout"] == 0.25
        assert kwargs.get("shell", False) is False
        assert "GIT_DIR" not in kwargs["env"]
        assert "GIT_WORK_TREE" not in kwargs["env"]


def test_git_timeout_is_a_capture_error_instead_of_unknown_scope(tmp_path, repo, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 0.25)

    monkeypatch.setattr(claude_repo_scope.subprocess, "run", timeout)
    with pytest.raises(claude_repo_scope.GitScopeTimeoutError):
        claude_repo_scope.resolve_repo(str(repo), (tmp_path.resolve(),))


def test_missing_git_is_a_capture_error_instead_of_unknown_scope(tmp_path, repo, monkeypatch):
    def missing_git(*args, **kwargs):
        raise FileNotFoundError("synthetic missing Git")

    monkeypatch.setattr(claude_repo_scope.subprocess, "run", missing_git)
    with pytest.raises(claude_repo_scope.GitUnavailableError):
        claude_repo_scope.resolve_repo(str(repo), (tmp_path.resolve(),))
