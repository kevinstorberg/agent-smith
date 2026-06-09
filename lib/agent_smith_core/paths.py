"""Path utilities for resolving module-relative paths.

This module provides utilities for consistently resolving paths relative to
module files, eliminating repeated Path(__file__).resolve().parent patterns.
"""

from pathlib import Path

REPO_ROOT_MARKERS = ("pyproject.toml", ".git", "alembic.ini")


def get_module_dir(file: str) -> Path:
    """Get directory containing the calling module.

    Args:
        file: The __file__ attribute of the calling module

    Returns:
        Resolved path to the directory containing the module

    Usage:
        >>> # In config/loader.py
        >>> _CONFIG_DIR = get_module_dir(__file__)
    """
    return Path(file).resolve().parent


def get_repo_root(file: str) -> Path:
    """Find the repository root from a module file or directory.

    Args:
        file: The __file__ attribute of the calling module, or a directory

    Returns:
        Resolved path to the repository root

    Usage:
        >>> # In src/settings.py
        >>> _REPO_ROOT = get_repo_root(__file__)
    """
    start = Path(file).resolve()
    current = start if start.is_dir() else start.parent

    for candidate in (current, *current.parents):
        if any((candidate / marker).exists() for marker in REPO_ROOT_MARKERS):
            return candidate

    markers = ", ".join(REPO_ROOT_MARKERS)
    raise RuntimeError(f"Could not find repository root from {file!r}; expected one of: {markers}")
