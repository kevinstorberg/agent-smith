from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath


def relative_parts(relative: str) -> tuple[str, ...]:
    if not isinstance(relative, str) or not relative or "\0" in relative:
        raise ValueError(
            "path must be a nonempty relative string without null characters"
        )
    portable = PurePosixPath(relative)
    windows = PureWindowsPath(relative)
    if portable.is_absolute() or windows.drive or windows.root or "\\" in relative:
        raise ValueError(f"path must be relative and use forward slashes: {relative!r}")
    if not portable.parts or ".." in portable.parts:
        raise ValueError(
            f"path must identify a child without parent traversal: {relative!r}"
        )
    return portable.parts


def contained_path(root: Path, relative: str) -> Path:
    parts = relative_parts(relative)

    try:
        root = Path(root).resolve()
        candidate = root
        for component in parts:
            candidate = candidate / component
            if candidate.is_symlink():
                raise ValueError(f"path contains a symbolic link: {candidate}")
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError(f"path escapes its destination: {relative!r}")
        return resolved
    except (OSError, RuntimeError) as error:
        raise ValueError(f"Cannot validate destination path: {relative!r}") from error
