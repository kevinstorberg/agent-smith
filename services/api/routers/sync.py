from __future__ import annotations

import subprocess
import sys

from fastapi import APIRouter, HTTPException

from scripts.shared.paths import REPO_ROOT

router = APIRouter()


@router.post("/sync")
def run_sync():
    sync_script = REPO_ROOT / "scripts" / "sync.py"
    if not sync_script.exists():
        raise HTTPException(500, f"sync.py not found at {sync_script}")
    result = subprocess.run(
        [sys.executable, str(sync_script)],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=60,
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
