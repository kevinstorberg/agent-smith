#!/usr/bin/env -S .venv/bin/python3
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) in sys.path:
    sys.path.remove(str(SCRIPT_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import argparse
import asyncio
import json
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from scripts.base import BaseScript
from src.agent_smith.constants import EXPECTED_MIGRATION_HEAD
from src.settings import get_settings

AGENT_SMITH_TABLES = (
    "harness_rules",
    "harness_skills",
    "harness_tools",
    "harness_hooks",
    "harness_agents",
    "harness_configs",
    "plans",
    "eval_suites",
    "eval_scenarios",
    "eval_results",
    "background_jobs",
    "job_configs",
    "job_executions",
)


class AgentSmithPreflightScript(BaseScript):
    name = "scripts/agent_smith_preflight.py"
    description = "Validate Agent Smith Cairn production cutover prerequisites without mutating stores."

    def configure_args(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--production", action="store_true", help="Use read-only production DB settings.")
        parser.add_argument("--write-cutover", action="store_true", help="Validate write-capable cutover gates.")
        parser.add_argument("--output", type=Path, default=None, help="Optional JSON report path.")

    def run(self, args: argparse.Namespace) -> int:
        report = asyncio.run(_run_preflight(args.production, args.write_cutover))
        output = json.dumps(report, indent=2, default=str) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output, encoding="utf-8")
        print(output, end="")
        return 0 if report["status"] == "pass" else 1


async def _run_preflight(production: bool, write_cutover: bool) -> dict:
    settings = get_settings()
    errors: list[str] = []
    database_url = _database_url(settings, production=production, write_cutover=write_cutover, errors=errors)
    if write_cutover:
        errors.extend(_write_cutover_errors(settings))

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "production" if production else settings.APP_ENV,
        "write_cutover": write_cutover,
        "expected_migration_head": EXPECTED_MIGRATION_HEAD,
        "database": {},
        "vector": _vector_report(settings),
        "errors": errors,
    }
    if database_url and not errors:
        report["database"] = await _database_report(database_url)
        heads = set(report["database"].get("alembic_versions") or [])
        if heads != {EXPECTED_MIGRATION_HEAD}:
            report["errors"].append(
                f"database revisions {sorted(heads)} do not match expected {EXPECTED_MIGRATION_HEAD}"
            )
    report["status"] = "pass" if not report["errors"] else "fail"
    return report


def _database_url(settings, *, production: bool, write_cutover: bool, errors: list[str]) -> str:
    if production and not write_cutover:
        if not settings.AGENT_SMITH_PROD_DATABASE_URL_READONLY:
            errors.append("AGENT_SMITH_PROD_DATABASE_URL_READONLY is required for production read-only preflight")
            return ""
        return settings.AGENT_SMITH_PROD_DATABASE_URL_READONLY
    return settings.database_url


def _write_cutover_errors(settings) -> list[str]:
    errors = []
    if not settings.AGENT_SMITH_CUTOVER_CONFIRMED:
        errors.append("AGENT_SMITH_CUTOVER_CONFIRMED=true is required for write-capable cutover")
    if not settings.AGENT_SMITH_BACKUP_PATH:
        errors.append("AGENT_SMITH_BACKUP_PATH is required before write-capable cutover")
    return errors


async def _database_report(database_url: str) -> dict:
    engine = create_async_engine(_async_database_url(database_url))
    try:
        async with engine.connect() as connection:
            versions = [
                row.version_num
                for row in (await connection.execute(text("SELECT version_num FROM alembic_version"))).all()
            ]
            counts = {}
            for table in AGENT_SMITH_TABLES:
                exists = await connection.execute(text("SELECT to_regclass(:table_name)::text"), {"table_name": table})
                if exists.scalar_one_or_none() is None:
                    counts[table] = None
                    continue
                result = await connection.execute(text(f"SELECT count(*) FROM {table}"))
                counts[table] = int(result.scalar_one())
            return {"alembic_versions": versions, "row_counts": counts}
    finally:
        await engine.dispose()


def _vector_report(settings) -> dict:
    if settings.MEMORY_BACKEND != "pinecone":
        return {"backend": settings.MEMORY_BACKEND, "status": "not_production_vector_backend"}
    if not settings.PINECONE_API_KEY:
        return {"backend": "pinecone", "status": "skipped_missing_credentials"}
    try:
        from pinecone import Pinecone

        index_name = settings.PINECONE_INDEX_NAME or settings.PINECONE_INDEX
        index = Pinecone(api_key=settings.PINECONE_API_KEY).Index(index_name)
        return {"backend": "pinecone", "status": "pass", "stats": index.describe_index_stats()}
    except Exception as exc:  # noqa: BLE001
        return {"backend": "pinecone", "status": "fail", "error": f"{type(exc).__name__}: {exc}"}


def _async_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    return database_url


if __name__ == "__main__":
    raise SystemExit(AgentSmithPreflightScript().execute())
