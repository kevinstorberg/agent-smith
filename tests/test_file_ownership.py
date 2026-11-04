from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.shared import agents, fs
from scripts.shared.atomic_json import exclusive_file_lock
from scripts.shared.file_ownership import LOCK_NAME, STATE_NAME, publish_files
from services.api.models import agent as agent_model


def snapshot(root: Path) -> dict:
    return {
        str(path.relative_to(root)): (
            path.read_bytes() if path.is_file() else None,
            path.stat().st_mtime_ns,
            path.stat().st_mode,
        )
        for path in root.rglob("*")
    }


@pytest.fixture
def publication(tmp_path, monkeypatch):
    root = tmp_path / "client"
    root.mkdir()
    cfg = {
        **agents.AGENT_TARGETS["claude"],
        "rules_file": str(root / "CLAUDE.md"),
        "rules_dir": str(root / "rules"),
        "skills_dir": str(root / "skills"),
        "agents_dir": str(root / "agents"),
        "mcp_file": str(root / "mcp.json"),
    }
    monkeypatch.setattr(agents, "AGENT_TARGETS", {"claude": cfg})
    monkeypatch.setattr(agents, "_unsync_repo_targets", lambda agent: [])
    items = [{"name": "managed", "content": {"body": "managed body", "metadata": {}}}]
    monkeypatch.setattr(fs, "_resolve_and_partition", lambda *args: (items, {}))
    monkeypatch.setattr(fs, "_collect_skill_clones", lambda *args: ({}, {}))
    monkeypatch.setattr(
        agent_model,
        "collect_agents_from_db",
        lambda agent: {
            row["name"]: {"body": row["content"]["body"], "metadata": {}}
            for row in items
        },
    )
    return root, items


def publish(kind: str) -> None:
    {"rule": fs.sync_rules, "skill": fs.sync_skills, "agent": fs.sync_agents}[kind](
        "claude", False
    )


def output(root: Path, kind: str) -> Path:
    return (
        root
        / {
            "rule": "rules/managed.md",
            "skill": "skills/managed/SKILL.md",
            "agent": "agents/managed.md",
        }[kind]
    )


@pytest.mark.parametrize("kind", ["rule", "skill", "agent"])
def test_full_publication_and_unsync_preserve_manual_artifacts(publication, kind):
    root, _ = publication
    folder = root / {"rule": "rules", "skill": "skills", "agent": "agents"}[kind]
    manual = folder / (".system/tool/SKILL.md" if kind == "skill" else "manual.md")
    manual.parent.mkdir(parents=True)
    manual.write_text("manual sentinel")
    before = (manual.read_bytes(), manual.stat().st_mtime_ns)

    publish(kind)
    assert output(root, kind).is_file()
    assert (manual.read_bytes(), manual.stat().st_mtime_ns) == before
    agents.unsync_agent("claude")
    assert not output(root, kind).exists()
    assert (manual.read_bytes(), manual.stat().st_mtime_ns) == before


@pytest.mark.parametrize("kind", ["rule", "skill", "agent"])
def test_only_known_unchanged_files_retire_not_nested_extras(publication, kind):
    root, items = publication
    publish(kind)
    managed = output(root, kind)
    extra = managed.parent / "private-notes.txt"
    extra.write_text("keep")
    items.clear()
    publish(kind)
    assert not managed.exists()
    assert extra.read_text() == "keep"


@pytest.mark.parametrize("kind", ["rule", "skill", "agent"])
def test_identical_existing_files_remain_unclaimed(publication, kind):
    root, _ = publication
    desired = output(root, kind)
    desired.parent.mkdir(parents=True)
    desired.write_text("managed body" + ("\n" if kind == "agent" else ""))
    before = desired.stat().st_mtime_ns
    publish(kind)
    agents.unsync_agent("claude")
    assert desired.exists()
    assert desired.stat().st_mtime_ns == before


@pytest.mark.parametrize("kind", ["rule", "skill", "agent"])
def test_foreign_collision_aborts_before_writing(publication, kind):
    root, _ = publication
    desired = output(root, kind)
    desired.parent.mkdir(parents=True)
    desired.write_text("foreign content")
    before = snapshot(root)
    with pytest.raises(ValueError, match="[Cc]ollision"):
        publish(kind)
    assert snapshot(root) == before


@pytest.mark.parametrize("kind", ["rule", "skill", "agent"])
def test_modified_owned_file_blocks_overwrite_and_survives_unsync(publication, kind):
    root, _ = publication
    publish(kind)
    desired = output(root, kind)
    desired.write_text("locally edited")
    before = desired.stat().st_mtime_ns
    with pytest.raises(ValueError, match="[Cc]ollision"):
        publish(kind)
    agents.unsync_agent("claude")
    assert desired.read_text() == "locally edited"
    assert desired.stat().st_mtime_ns == before


def test_unsync_without_manifest_preserves_all_legacy_files(publication):
    root, _ = publication
    (root / "CLAUDE.md").write_text("legacy rules")
    for relative in ("rules/manual.md", "skills/manual/SKILL.md", "agents/manual.md"):
        destination = root / relative
        destination.parent.mkdir(parents=True)
        destination.write_text("legacy")
    before = snapshot(root)
    assert agents.unsync_agent("claude") == []
    assert snapshot(root) == before


def test_skill_preview_does_not_create_any_files_or_metadata(publication):
    root, _ = publication
    before = snapshot(root)
    fs.sync_skills("claude", True)
    assert snapshot(root) == before


def write_outputs(root, owner="claude:skills", outputs=None, **kwargs):
    return publish_files(
        root,
        owner,
        {"managed/SKILL.md": "body"} if outputs is None else outputs,
        write=fs.atomic_write,
        **kwargs,
    )


def test_repeated_publication_is_byte_and_mtime_idempotent(tmp_path):
    write_outputs(tmp_path)
    before = snapshot(tmp_path)
    write_outputs(tmp_path)
    assert snapshot(tmp_path) == before


def test_other_publisher_reference_protects_shared_file_until_last_retirement(tmp_path):
    write_outputs(tmp_path, "claude:skills")
    write_outputs(tmp_path, "codex:skills")
    write_outputs(tmp_path, "claude:skills", {})
    assert (tmp_path / "managed/SKILL.md").read_text() == "body"
    write_outputs(tmp_path, "codex:skills", {})
    assert not (tmp_path / "managed/SKILL.md").exists()


def test_conflicting_other_owner_cannot_change_shared_content(tmp_path):
    write_outputs(tmp_path, "claude:skills")
    before = snapshot(tmp_path)
    with pytest.raises(ValueError, match="Collision with another publisher"):
        write_outputs(tmp_path, "codex:skills", {"managed/SKILL.md": "different"})
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("replacement", ["edited", "symlink", "directory"])
def test_retired_replaced_file_is_preserved(tmp_path, replacement):
    write_outputs(tmp_path)
    path = tmp_path / "managed/SKILL.md"
    if replacement == "edited":
        path.write_text("local")
    elif replacement == "symlink":
        target = tmp_path / "outside.txt"
        target.write_text("outside")
        path.unlink()
        path.symlink_to(target)
    else:
        path.unlink()
        path.mkdir()
    before = path.lstat()
    write_outputs(tmp_path, outputs={})
    assert path.lstat().st_mtime_ns == before.st_mtime_ns
    assert path.lstat().st_ino == before.st_ino
    if replacement == "symlink":
        assert target.read_text() == "outside"


@pytest.mark.parametrize(
    "state",
    [
        "bad json",
        "[]",
        '{"version": true, "owners": {}}',
        '{"version": 2, "owners": {}}',
        '{"version": 1, "owners": {"a": {"../escape": "' + "0" * 64 + '"}}}',
        '{"version": 1, "owners": {"a": {"safe.md": "bad"}}}',
    ],
)
def test_invalid_ownership_state_fails_before_any_writes(tmp_path, state):
    (tmp_path / STATE_NAME).write_text(state)
    before = snapshot(tmp_path)
    with pytest.raises(ValueError):
        write_outputs(tmp_path)
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize(
    "relative",
    [
        STATE_NAME,
        LOCK_NAME,
        "../escape",
        "/absolute",
        "a/../../escape",
        "a//b",
        "./file",
    ],
)
def test_unsafe_or_reserved_output_fails_without_side_effects(tmp_path, relative):
    before = snapshot(tmp_path)
    with pytest.raises(ValueError):
        write_outputs(tmp_path, outputs={"valid.md": "first", relative: "bad"})
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize(
    "special", [STATE_NAME, LOCK_NAME, "managed", "managed/SKILL.md"]
)
def test_active_symbolic_paths_fail_without_following_links(tmp_path, special):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SKILL.md").write_text("outside")
    path = tmp_path / special
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(outside, target_is_directory=True)
    before = (outside / "SKILL.md").read_bytes()
    with pytest.raises(ValueError, match="symbolic"):
        write_outputs(tmp_path)
    assert (outside / "SKILL.md").read_bytes() == before


def test_lock_contention_refuses_second_publisher(tmp_path):
    with exclusive_file_lock(tmp_path / LOCK_NAME):
        with pytest.raises(RuntimeError, match="already running"):
            write_outputs(tmp_path)
    assert not (tmp_path / STATE_NAME).exists()
    assert not (tmp_path / "managed").exists()


def test_failed_publication_never_retires_old_files_or_claims_unwritten_paths(tmp_path):
    write_outputs(tmp_path, outputs={"old.md": "old"})
    state_before = (tmp_path / STATE_NAME).read_bytes()

    def failing_writer(path, content):
        if path.name == "second.md":
            raise OSError("synthetic write failure")
        return fs.atomic_write(path, content)

    with pytest.raises(OSError, match="synthetic"):
        publish_files(
            tmp_path,
            "claude:skills",
            {"first.md": "first", "second.md": "second"},
            write=failing_writer,
        )
    assert (tmp_path / "old.md").read_text() == "old"
    assert not (tmp_path / "second.md").exists()
    assert (tmp_path / STATE_NAME).read_bytes() == state_before
    assert "first.md" not in json.loads(state_before)["owners"]["claude:skills"]


def test_failed_manifest_commit_leaves_new_file_unclaimed(tmp_path, monkeypatch):
    from scripts.shared import file_ownership

    def fail_state(*args):
        raise OSError("synthetic state failure")

    monkeypatch.setattr(file_ownership, "atomic_write_json", fail_state)
    with pytest.raises(OSError, match="synthetic state"):
        write_outputs(tmp_path)
    assert (tmp_path / "managed/SKILL.md").read_text() == "body"
    assert not (tmp_path / STATE_NAME).exists()


def test_repo_retirement_uses_same_conservative_ownership(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from services import db

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, query, parameters):
            assert parameters == ("claude",)

        def fetchall(self):
            return [{"repo": str(tmp_path)}]

    class Connection:
        def cursor(self, **kwargs):
            return Cursor()

    @contextmanager
    def connection():
        yield Connection()

    monkeypatch.setattr(db, "get_connection", connection)
    cfg = agents.repo_config("claude", str(tmp_path))
    root = Path(cfg["skills_dir"])
    write_outputs(root)
    manual = root / ".system/manual/SKILL.md"
    manual.parent.mkdir(parents=True)
    manual.write_text("keep")
    removed = agents._unsync_repo_targets("claude")
    assert str(root / "managed/SKILL.md") in removed
    assert not (root / "managed/SKILL.md").exists()
    assert manual.read_text() == "keep"


def test_alias_roots_share_ownership_and_preserve_other_owner(tmp_path):
    root = tmp_path / "real"
    root.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    write_outputs(root, "claude:skills")
    write_outputs(alias, "codex:skills")
    write_outputs(root, "claude:skills", {})
    assert (alias / "managed/SKILL.md").read_text() == "body"
    write_outputs(alias, "codex:skills", {})
    assert not (root / "managed/SKILL.md").exists()


def test_empty_unknown_publication_does_not_create_destination(tmp_path):
    root = tmp_path / "absent"
    write_outputs(root, outputs={})
    assert not root.exists()


def test_publication_freezes_desired_content_before_writer_side_effects(tmp_path):
    desired = {"first.md": "first", "second.md": "captured"}

    def writer(path, content):
        desired["second.md"] = "later"
        return fs.atomic_write(path, content)

    publish_files(tmp_path, "claude:skills", desired, write=writer)
    assert (tmp_path / "second.md").read_text() == "captured"


def test_parent_file_collision_preflights_all_outputs(tmp_path):
    (tmp_path / "parent").write_text("foreign")
    before = snapshot(tmp_path)
    with pytest.raises(ValueError, match="Collision"):
        write_outputs(
            tmp_path, outputs={"first.md": "first", "parent/second.md": "second"}
        )
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("reverse", [False, True])
def test_desired_parent_child_collision_preflights_all_outputs(tmp_path, reverse):
    before = snapshot(tmp_path)
    outputs = [("parent", "first"), ("parent/child.md", "second")]
    if reverse:
        outputs.reverse()
    with pytest.raises(ValueError, match="Collision"):
        write_outputs(tmp_path, outputs=dict(outputs))
    assert snapshot(tmp_path) == before
