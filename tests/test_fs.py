from __future__ import annotations

from pathlib import Path

from scripts.shared.fs import (
    atomic_write,
    collect_md_files,
    collect_skill_dirs,
    compose_parts,
    sync_skill_dirs,
)


def test_collect_md_files_from_directory(harness_dir: Path):
    files = collect_md_files(["rules/shared/"], harness_dir)
    names = [f.name for f in files]
    assert "aaa.md" in names
    assert "bbb.md" in names
    assert ".hidden.md" not in names


def test_collect_md_files_from_file(harness_dir: Path):
    files = collect_md_files(["rules/shared/aaa.md"], harness_dir)
    assert len(files) == 1
    assert files[0].name == "aaa.md"


def test_collect_md_files_missing_source(harness_dir: Path):
    files = collect_md_files(["nonexistent/"], harness_dir)
    assert files == []


def test_compose_parts(harness_dir: Path):
    files = collect_md_files(["rules/shared/"], harness_dir)
    result = compose_parts(files)
    assert "Content A." in result
    assert "Content B." in result
    assert result.index("Content A.") < result.index("Content B.")


def test_compose_parts_footer_marker(tmp_path: Path):
    (tmp_path / "a.md").write_text("top\n<!-- footer -->\nbottom")
    (tmp_path / "b.md").write_text("middle")
    files = [tmp_path / "a.md", tmp_path / "b.md"]
    result = compose_parts(files)
    assert result.index("middle") < result.index("bottom")


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


def test_collect_skill_dirs(harness_dir: Path):
    skills = collect_skill_dirs(["skills/shared/"], harness_dir)
    assert "commit" in skills
    assert "pr" in skills


def test_collect_skill_dirs_ignores_non_skill_dirs(tmp_path: Path):
    empty = tmp_path / "skills" / "empty_dir"
    empty.mkdir(parents=True)
    skills = collect_skill_dirs(["skills/"], tmp_path)
    assert skills == {}


def test_sync_skill_dirs_copies_and_prunes(harness_dir: Path, tmp_path: Path):
    dest = tmp_path / "dest_skills"
    skills = collect_skill_dirs(["skills/shared/"], harness_dir)
    sync_skill_dirs(skills, dest, dry_run=False)

    assert (dest / "commit" / "SKILL.md").exists()
    assert (dest / "pr" / "SKILL.md").exists()

    skills_without_pr = {k: v for k, v in skills.items() if k != "pr"}
    sync_skill_dirs(skills_without_pr, dest, dry_run=False)

    assert (dest / "commit" / "SKILL.md").exists()
    assert not (dest / "pr").exists()
