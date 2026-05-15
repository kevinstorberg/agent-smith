from __future__ import annotations

import subprocess
import sys


def run_sync_script(args: list[str] | None = None) -> dict:
    """Execute scripts/sync.py via subprocess.

    Args:
        args: Additional arguments to pass to sync.py

    Returns:
        dict with keys: success (bool), stdout (str), stderr (str)

    Raises:
        FileNotFoundError: If sync.py script doesn't exist
        subprocess.TimeoutExpired: If execution exceeds timeout
    """
    from scripts.shared.paths import REPO_ROOT

    sync_script = REPO_ROOT / "scripts" / "sync.py"
    if not sync_script.exists():
        raise FileNotFoundError(f"sync.py not found at {sync_script}")

    cmd = [sys.executable, str(sync_script)]
    if args:
        cmd.extend(args)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=60,
    )

    return {
        "success": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
