"""Create databases for configured environments. Idempotent."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT


def create_database(url: str) -> bool:
    """Create the database if it doesn't exist. Returns True if created."""
    db_name = url.rsplit("/", 1)[-1].split("?")[0]
    base = url.rsplit("/", 1)[0] + "/postgres"
    if "?" in url:
        base += "?" + url.split("?", 1)[1]

    conn = psycopg2.connect(base)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
        if cur.fetchone():
            conn.close()
            return False
        cur.execute(f'CREATE DATABASE "{db_name}"')
    conn.close()
    return True


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(repo_root))

    from scripts.shared.env import load_dotenv
    load_dotenv(repo_root)

    envs = [
        ("development", "DATABASE_URL_DEVELOPMENT"),
        ("test", "DATABASE_URL_TEST"),
        ("production", "DATABASE_URL_PRODUCTION"),
    ]
    for label, var in envs:
        url = os.environ.get(var, "")
        if not url:
            print(f"  {label}: skipped ({var} not set)")
            continue
        created = create_database(url)
        print(f"  {label}: {'created' if created else 'already exists'}")


if __name__ == "__main__":
    main()
