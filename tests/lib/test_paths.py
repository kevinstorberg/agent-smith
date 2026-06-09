import pytest

from lib.agent_smith_core.paths import get_repo_root


def test_get_repo_root_finds_marker_from_nested_file(tmp_path):
    repo_root = tmp_path / "repo"
    nested = repo_root / "src" / "features" / "deep"
    nested.mkdir(parents=True)
    (repo_root / "pyproject.toml").write_text("[project]\nname = 'example'\n")
    module_file = nested / "module.py"
    module_file.write_text("")

    assert get_repo_root(str(module_file)) == repo_root


def test_get_repo_root_accepts_directory_path(tmp_path):
    repo_root = tmp_path / "repo"
    nested = repo_root / "config" / "graphs"
    nested.mkdir(parents=True)
    (repo_root / "alembic.ini").write_text("")

    assert get_repo_root(str(nested)) == repo_root


def test_get_repo_root_fails_when_no_marker_exists(tmp_path):
    module_file = tmp_path / "src" / "module.py"
    module_file.parent.mkdir()
    module_file.write_text("")

    with pytest.raises(RuntimeError, match="Could not find repository root"):
        get_repo_root(str(module_file))
