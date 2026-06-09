import argparse
import asyncio
import importlib.util
import os
import shutil
import subprocess
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from config.loader import load_default_config
from config.models import DefaultConfig
from lib.agent_smith_core.paths import get_repo_root
from scripts.base import BaseScript
from src.security.production import validate_production_settings
from src.settings import Settings, get_settings

CheckStatus = Literal["pass", "warn", "fail"]
CommandRunner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]
ImportChecker = Callable[[str], bool]
AsyncCheck = Callable[[], Awaitable["CheckResult"]]


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: CheckStatus
    message: str

    @classmethod
    def passed(cls, name: str, message: str) -> "CheckResult":
        return cls(name=name, status="pass", message=message)

    @classmethod
    def warned(cls, name: str, message: str) -> "CheckResult":
        return cls(name=name, status="warn", message=message)

    @classmethod
    def failed(cls, name: str, message: str) -> "CheckResult":
        return cls(name=name, status="fail", message=message)


def _run_command(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, check=False, text=True)


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _format_output(output: str) -> str:
    return " ".join(output.strip().split())


def _credential_status(*, strict: bool, require_credentials: bool) -> CheckStatus:
    if strict or require_credentials:
        return "fail"
    return "warn"


def _credential_result(
    *,
    name: str,
    setting_name: str,
    setting_value: str,
    strict: bool,
    require_credentials: bool,
) -> CheckResult:
    if setting_value:
        return CheckResult.passed(name, f"{setting_name} is set")

    message = f"{setting_name} is not set"
    status = _credential_status(strict=strict, require_credentials=require_credentials)
    if status == "fail":
        return CheckResult.failed(name, message)
    return CheckResult.warned(name, message)


class Doctor:
    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        settings: Settings | None = None,
        config: DefaultConfig | None = None,
        command_runner: CommandRunner = _run_command,
        import_checker: ImportChecker = _module_available,
        db_check: AsyncCheck | None = None,
        migration_check: AsyncCheck | None = None,
        poetry_locator: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self.repo_root = repo_root or get_repo_root(__file__)
        self.settings = settings or get_settings()
        self.config = config or load_default_config()
        self.command_runner = command_runner
        self.import_checker = import_checker
        self.db_check = db_check
        self.migration_check = migration_check
        self.poetry_locator = poetry_locator

    async def run(
        self,
        *,
        skip_db: bool = False,
        all_optional: bool = False,
        strict: bool = False,
        require_credentials: bool = False,
    ) -> list[CheckResult]:
        results = [
            *self.check_poetry(),
            *self.check_env_files(),
            *self.check_settings(),
            self.check_production_security(),
            self.check_job_runtime(),
            *self.check_required_dependencies(),
            *self.check_optional_backend_dependencies(all_optional=all_optional),
            *self.check_provider_credentials(strict=strict, require_credentials=require_credentials),
        ]

        if skip_db:
            results.append(CheckResult.warned("Database", "skipped by --skip-db"))
            results.append(CheckResult.warned("Migrations", "skipped by --skip-db"))
            return results

        results.append(await self._run_db_check())
        results.append(await self._run_migration_check())
        return results

    def check_poetry(self) -> list[CheckResult]:
        results = []
        poetry_path = self.poetry_locator("poetry")
        if poetry_path:
            results.append(CheckResult.passed("Poetry CLI", poetry_path))
        else:
            results.append(CheckResult.failed("Poetry CLI", "poetry is not on PATH"))
            return results

        if os.environ.get("POETRY_ACTIVE") == "1" or sys.prefix != sys.base_prefix:
            results.append(CheckResult.passed("Poetry environment", f"active Python: {sys.executable}"))
        else:
            results.append(CheckResult.warned("Poetry environment", "run through `poetry run` for app parity"))

        try:
            completed = self.command_runner(["poetry", "check", "--lock"], self.repo_root)
        except OSError as e:
            results.append(CheckResult.failed("Lockfile freshness", str(e)))
        else:
            output = _format_output(completed.stdout or completed.stderr)
            if completed.returncode == 0:
                results.append(CheckResult.passed("Lockfile freshness", output or "poetry.lock is fresh"))
            else:
                results.append(CheckResult.failed("Lockfile freshness", output or "poetry check --lock failed"))

        return results

    def check_env_files(self) -> list[CheckResult]:
        results = []
        env_default = self.repo_root / ".env.default"
        active_env = self.repo_root / f".env.{self.settings.APP_ENV}"

        if env_default.exists():
            results.append(CheckResult.passed("Env default", ".env.default exists"))
        else:
            results.append(CheckResult.failed("Env default", ".env.default is missing"))

        if active_env.exists():
            results.append(CheckResult.passed("Active env file", f"{active_env.name} exists"))
        else:
            results.append(
                CheckResult.warned(
                    "Active env file",
                    f"{active_env.name} is missing; real environment variables may still satisfy settings",
                )
            )

        return results

    def check_settings(self) -> list[CheckResult]:
        try:
            database_url = self.settings.database_url_for()
        except ValueError as e:
            return [CheckResult.failed("Settings", str(e))]

        return [
            CheckResult.passed("Settings", f"APP_ENV={self.settings.APP_ENV}"),
            CheckResult.passed("Database URL", database_url),
        ]

    def check_production_security(self) -> CheckResult:
        errors = validate_production_settings(self.settings, self.config)
        if errors:
            return CheckResult.failed("Production security", "; ".join(errors))

        if self.settings.APP_ENV.lower() == "production":
            return CheckResult.passed("Production security", "production security settings are explicit")
        return CheckResult.warned(
            "Production security", f"APP_ENV={self.settings.APP_ENV}; production checks not enforced"
        )

    def check_job_runtime(self) -> CheckResult:
        if not self.config.jobs.enabled:
            return CheckResult.passed("Job runtime", "disabled")

        distributed_lock = self.config.jobs.lock_backend.lower() in {"postgres", "redis"}
        if self.config.jobs.require_distributed_lock and not distributed_lock:
            return CheckResult.failed(
                "Job runtime",
                "jobs.require_distributed_lock=true requires jobs.lock_backend=postgres or redis",
            )

        if self.settings.APP_ENV.lower() == "production" and not distributed_lock:
            return CheckResult.warned(
                "Job runtime",
                f"production jobs use non-distributed lock backend {self.config.jobs.lock_backend!r}",
            )

        return CheckResult.passed(
            "Job runtime",
            (
                f"scheduler_store={self.config.jobs.scheduler_store}, "
                f"status_store={self.config.jobs.status_store}, "
                f"lock_backend={self.config.jobs.lock_backend}"
            ),
        )

    def check_required_dependencies(self) -> list[CheckResult]:
        required_modules = ["fastapi", "sqlalchemy", "alembic", "pydantic", "langgraph"]
        return [self._dependency_result("Required dependency", module) for module in required_modules]

    def check_optional_backend_dependencies(self, *, all_optional: bool) -> list[CheckResult]:
        dependencies = self._selected_optional_dependencies()
        if all_optional:
            dependencies.update({"boto3", "langgraph.checkpoint.postgres", "pgvector", "pinecone", "pymongo", "redis"})

        if not dependencies:
            return [CheckResult.passed("Optional backend dependencies", "no optional backends selected")]

        return [self._dependency_result("Optional backend dependency", module) for module in sorted(dependencies)]

    def check_provider_credentials(self, *, strict: bool, require_credentials: bool) -> list[CheckResult]:
        results = []

        llm_provider = self.config.llm.provider.lower()
        if llm_provider == "anthropic":
            results.append(
                _credential_result(
                    name="LLM credentials",
                    setting_name="ANTHROPIC_API_KEY",
                    setting_value=self.settings.ANTHROPIC_API_KEY,
                    strict=strict,
                    require_credentials=require_credentials,
                )
            )
        elif llm_provider == "openai":
            results.append(
                _credential_result(
                    name="LLM credentials",
                    setting_name="OPENAI_API_KEY",
                    setting_value=self.settings.OPENAI_API_KEY,
                    strict=strict,
                    require_credentials=require_credentials,
                )
            )
        else:
            results.append(CheckResult.failed("LLM credentials", f"unknown provider {self.config.llm.provider!r}"))

        if self.config.storage.backend.lower() == "s3":
            if self.settings.S3_BUCKET:
                results.append(CheckResult.passed("S3 credentials", "S3_BUCKET is set"))
            else:
                results.append(CheckResult.failed("S3 credentials", "S3_BUCKET is required for storage.backend=s3"))

            if self.settings.AWS_ACCESS_KEY_ID and self.settings.AWS_SECRET_ACCESS_KEY:
                results.append(CheckResult.passed("AWS credentials", "static AWS credentials are set"))
            else:
                results.append(
                    CheckResult.warned(
                        "AWS credentials",
                        "static AWS credentials are not set; IAM role or ambient AWS credentials must be available",
                    )
                )

        if self.config.memory.backend.lower() == "pinecone":
            if self.settings.PINECONE_API_KEY and self.settings.PINECONE_INDEX_NAME:
                results.append(
                    CheckResult.passed("Pinecone credentials", "PINECONE_API_KEY and PINECONE_INDEX_NAME are set")
                )
            else:
                missing = [
                    name
                    for name, value in {
                        "PINECONE_API_KEY": self.settings.PINECONE_API_KEY,
                        "PINECONE_INDEX_NAME": self.settings.PINECONE_INDEX_NAME,
                    }.items()
                    if not value
                ]
                results.append(
                    CheckResult.failed(
                        "Pinecone credentials",
                        f"{', '.join(missing)} required for memory.backend=pinecone",
                    )
                )

        if self.config.cache.backend.lower() == "redis":
            if self.settings.REDIS_URL:
                results.append(CheckResult.passed("Redis connection", "REDIS_URL is set"))
            else:
                results.append(CheckResult.failed("Redis connection", "REDIS_URL is required for cache.backend=redis"))

        return results

    async def _run_db_check(self) -> CheckResult:
        if self.db_check is not None:
            return await self.db_check()
        try:
            database_url = self.settings.database_url_for()
        except ValueError as e:
            return CheckResult.failed("Database", str(e))
        return await check_database_connectivity(database_url)

    async def _run_migration_check(self) -> CheckResult:
        if self.migration_check is not None:
            return await self.migration_check()
        try:
            database_url = self.settings.database_url_for()
        except ValueError as e:
            return CheckResult.failed("Migrations", str(e))
        return await check_migrations_current(self.repo_root, database_url)

    def _selected_optional_dependencies(self) -> set[str]:
        dependencies: set[str] = set()
        if self.config.cache.backend.lower() == "redis":
            dependencies.add("redis")
        if self.config.jobs.lock_backend.lower() == "redis":
            dependencies.add("redis")
        if self.config.storage.backend.lower() == "s3":
            dependencies.add("boto3")
        if self.config.memory.backend.lower() == "pinecone":
            dependencies.add("pinecone")
        if self.config.memory.backend.lower() == "pgvector":
            dependencies.add("pgvector")
        return dependencies

    def _dependency_result(self, check_name: str, module: str) -> CheckResult:
        if self.import_checker(module):
            return CheckResult.passed(check_name, f"{module} importable")
        return CheckResult.failed(check_name, f"{module} is not importable")


async def check_database_connectivity(database_url: str) -> CheckResult:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as e:
        return CheckResult.failed("Database", f"cannot connect: {e}")
    finally:
        await engine.dispose()
    return CheckResult.passed("Database", "SELECT 1 succeeded")


async def check_migrations_current(repo_root: Path, database_url: str) -> CheckResult:
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
    except ImportError as e:
        return CheckResult.failed("Migrations", f"Alembic unavailable: {e}")

    migrations_path = repo_root / "db" / "migrations"
    if not migrations_path.exists():
        return CheckResult.failed("Migrations", f"migration script path does not exist: {migrations_path}")

    alembic_config = Config(str(repo_root / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(migrations_path))
    script = ScriptDirectory.from_config(alembic_config)
    heads = set(script.get_heads())

    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT to_regclass('public.alembic_version')::text"))
            table_name = result.scalar()
            if table_name is None:
                if not heads:
                    return CheckResult.passed("Migrations", "no migration revisions defined")
                return CheckResult.failed("Migrations", "alembic_version table is missing")

            versions_result = await connection.execute(text("SELECT version_num FROM alembic_version"))
            current_versions = {row.version_num for row in versions_result}
    except Exception as e:
        return CheckResult.failed("Migrations", f"cannot inspect migration state: {e}")
    finally:
        await engine.dispose()

    if not heads:
        if current_versions:
            return CheckResult.failed(
                "Migrations",
                f"database has recorded revisions {sorted(current_versions)} but repository has no migration revisions",
            )
        return CheckResult.passed("Migrations", "no migration revisions defined")

    if current_versions == heads:
        return CheckResult.passed("Migrations", f"current at head {', '.join(sorted(heads))}")
    return CheckResult.failed(
        "Migrations",
        f"database revisions {sorted(current_versions)} do not match heads {sorted(heads)}",
    )


class DoctorScript(BaseScript):
    name = "doctor"
    description = "Verify local Agent Smith bootstrap requirements"

    def configure_args(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--skip-db", action="store_true", help="Skip DB connectivity and migration checks")
        parser.add_argument("--all-optional", action="store_true", help="Check every optional backend dependency")
        parser.add_argument("--strict", action="store_true", help="Treat warnings as failures")
        parser.add_argument(
            "--require-provider-credentials",
            action="store_true",
            help="Fail when selected LLM provider credentials are missing",
        )

    def run(self, args: argparse.Namespace) -> int:
        results = asyncio.run(
            Doctor().run(
                skip_db=args.skip_db,
                all_optional=args.all_optional,
                strict=args.strict,
                require_credentials=args.require_provider_credentials,
            )
        )
        return render_results(results, strict=args.strict)


def render_results(results: list[CheckResult], *, strict: bool = False) -> int:
    for result in results:
        print(f"[{result.status.upper()}] {result.name}: {result.message}")

    failures = sum(result.status == "fail" for result in results)
    warnings = sum(result.status == "warn" for result in results)
    if strict and warnings:
        failures += warnings

    print(f"Doctor completed with {failures} failure(s) and {warnings} warning(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    script = DoctorScript()
    raise SystemExit(script.execute())
