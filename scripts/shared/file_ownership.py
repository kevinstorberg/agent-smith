from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path

from scripts.shared.atomic_json import atomic_write_json, exclusive_file_lock
from scripts.shared.path_safety import contained_path, relative_parts

STATE_NAME = ".agent-smith-files.json"
LOCK_NAME = ".agent-smith-files.lock"
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def _relative(relative: str) -> tuple[str, ...]:
    parts = relative_parts(relative)
    if parts[0] in {STATE_NAME, LOCK_NAME}:
        raise ValueError("Publication paths must not replace ownership metadata")
    if "/".join(parts) != relative:
        raise ValueError(f"Publication paths must be canonical: {relative!r}")
    return parts


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _state(root: Path) -> dict[str, dict[str, str]]:
    path = contained_path(root, STATE_NAME)
    if not path.exists():
        return {}
    if not path.is_file():
        raise ValueError(f"Ownership state must be a regular file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"Cannot read ownership state: {path}") from error
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "owners"}
        or type(value["version"]) is not int
        or value["version"] != 1
        or not isinstance(value["owners"], dict)
    ):
        raise ValueError(f"Unsupported ownership state: {path}")
    owners = value["owners"]
    for owner, files in owners.items():
        if not isinstance(owner, str) or not owner or not isinstance(files, dict):
            raise ValueError(f"Invalid ownership entry: {path}")
        for relative, digest in files.items():
            _relative(relative)
            if not isinstance(digest, str) or not _HASH.fullmatch(digest):
                raise ValueError(f"Invalid ownership digest: {path}")
    return owners


def _prepare(
    root: Path, owner: str, outputs: dict[str, str]
) -> tuple[dict[str, dict[str, str]], dict[str, tuple[Path, str, bool]]]:
    if not isinstance(owner, str) or not owner:
        raise ValueError("Publication owner must be a nonempty string")
    if not isinstance(outputs, dict):
        raise ValueError("Publication outputs must be an object")
    for relative in outputs:
        parts = _relative(relative)
        if any("/".join(parts[:index]) in outputs for index in range(1, len(parts))):
            raise ValueError(
                f"Collision between desired parent and child files: {relative}"
            )
    contained_path(root, LOCK_NAME)
    owners = _state(root)
    prepared = {}
    for relative, content in outputs.items():
        _relative(relative)
        if not isinstance(content, str):
            raise ValueError(f"Publication content must be text: {relative!r}")
        path = contained_path(root, relative)
        for parent in path.parents:
            if parent == root.parent:
                break
            if parent.exists() and not parent.is_dir():
                raise ValueError(f"Collision with a non-directory parent at {parent}")
        desired_hash = _digest(content.encode("utf-8"))
        references = {
            name: files[relative] for name, files in owners.items() if relative in files
        }
        other_hashes = {digest for name, digest in references.items() if name != owner}
        if other_hashes - {desired_hash}:
            raise ValueError(f"Collision with another publisher at {path}")
        owned = bool(references)
        if path.exists():
            if not path.is_file():
                raise ValueError(f"Collision with a non-file destination at {path}")
            current = _digest(path.read_bytes())
            if (owned and set(references.values()) != {current}) or (
                not owned and current != desired_hash
            ):
                raise ValueError(
                    f"Collision at {path}; preserve or move the local file before retrying"
                )
        else:
            owned = True
        prepared[relative] = (path, desired_hash, owned)
    return owners, prepared


def check_publication(root: Path, owner: str, outputs: dict[str, str]) -> None:
    _prepare(Path(root).expanduser().resolve(), owner, outputs)


def publish_files(
    root: Path,
    owner: str,
    outputs: dict[str, str],
    *,
    dry_run: bool = False,
    write: Callable[[Path, str], tuple[bool, str]] | None = None,
) -> list[str]:
    root = Path(root).expanduser().resolve()
    if not isinstance(outputs, dict):
        raise ValueError("Publication outputs must be an object")
    outputs = dict(outputs)
    owners, _ = _prepare(root, owner, outputs)
    if dry_run:
        print(f"  would publish {len(outputs)} file(s) -> {root}")
        return []
    if not outputs and owner not in owners:
        return []
    if outputs and write is None:
        raise ValueError("Publication requires a text writer")
    with exclusive_file_lock(root / LOCK_NAME, "File publication"):
        owners, prepared = _prepare(root, owner, outputs)
        previous = owners.get(owner, {})
        new_owned = {}
        for relative, (path, digest, owned) in prepared.items():
            if not owned:
                print(f"  preserved unowned identical file: {path}")
                continue
            _, message = write(path, outputs[relative])
            if _digest(path.read_bytes()) != digest:
                raise RuntimeError(f"Published content verification failed: {path}")
            print(f"  {message}")
            new_owned[relative] = digest

        removed = []
        for relative, digest in previous.items():
            if relative in outputs or any(
                relative in files for name, files in owners.items() if name != owner
            ):
                continue
            # Retired links, local edits and unknown nested files are never followed or removed.
            try:
                path = contained_path(root, relative)
            except ValueError:
                print(f"  preserved retired symbolic path: {root / relative}")
                continue
            if path.is_file() and _digest(path.read_bytes()) == digest:
                path.unlink()
                removed.append(str(path))
                print(f"  removed owned file: {path}")
            elif path.exists():
                print(f"  preserved modified retired file: {path}")
        if new_owned:
            owners[owner] = new_owned
        else:
            owners.pop(owner, None)
        atomic_write_json(root / STATE_NAME, {"version": 1, "owners": owners})
        return removed


def retire_config_files(cfg: dict, agent: str) -> list[str]:
    removed = []
    for key, kind in (
        ("rules_file", "rules-file"),
        ("rules_dir", "rules"),
        ("skills_dir", "skills"),
        ("agents_dir", "agents"),
    ):
        if not cfg.get(key):
            continue
        path = Path(cfg[key]).expanduser()
        root = path.parent if key == "rules_file" else path
        removed.extend(publish_files(root, f"{agent}:{kind}", {}))
    return removed
