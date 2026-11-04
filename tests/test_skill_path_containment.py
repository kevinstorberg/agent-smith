from __future__ import annotations

from pathlib import Path

import pytest

from scripts.shared.fs import _sync_skills_to_target


def tree_snapshot(root: Path) -> dict[str, tuple[str, bytes | str]]:
    return {
        str(path.relative_to(root)): (
            ("symlink", str(path.readlink()))
            if path.is_symlink()
            else ("directory", "")
            if path.is_dir()
            else ("file", path.read_bytes())
        )
        for path in root.rglob("*")
    }


def skill(files: object = None) -> dict:
    return {
        "skill_md": "---\nname: fixture\n---\nComplete skill body.\n",
        "files": {} if files is None else files,
    }


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize(
    "bad_path",
    [
        "../sibling.txt",
        "../../outside/sentinel.txt",
        "absolute",
        "C:\\outside\\sentinel.txt",
        "C:sentinel.txt",
        "\\\\host\\share\\sentinel.txt",
        "..\\outside\\sentinel.txt",
        "",
        ".",
        "bad\0path",
    ],
)
def test_skill_file_escape_is_rejected_before_any_publication(
    tmp_path, dry_run, bad_path
):
    destination = tmp_path / "skills"
    stale = destination / "stale"
    stale.mkdir(parents=True)
    (stale / "SKILL.md").write_text("Unchanged stale fixture.")
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("Outside fixture must survive.")
    path = str(sentinel) if bad_path == "absolute" else bad_path
    desired = {
        "a_valid": skill({"references/valid.md": "Valid nested reference."}),
        "z_invalid": skill({path: "Unsafe content."}),
    }
    before = tree_snapshot(tmp_path)

    with pytest.raises(ValueError, match="path|skill"):
        _sync_skills_to_target(desired, destination, dry_run)

    assert tree_snapshot(tmp_path) == before


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("location", ["skill", "body", "parent", "leaf"])
def test_skill_symlink_destinations_are_rejected_before_any_publication(
    tmp_path, dry_run, location
):
    destination = tmp_path / "skills"
    destination.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("Outside fixture must survive.")
    target = destination / "z_invalid"
    if location == "skill":
        target.symlink_to(outside, target_is_directory=True)
    else:
        target.mkdir()
        if location == "body":
            (target / "SKILL.md").symlink_to(sentinel)
        elif location == "parent":
            (target / "references").symlink_to(outside, target_is_directory=True)
        else:
            (target / "references").mkdir()
            (target / "references" / "sentinel.txt").symlink_to(sentinel)
    desired = {
        "a_valid": skill(),
        "z_invalid": skill({"references/sentinel.txt": "Unsafe content."}),
    }
    before = tree_snapshot(tmp_path)

    with pytest.raises(ValueError, match="path|skill|symbolic"):
        _sync_skills_to_target(desired, destination, dry_run)

    assert tree_snapshot(tmp_path) == before


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize(
    "malformed",
    [
        None,
        [],
        {"fixture": None},
        {"fixture": []},
        {"fixture": {"skill_md": 4}},
        {"fixture": skill([])},
        {"fixture": skill({4: "text"})},
        {"fixture": skill({"file.txt": 4})},
        {"../outside": skill()},
        {"nested/fixture": skill()},
    ],
)
def test_malformed_skill_publication_is_rejected_before_writes(
    tmp_path, dry_run, malformed
):
    before = tree_snapshot(tmp_path)

    with pytest.raises(ValueError, match="skill|path|files"):
        _sync_skills_to_target(malformed, tmp_path / "skills", dry_run)

    assert tree_snapshot(tmp_path) == before


def test_skill_publication_preserves_complete_nested_file_contents(tmp_path):
    desired = {
        "fixture": skill(
            {
                "scripts/run.py": "print('complete script')\n",
                "references/guide.md": "# Complete guide\n\nKeep all content.\n",
            }
        )
    }

    _sync_skills_to_target(desired, tmp_path / "skills", False)

    target = tmp_path / "skills" / "fixture"
    assert (target / "SKILL.md").read_text() == desired["fixture"]["skill_md"]
    for name, content in desired["fixture"]["files"].items():
        assert (target / name).read_text() == content


def test_valid_skill_dry_run_creates_no_files_or_directories(tmp_path):
    _sync_skills_to_target(
        {"fixture": skill({"references/guide.md": "Complete guide."})},
        tmp_path / "skills",
        True,
    )

    assert list(tmp_path.iterdir()) == []


def test_configured_skill_root_may_be_an_intentional_symlink(tmp_path):
    configured_root = tmp_path / "configured-skills"
    real_root = tmp_path / "real-skills"
    real_root.mkdir()
    configured_root.symlink_to(real_root, target_is_directory=True)

    _sync_skills_to_target({"fixture": skill()}, configured_root, False)

    assert (real_root / "fixture" / "SKILL.md").read_text() == skill()["skill_md"]
