from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT


def create_database(url: str) -> bool:
    from scripts.shared.database_safety import database_identity, validate_database_target, production_database_url
    repo_root = Path(__file__).resolve().parent.parent.parent
    app_env = os.environ.get("APP_ENV", "development")
    if app_env == "production":
        raise ValueError("Production database creation is disabled; provision it separately")
    validate_database_target(app_env, url, production_database_url(repo_root, dict(os.environ)))
    db_name = database_identity(url)[2]
    base = urlunsplit(urlsplit(url)._replace(path="/postgres"))

    conn = psycopg2.connect(base, connect_timeout=5)
    try:
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
            if cur.fetchone():
                return False
            from psycopg2 import sql
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))
        return True
    finally:
        conn.close()


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(repo_root))

    from services.config import APP_ENV, DATABASE_URL
    created = create_database(DATABASE_URL)
    print(f"{APP_ENV}: {'created' if created else 'already exists'}")


if __name__ == "__main__":
    main()
