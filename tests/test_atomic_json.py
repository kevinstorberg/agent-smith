from __future__ import annotations

import json
import os
import stat

import pytest

from scripts.shared import atomic_json


def test_atomic_json_creates_private_file_and_preserves_existing_mode(tmp_path):
    path = tmp_path / "private" / "state.json"
    assert atomic_json.atomic_write_json(path, {"value": "café"})
    assert json.loads(path.read_text()) == {"value": "café"}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    path.chmod(0o640)
    assert atomic_json.atomic_write_json(path, {"value": "updated"})
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    modified = path.stat().st_mtime_ns
    assert not atomic_json.atomic_write_json(path, {"value": "updated"})
    assert path.stat().st_mtime_ns == modified


def test_atomic_json_failed_replace_keeps_original_and_cleans_temp(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    atomic_json.atomic_write_json(path, {"value": "old"})

    def fail_replace(source, destination):
        assert source != destination
        assert os.path.dirname(source) == str(tmp_path)
        raise OSError("synthetic replacement failure")

    monkeypatch.setattr(atomic_json.os, "replace", fail_replace)
    with pytest.raises(OSError, match="synthetic replacement failure"):
        atomic_json.atomic_write_json(path, {"value": "new"})
    assert json.loads(path.read_text()) == {"value": "old"}
    assert list(tmp_path.iterdir()) == [path]


def test_atomic_json_syncs_file_then_replace_then_directory(tmp_path, monkeypatch):
    events = []
    replace = atomic_json.os.replace
    fsync = atomic_json.os.fsync

    def record_sync(descriptor):
        events.append("directory" if stat.S_ISDIR(os.fstat(descriptor).st_mode) else "file")
        fsync(descriptor)

    def record_replace(source, destination):
        events.append("replace")
        replace(source, destination)

    monkeypatch.setattr(atomic_json.os, "fsync", record_sync)
    monkeypatch.setattr(atomic_json.os, "replace", record_replace)
    atomic_json.atomic_write_json(tmp_path / "state.json", {"value": 1})
    assert events == ["file", "replace", "directory"]


def test_atomic_json_rejects_invalid_content_before_creating_directory(tmp_path):
    path = tmp_path / "missing" / "state.json"
    with pytest.raises(TypeError):
        atomic_json.atomic_write_json(path, {"value": object()})
    assert not path.parent.exists()


def test_directory_sync_failure_closes_descriptor_and_keeps_replaced_json(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    fsync = atomic_json.os.fsync
    descriptors = []

    def fail_directory_sync(descriptor):
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            descriptors.append(descriptor)
            raise OSError("synthetic directory sync failure")
        fsync(descriptor)

    monkeypatch.setattr(atomic_json.os, "fsync", fail_directory_sync)
    with pytest.raises(OSError, match="directory sync failure"):
        atomic_json.atomic_write_json(path, {"value": "new"})
    assert json.loads(path.read_text()) == {"value": "new"}
    with pytest.raises(OSError):
        os.fstat(descriptors[0])
    assert list(tmp_path.iterdir()) == [path]


def test_atomic_json_and_lock_reject_symlinks(tmp_path):
    target = tmp_path / "target.json"
    target.write_text("original")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="symbolic link"):
        atomic_json.atomic_write_json(link, {"value": "new"})
    with pytest.raises(ValueError, match="symbolic link"):
        with atomic_json.exclusive_file_lock(link):
            pytest.fail("Symlink lock admitted")
    assert target.read_text() == "original"


def test_exclusive_lock_rejects_overlap_and_releases_after_exception(tmp_path):
    path = tmp_path / "sync.lock"
    with pytest.raises(LookupError):
        with atomic_json.exclusive_file_lock(path, "Capture"):
            with pytest.raises(RuntimeError, match="Capture is already running"):
                with atomic_json.exclusive_file_lock(path, "Capture"):
                    pytest.fail("Concurrent lock admitted")
            raise LookupError("synthetic failure")
    with atomic_json.exclusive_file_lock(path, "Capture"):
        pass
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
