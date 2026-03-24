#!/usr/bin/env -S .venv/bin/python3
"""Migrate eval_results data from local Postgres to remote RDS.

Usage:
    REMOTE_DATABASE_URL='postgresql://...' ./scripts/migrate_to_rds.py

Env vars:
    LOCAL_DATABASE_URL   Source DB (defaults to postgresql://localhost/agent_smith)
    REMOTE_DATABASE_URL  Target RDS instance (required)
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.shared.paths import bootstrap, REPO_ROOT  # noqa: E402
bootstrap()

from scripts.shared.validation import require_env  # noqa: E402

LOCAL_URL = os.environ.get("LOCAL_DATABASE_URL", "postgresql://localhost/agent_smith")
REMOTE_URL = os.environ.get("REMOTE_DATABASE_URL", "")


def _connect(url: str, label: str) -> psycopg2.extensions.connection:
    try:
        conn = psycopg2.connect(url)
        return conn
    except psycopg2.OperationalError as e:
        raise SystemExit(f"Cannot connect to {label} DB: {e}") from e


def _row_count(url: str) -> int:
    conn = _connect(url, "count")
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM eval_results")
            return cur.fetchone()[0]
    except psycopg2.errors.UndefinedTable:
        return 0
    finally:
        conn.close()


def _sample_rows(url: str, ids: list[int]) -> list[tuple]:
    conn = _connect(url, "sample")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, timestamp, scenario, test_model FROM eval_results WHERE id = ANY(%s) ORDER BY id",
                (ids,),
            )
            return cur.fetchall()
    finally:
        conn.close()


def _run(cmd: list[str], description: str) -> None:
    print(f"  {description}...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  FAILED: {result.stderr.strip()}", file=sys.stderr)
        raise SystemExit(1)


def main() -> None:
    assert LOCAL_URL.startswith(("postgresql://", "postgres://")), (
        f"LOCAL_DATABASE_URL must be a postgresql:// URL, got: {LOCAL_URL[:30]}..."
    )
    if not REMOTE_URL:
        require_env("REMOTE_DATABASE_URL", "Example: REMOTE_DATABASE_URL='postgresql://user:pass@host:5432/agent_smith?sslmode=verify-full&sslrootcert=~/.aws/rds-global-bundle.pem'")
    assert REMOTE_URL.startswith(("postgresql://", "postgres://")), (
        f"REMOTE_DATABASE_URL must be a postgresql:// URL, got: {REMOTE_URL[:30]}..."
    )

    print("[1/6] Checking local DB...")
    local_conn = _connect(LOCAL_URL, "local")
    local_conn.close()
    local_count = _row_count(LOCAL_URL)
    if local_count == 0:
        raise SystemExit("Local DB has no rows in eval_results. Nothing to migrate.")
    print(f"  Local eval_results: {local_count} rows")

    print("[2/6] Checking remote DB...")
    remote_conn = _connect(REMOTE_URL, "remote")
    remote_conn.close()

    print("[3/6] Running Alembic migrations on remote...")
    env = {**os.environ, "DATABASE_URL": REMOTE_URL}
    _run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        "alembic upgrade head",
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(REPO_ROOT),
        env=env,
        check=True,
    )

    remote_count = _row_count(REMOTE_URL)
    if remote_count > 0:
        raise SystemExit(
            f"Remote DB already has {remote_count} rows in eval_results. "
            "Aborting to prevent duplicate data. "
            "If this is intentional, truncate the remote table first."
        )

    with tempfile.NamedTemporaryFile(suffix=".pgdump", delete=False) as tmp:
        dump_path = tmp.name

    print("[4/6] Dumping local eval_results...")
    _run(
        [
            "pg_dump",
            "--table=eval_results",
            "--data-only",
            "--format=custom",
            f"--dbname={LOCAL_URL}",
            f"--file={dump_path}",
        ],
        "pg_dump --data-only",
    )

    print("[5/6] Restoring to remote DB...")
    _run(
        [
            "pg_restore",
            "--data-only",
            "--disable-triggers",
            f"--dbname={REMOTE_URL}",
            dump_path,
        ],
        "pg_restore --data-only",
    )

    Path(dump_path).unlink(missing_ok=True)

    # pg_restore doesn't advance the serial sequence — fix it manually
    remote_conn = _connect(REMOTE_URL, "remote")
    try:
        with remote_conn.cursor() as cur:
            cur.execute("SELECT setval('eval_results_id_seq', (SELECT MAX(id) FROM eval_results))")
        remote_conn.commit()
    finally:
        remote_conn.close()

    print("[6/6] Verifying migration...")
    migrated_count = _row_count(REMOTE_URL)
    if migrated_count != local_count:
        raise SystemExit(
            f"ROW COUNT MISMATCH: local={local_count}, remote={migrated_count}. "
            "Migration may be incomplete — investigate before proceeding."
        )

    local_conn = _connect(LOCAL_URL, "local")
    try:
        with local_conn.cursor() as cur:
            cur.execute("SELECT id FROM eval_results ORDER BY id LIMIT 3")
            sample_ids = [row[0] for row in cur.fetchall()]
    finally:
        local_conn.close()

    if sample_ids:
        local_sample = _sample_rows(LOCAL_URL, sample_ids)
        remote_sample = _sample_rows(REMOTE_URL, sample_ids)
        if local_sample != remote_sample:
            raise SystemExit(
                f"SAMPLE MISMATCH: rows {sample_ids} differ between local and remote. "
                "Investigate before proceeding."
            )
        print(f"  Sample verification passed ({len(sample_ids)} rows compared)")

    print(f"\nMigration complete: {migrated_count} rows transferred successfully.")
    print("Local DB has NOT been deleted — verify the remote data before removing it.")


if __name__ == "__main__":
    main()
