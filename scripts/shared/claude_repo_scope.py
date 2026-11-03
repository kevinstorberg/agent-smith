from __future__ import annotations

import os
import subprocess
from pathlib import Path


class GitUnavailableError(ValueError):
    pass


class GitScopeTimeoutError(ValueError):
    pass


def _contained(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(root.is_absolute() and path.is_relative_to(root) for root in roots)


def _git_path(directory: Path, option: str) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(directory), "rev-parse", option],
            capture_output=True, text=True, timeout=0.25, check=False,
            env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
        )
    except FileNotFoundError:
        raise GitUnavailableError("Git executable is unavailable") from None
    except subprocess.TimeoutExpired:
        raise GitScopeTimeoutError("Git repository scope lookup timed out") from None
    text = result.stdout.rstrip("\n")
    if result.returncode or not text or any(character in text for character in "\n\r\0"):
        return None
    path = Path(text)
    return path if path.is_absolute() else directory / path


def resolve_repo(path: str, allowed_roots: tuple[Path, ...]) -> dict[str, str] | None:
    if not isinstance(path, str) or not path or len(path) > 4096:
        return None
    try:
        candidate = Path(os.path.normpath(Path(path).expanduser()))
        if not candidate.is_absolute() or not _contained(candidate, allowed_roots):
            return None
        candidate = candidate.resolve(strict=True)
        if not _contained(candidate, allowed_roots):
            return None
        if candidate.is_file():
            candidate = candidate.parent
        if not candidate.is_dir():
            return None

        root = _git_path(candidate, "--show-toplevel")
        if root is None:
            return None
        root = root.resolve(strict=True)
        if not root.is_dir() or not _contained(root, allowed_roots) or not candidate.is_relative_to(root):
            return None
        common = _git_path(root, "--git-common-dir")
        if common is None:
            return None
        common = common.resolve(strict=True)
        if not common.is_dir() or not _contained(common, allowed_roots):
            return None

        # Linked worktree directory names describe branches, not repository identity.
        canonical = common.parent if common.name == ".git" else root
        if not canonical.is_dir() or not _contained(canonical, allowed_roots):
            return None
        return {"repo": canonical.name, "root": str(root), "canonical_root": str(canonical)}
    except (GitUnavailableError, GitScopeTimeoutError):
        raise
    except (OSError, ValueError, RuntimeError):
        return None
