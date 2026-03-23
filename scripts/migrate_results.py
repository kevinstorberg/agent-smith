"""Migrate eval result JSON files to Postgres."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.shared.env import load_dotenv
load_dotenv(REPO_ROOT)

from evals.shared.db import init_eval_tables, save_result
from services.db import get_connection

RESULTS_DIR = REPO_ROOT / "evals" / "results"


def _already_migrated(conn, filename: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM eval_results WHERE timestamp = %s AND scenario = %s AND test_model = %s LIMIT 1",
            _parse_filename_keys(filename),
        )
        return cur.fetchone() is not None


def _parse_filename_keys(filename: str) -> tuple:
    """Extract dedup keys from the JSON content instead of filename parsing."""
    return None


def migrate():
    init_eval_tables()

    json_files = sorted(RESULTS_DIR.rglob("*.json"))
    if not json_files:
        print(f"No JSON files found in {RESULTS_DIR}")
        return

    migrated = 0
    skipped = 0

    for f in json_files:
        data = json.loads(f.read_text(encoding="utf-8"))
        ts = datetime.fromisoformat(data["timestamp"])

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM eval_results WHERE timestamp = %s AND scenario = %s AND test_model = %s LIMIT 1",
                    (ts, data["scenario"], data["model"]),
                )
                if cur.fetchone():
                    skipped += 1
                    continue

        output = data.get("output") or data.get("plan", "")

        run_id = save_result(
            timestamp=ts,
            eval_type=data["eval_type"],
            scenario=data["scenario"],
            test_model=data["model"],
            judge_model=data["judge_model"],
            threshold=data["threshold"],
            output=output,
            results=data["results"],
        )
        migrated += 1
        print(f"  migrated: {f.name} -> id={run_id}")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM eval_results")
            total = cur.fetchone()[0]

    print(f"\nMigrated {migrated} files, {skipped} skipped. Total rows in DB: {total}")


if __name__ == "__main__":
    migrate()
