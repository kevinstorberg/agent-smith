from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.shared.paths import bootstrap  # noqa: E402
bootstrap()


@pytest.fixture(scope="session")
def eval_config():
    return {
        "model": os.environ.get("EVAL_MODEL", "claude-opus-4-6"),
        "judge_model": os.environ.get("EVAL_JUDGE_MODEL", "gpt-5.4"),
        "threshold": float(os.environ.get("EVAL_THRESHOLD", "0.9")),
    }


@pytest.fixture(scope="session", autouse=True)
def _init_db():
    from services.db import init_db
    init_db()
