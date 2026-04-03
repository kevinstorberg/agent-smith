from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter()

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent


@router.post("/sync")
def run_sync():
    sync_script = _REPO_ROOT / "sync.py"
    if not sync_script.exists():
        raise HTTPException(500, f"sync.py not found at {sync_script}")
    result = subprocess.run(
        [sys.executable, str(sync_script)],
        capture_output=True, text=True, cwd=str(_REPO_ROOT), timeout=60,
    )
    return {
        "success": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


@router.post("/unsync")
def run_unsync():
    from scripts.shared.agents import unsync_all
    removed = unsync_all()
    return {"success": True, "removed": removed}
