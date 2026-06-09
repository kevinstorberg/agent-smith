from pathlib import Path
from types import SimpleNamespace

import pytest

from config.models import CacheConfig, DefaultConfig, JobsConfig, LLMConfig, MemoryConfig, SecurityConfig, StorageConfig
from scripts.doctor import CheckResult, Doctor, DoctorScript, render_results
from src.settings import Settings


def passing_command_runner(command, cwd):
    return SimpleNamespace(returncode=0, stdout="All set!\n", stderr="")


def failing_command_runner(command, cwd):
    return SimpleNamespace(returncode=1, stdout="", stderr="lock file is stale\n")


def poetry_locator(command: str) -> str:
    assert command == "poetry"
    return "/usr/local/bin/poetry"


def import_checker(module: str) -> bool:
    return module not in {"boto3", "pinecone"}


async def passing_db_check() -> CheckResult:
    return CheckResult.passed("Database", "fake database ok")


async def passing_migration_check() -> CheckResult:
    return CheckResult.passed("Migrations", "fake migrations ok")


def test_render_results_returns_failure_only_for_failed_checks(capsys):
    exit_code = render_results(
        [
            CheckResult.passed("A", "ok"),
            CheckResult.warned("B", "warning"),
        ]
    )

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "[PASS] A: ok" in output
    assert "[WARN] B: warning" in output


def test_render_results_strict_treats_warnings_as_failures(capsys):
    exit_code = render_results([CheckResult.warned("A", "warning")], strict=True)

    output = capsys.readouterr().out

    assert exit_code == 1
    assert "1 failure(s) and 1 warning(s)" in output


@pytest.mark.asyncio
async def test_doctor_skip_db_checks_core_bootstrap_requirements(tmp_path):
    (tmp_path / ".env.default").write_text("APP_ENV=development\n")
    (tmp_path / ".env.development").write_text("APP_ENV=development\n")
    doctor = Doctor(
        repo_root=tmp_path,
        settings=Settings(APP_ENV="development", ANTHROPIC_API_KEY="key"),
        config=DefaultConfig(llm=LLMConfig(provider="anthropic")),
        command_runner=passing_command_runner,
        import_checker=lambda module: True,
        poetry_locator=poetry_locator,
    )

    results = await doctor.run(skip_db=True)

    statuses = {(result.name, result.status) for result in results}
    assert ("Poetry CLI", "pass") in statuses
    assert ("Lockfile freshness", "pass") in statuses
    assert ("Production security", "warn") in statuses
    assert ("Env default", "pass") in statuses
    assert ("Active env file", "pass") in statuses
    assert ("Database", "warn") in statuses
    assert ("Migrations", "warn") in statuses


@pytest.mark.asyncio
async def test_doctor_reports_stale_lockfile(tmp_path):
    doctor = Doctor(
        repo_root=tmp_path,
        settings=Settings(ANTHROPIC_API_KEY="key"),
        config=DefaultConfig(),
        command_runner=failing_command_runner,
        import_checker=lambda module: True,
        poetry_locator=poetry_locator,
    )

    results = await doctor.run(skip_db=True)

    assert CheckResult.failed("Lockfile freshness", "lock file is stale") in results


@pytest.mark.asyncio
async def test_doctor_fails_selected_optional_backend_dependency_and_credentials(tmp_path):
    (tmp_path / ".env.default").write_text("")
    config = DefaultConfig(
        llm=LLMConfig(provider="openai"),
        memory=MemoryConfig(backend="pinecone"),
        cache=CacheConfig(backend="redis"),
        storage=StorageConfig(backend="s3"),
    )
    settings = Settings(
        APP_ENV="development",
        OPENAI_API_KEY="key",
        REDIS_URL="redis://localhost:6379/0",
        S3_BUCKET="bucket",
        AWS_ACCESS_KEY_ID="id",
        AWS_SECRET_ACCESS_KEY="secret",
        PINECONE_API_KEY="",
        PINECONE_INDEX_NAME="",
    )
    doctor = Doctor(
        repo_root=tmp_path,
        settings=settings,
        config=config,
        command_runner=passing_command_runner,
        import_checker=import_checker,
        poetry_locator=poetry_locator,
    )

    results = await doctor.run(skip_db=True)

    assert CheckResult.failed("Optional backend dependency", "boto3 is not importable") in results
    assert CheckResult.failed("Optional backend dependency", "pinecone is not importable") in results
    assert any(result.name == "Pinecone credentials" and result.status == "fail" for result in results)


def test_doctor_all_optional_dependencies_include_documentdb_driver(tmp_path):
    checked_modules = set()
    doctor = Doctor(
        repo_root=tmp_path,
        settings=Settings(ANTHROPIC_API_KEY="key"),
        config=DefaultConfig(),
        command_runner=passing_command_runner,
        import_checker=lambda module: checked_modules.add(module) or True,
        poetry_locator=poetry_locator,
    )

    results = doctor.check_optional_backend_dependencies(all_optional=True)

    assert all(result.status == "pass" for result in results)
    assert {"boto3", "langgraph.checkpoint.postgres", "pgvector", "pinecone", "pymongo", "redis"} <= checked_modules


def test_doctor_warns_for_production_jobs_without_distributed_lock(tmp_path):
    doctor = Doctor(
        repo_root=tmp_path,
        settings=Settings(
            APP_ENV="production",
            SECRET_KEY="x" * 32,
            TRUSTED_HOSTS="api.example.com",
            ANTHROPIC_API_KEY="key",
        ),
        config=DefaultConfig(
            jobs=JobsConfig(lock_backend="memory"),
            security=SecurityConfig(cors_origins=["https://api.example.com"]),
        ),
        command_runner=passing_command_runner,
        import_checker=lambda module: True,
        poetry_locator=poetry_locator,
    )

    result = doctor.check_job_runtime()

    assert result.status == "warn"
    assert "non-distributed lock backend" in result.message


def test_doctor_fails_when_distributed_job_lock_is_required(tmp_path):
    doctor = Doctor(
        repo_root=tmp_path,
        settings=Settings(ANTHROPIC_API_KEY="key"),
        config=DefaultConfig(jobs=JobsConfig(lock_backend="memory", require_distributed_lock=True)),
        command_runner=passing_command_runner,
        import_checker=lambda module: True,
        poetry_locator=poetry_locator,
    )

    result = doctor.check_job_runtime()

    assert result.status == "fail"
    assert "requires jobs.lock_backend=postgres or redis" in result.message


@pytest.mark.asyncio
async def test_doctor_runs_injected_db_and_migration_checks(tmp_path):
    doctor = Doctor(
        repo_root=tmp_path,
        settings=Settings(ANTHROPIC_API_KEY="key"),
        config=DefaultConfig(),
        command_runner=passing_command_runner,
        import_checker=lambda module: True,
        db_check=passing_db_check,
        migration_check=passing_migration_check,
        poetry_locator=poetry_locator,
    )

    results = await doctor.run()

    assert CheckResult.passed("Database", "fake database ok") in results
    assert CheckResult.passed("Migrations", "fake migrations ok") in results


@pytest.mark.asyncio
async def test_doctor_reports_invalid_database_settings_without_crashing(tmp_path):
    doctor = Doctor(
        repo_root=tmp_path,
        settings=Settings(
            APP_ENV="development",
            ANTHROPIC_API_KEY="key",
            DATABASE_URL_DEVELOPMENT="",
            POSTGRES_DB_DEVELOPMENT="",
        ),
        config=DefaultConfig(),
        command_runner=passing_command_runner,
        import_checker=lambda module: True,
        poetry_locator=poetry_locator,
    )

    results = await doctor.run()

    assert any(result.name == "Settings" and result.status == "fail" for result in results)
    assert any(result.name == "Database" and result.status == "fail" for result in results)
    assert any(result.name == "Migrations" and result.status == "fail" for result in results)


@pytest.mark.asyncio
async def test_doctor_fails_unsafe_production_security_settings(tmp_path):
    doctor = Doctor(
        repo_root=tmp_path,
        settings=Settings(APP_ENV="production", ANTHROPIC_API_KEY="key"),
        config=DefaultConfig(),
        command_runner=passing_command_runner,
        import_checker=lambda module: True,
        db_check=passing_db_check,
        migration_check=passing_migration_check,
        poetry_locator=poetry_locator,
    )

    results = await doctor.run()

    assert any(
        result.name == "Production security"
        and result.status == "fail"
        and "SECRET_KEY must be changed from the template default" in result.message
        for result in results
    )


@pytest.mark.asyncio
async def test_doctor_passes_explicit_production_security_settings(tmp_path):
    doctor = Doctor(
        repo_root=tmp_path,
        settings=Settings(
            APP_ENV="production",
            SECRET_KEY="x" * 32,
            TRUSTED_HOSTS="api.example.com",
            ANTHROPIC_API_KEY="key",
        ),
        config=DefaultConfig(security=SecurityConfig(cors_origins=["https://api.example.com"])),
        command_runner=passing_command_runner,
        import_checker=lambda module: True,
        db_check=passing_db_check,
        migration_check=passing_migration_check,
        poetry_locator=poetry_locator,
    )

    results = await doctor.run()

    assert CheckResult.passed("Production security", "production security settings are explicit") in results


@pytest.mark.asyncio
async def test_doctor_strict_promotes_missing_llm_credentials_to_failure(tmp_path):
    doctor = Doctor(
        repo_root=tmp_path,
        settings=Settings(ANTHROPIC_API_KEY=""),
        config=DefaultConfig(llm=LLMConfig(provider="anthropic")),
        command_runner=passing_command_runner,
        import_checker=lambda module: True,
        poetry_locator=poetry_locator,
    )

    results = await doctor.run(skip_db=True, strict=True)

    assert CheckResult.failed("LLM credentials", "ANTHROPIC_API_KEY is not set") in results


def test_doctor_script_supports_skip_db(monkeypatch, capsys):
    class FakeDoctor:
        async def run(self, **kwargs):
            assert kwargs["skip_db"] is True
            return [CheckResult.passed("Fake", "ok")]

    monkeypatch.setattr("scripts.doctor.Doctor", lambda: FakeDoctor())

    exit_code = DoctorScript().execute(["--skip-db"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "[PASS] Fake: ok" in output


def test_makefile_exposes_doctor_target():
    makefile = Path("Makefile").read_text()

    assert "doctor:" in makefile
    assert "poetry run python -m scripts.doctor" in makefile
