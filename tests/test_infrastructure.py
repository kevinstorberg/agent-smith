import tomllib
from pathlib import Path

import pytest
import yaml


def _workflow(name: str) -> dict:
    workflow_path = Path(__file__).parents[1] / ".github" / "workflows" / name
    return yaml.safe_load(workflow_path.read_text())


@pytest.mark.unit
def test_framework_loads():
    """Verify pytest discovers and runs tests."""
    assert True


@pytest.mark.unit
def test_markers_registered(pytestconfig):
    """Verify custom markers are registered in pyproject.toml."""
    marker_strings = pytestconfig.getini("markers")
    marker_names = {m.split(":")[0].strip() for m in marker_strings}
    assert "unit" in marker_names
    assert "integration" in marker_names
    assert "e2e" in marker_names
    assert "eval" in marker_names


@pytest.mark.unit
def test_src_package_importable():
    """Verify the src package can be imported."""
    import src

    assert src is not None


@pytest.mark.unit
def test_test_database_url_uses_settings(monkeypatch):
    from src.settings import reset_settings
    from tests.conftest import get_test_database_url

    monkeypatch.setenv("DATABASE_URL_TEST", "")
    monkeypatch.setenv("POSTGRES_HOST", "127.0.0.1")
    monkeypatch.setenv("POSTGRES_PORT", "55432")
    monkeypatch.setenv("POSTGRES_USER", "fixture_user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "fixture_password")
    monkeypatch.setenv("POSTGRES_DB_TEST", "fixture_test_db")
    reset_settings()

    try:
        assert (
            get_test_database_url()
            == "postgresql+asyncpg://fixture_user:fixture_password@127.0.0.1:55432/fixture_test_db"
        )
    finally:
        reset_settings()


@pytest.mark.unit
def test_docker_compose_database_port_is_configurable():
    compose_path = Path(__file__).parents[1] / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text())

    db_service = compose["services"]["db"]
    app_environment = compose["services"]["app"]["environment"]

    assert db_service["image"] == "${POSTGRES_IMAGE:-pgvector/pgvector:pg16}"
    assert db_service["ports"] == ["${POSTGRES_PORT:-5432}:5432"]
    assert app_environment["POSTGRES_HOST"] == "db"
    assert app_environment["POSTGRES_PORT"] == 5432
    assert app_environment["DATABASE_URL_DEVELOPMENT"] == ""


@pytest.mark.unit
def test_docker_compose_redis_port_is_configurable_and_app_uses_service_url():
    compose_path = Path(__file__).parents[1] / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text())

    redis_service = compose["services"]["redis"]
    app_environment = compose["services"]["app"]["environment"]

    assert redis_service["ports"] == ["${REDIS_PORT:-6379}:6379"]
    assert app_environment["REDIS_URL"] == "redis://redis:6379/0"


@pytest.mark.unit
def test_docker_compose_app_port_is_configurable():
    compose_path = Path(__file__).parents[1] / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text())

    app_service = compose["services"]["app"]

    assert app_service["ports"] == ["${APP_PORT:-8000}:8000"]


@pytest.mark.unit
def test_docker_compose_frontend_service_is_profile_gated_and_port_configurable():
    compose_path = Path(__file__).parents[1] / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text())

    frontend_service = compose["services"]["frontend"]

    assert frontend_service["profiles"] == ["frontend"]
    assert frontend_service["image"] == "node:22-alpine"
    assert frontend_service["ports"] == ["${FRONTEND_PORT:-5173}:5173"]
    assert frontend_service["working_dir"] == "/app/frontend"
    assert "npm ci && npm run dev" in frontend_service["command"]


@pytest.mark.unit
def test_dockerfile_defines_production_runtime_contract():
    dockerfile = (Path(__file__).parents[1] / "Dockerfile").read_text()
    runtime_stage = dockerfile.split("FROM python:3.11-slim AS runtime", 1)[1]

    assert "FROM python:3.11-slim AS builder" in dockerfile
    assert "FROM python:3.11-slim AS runtime" in dockerfile
    assert "COPY --from=builder /opt/venv /opt/venv" in dockerfile
    assert "USER cairn" in runtime_stage
    assert "HEALTHCHECK" in runtime_stage
    assert "/health" in runtime_stage
    assert '"uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8000"' in runtime_stage
    assert "poetry install" not in runtime_stage


@pytest.mark.unit
def test_dockerignore_excludes_local_state_from_production_context():
    patterns = set((Path(__file__).parents[1] / ".dockerignore").read_text().splitlines())

    assert {".env*", ".git", ".claude", ".pytest_cache", ".ruff_cache", ".coverage", "storage", "tmp"} <= patterns
    assert {"frontend/node_modules", "frontend/.vite", "frontend/coverage"} <= patterns
    assert "frontend/dist" not in patterns
    assert "!.env.default" not in patterns


@pytest.mark.unit
def test_ci_workflows_run_on_push_and_pull_request_for_all_branches():
    for workflow_name in ("test.yml", "pre-commit.yml", "security.yml"):
        triggers = _workflow(workflow_name)["on"]

        assert triggers["push"] == {}
        assert triggers["pull_request"] == {}


@pytest.mark.unit
def test_ci_enforces_coverage_threshold():
    workflow = _workflow("test.yml")
    steps = workflow["jobs"]["test"]["steps"]
    test_step = next(step for step in steps if step.get("name") == "Run tests with coverage")

    assert "--cov-fail-under=85" in test_step["run"]


@pytest.mark.unit
def test_ci_runs_frontend_checks():
    workflow = _workflow("test.yml")
    steps = workflow["jobs"]["test"]["steps"]
    commands = [step.get("run", "") for step in steps]
    setup_node = next(step for step in steps if step.get("uses") == "actions/setup-node@v4")

    assert setup_node["with"]["node-version"] == "22"
    assert setup_node["with"]["cache-dependency-path"] == "frontend/package-lock.json"
    assert "npm --prefix frontend ci" in commands
    assert "npm --prefix frontend run check" in commands


@pytest.mark.unit
def test_makefile_coverage_target_enforces_threshold():
    makefile = (Path(__file__).parents[1] / "Makefile").read_text()

    assert "--cov-fail-under=85" in makefile
    assert "$(PYTEST) tests/ -v --cov" in makefile


@pytest.mark.unit
def test_dependabot_updates_python_dependencies_and_actions():
    dependabot_path = Path(__file__).parents[1] / ".github" / "dependabot.yml"
    config = yaml.safe_load(dependabot_path.read_text())
    ecosystems = {entry["package-ecosystem"] for entry in config["updates"]}
    npm_entry = next(entry for entry in config["updates"] if entry["package-ecosystem"] == "npm")

    assert config["version"] == 2
    assert ecosystems == {"pip", "github-actions", "npm"}
    assert npm_entry["directory"] == "/frontend"
    assert all(entry["schedule"]["interval"] == "weekly" for entry in config["updates"])


@pytest.mark.unit
def test_security_workflow_checks_lockfile_vulnerabilities_and_secrets():
    workflow = _workflow("security.yml")
    jobs = workflow["jobs"]

    assert {"lockfile-freshness", "dependency-vulnerability-scan", "secret-scan"} <= set(jobs)
    lock_steps = jobs["lockfile-freshness"]["steps"]
    vulnerability_steps = jobs["dependency-vulnerability-scan"]["steps"]
    secret_steps = jobs["secret-scan"]["steps"]
    vulnerability_commands = [step.get("run", "") for step in vulnerability_steps]

    assert any(step.get("run") == "make lock-check" for step in lock_steps)
    assert any(
        "poetry install --no-interaction --with aws,redis,pinecone,pgvector,documentdb,graph-postgres" == command
        for command in vulnerability_commands
    )
    assert any(command == "make audit" for command in vulnerability_commands)
    assert any(command == "npm --prefix frontend ci" for command in vulnerability_commands)
    assert any(command == "make frontend-audit" for command in vulnerability_commands)
    assert all("pip install --upgrade" not in command for command in vulnerability_commands)
    assert all("--ignore-vuln" not in command for command in vulnerability_commands)
    assert any(step.get("uses") == "gitleaks/gitleaks-action@v2" for step in secret_steps)


@pytest.mark.unit
def test_pre_commit_checks_for_private_keys():
    config_path = Path(__file__).parents[1] / ".pre-commit-config.yaml"
    config = yaml.safe_load(config_path.read_text())
    hook_ids = {hook["id"] for repo in config["repos"] for hook in repo["hooks"]}

    assert "detect-private-key" in hook_ids


@pytest.mark.unit
def test_pre_commit_workflow_uses_poetry_managed_tooling():
    workflow = _workflow("pre-commit.yml")
    commands = [step.get("run", "") for step in workflow["jobs"]["pre-commit"]["steps"]]

    assert "poetry install --no-interaction" in commands
    assert "make pre-commit" in commands
    assert "pip install pre-commit" not in commands


@pytest.mark.unit
def test_makefile_lock_check_uses_poetry_lock_validation():
    makefile = (Path(__file__).parents[1] / "Makefile").read_text()

    assert "TEST_APP_ENV ?= test" in makefile
    assert "PYTEST = APP_ENV=$(TEST_APP_ENV) poetry run pytest" in makefile
    assert "$(PYTEST) tests/ -v" in makefile
    assert "lock-check:" in makefile
    assert "poetry check --lock" in makefile
    assert "frontend-check:" in makefile
    assert "FRONTEND_NPM = npm --prefix $(FRONTEND_DIR)" in makefile
    assert "$(FRONTEND_NPM) run check" in makefile
    assert "check: lock-check lint format-check test frontend-check" in makefile


@pytest.mark.unit
def test_makefile_exposes_local_security_targets():
    makefile = (Path(__file__).parents[1] / "Makefile").read_text()

    assert "audit:" in makefile
    assert "poetry run pip-audit --progress-spinner off" in makefile
    assert "frontend-audit:" in makefile
    assert "$(FRONTEND_NPM) run audit" in makefile
    assert "pre-commit:" in makefile
    assert "poetry run pre-commit run --all-files --show-diff-on-failure" in makefile
    assert "security: lock-check audit frontend-audit pre-commit" in makefile


@pytest.mark.unit
def test_local_security_tools_are_poetry_dev_dependencies():
    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    dev_dependencies = pyproject["tool"]["poetry"]["group"]["dev"]["dependencies"]

    assert "pre-commit" in dev_dependencies
    assert "pip-audit" in dev_dependencies


@pytest.mark.unit
def test_readme_links_repository_service_and_graph_runtime_docs():
    readme = (Path(__file__).parents[1] / "README.md").read_text()

    assert "docs/REPOSITORIES_SERVICES.md" in readme
    assert "docs/AUTHORIZATION.md" in readme
    assert "docs/JOBS.md" in readme
    assert "docs/ADMIN_DEBUG.md" in readme
    assert "docs/GENERATOR.md" in readme
    assert "src/graphs/endpoints.py" in readme
    assert "src/jobs/" in readme
    assert "src/diagnostics/" in readme
    assert "lib/cairn/generator" in readme
    assert "docs/FRONTEND.md" in readme
    assert "frontend/src/shared/api/" in readme
    assert "src/frontend/static.py" in readme
    assert "build_config_summary_graph()" in readme


@pytest.mark.unit
def test_admin_debug_docs_reference_source_of_truth_modules():
    docs = (Path(__file__).parents[1] / "docs" / "ADMIN_DEBUG.md").read_text()

    assert "src/diagnostics/" in docs
    assert "src/diagnostics/router.py" in docs
    assert "scripts/inspect.py" in docs
    assert "config/default.yaml" in docs


@pytest.mark.unit
def test_generator_docs_reference_source_of_truth_modules():
    docs = (Path(__file__).parents[1] / "docs" / "GENERATOR.md").read_text()

    assert "scripts/cli.py" in docs
    assert "scripts/generate.py" in docs
    assert "lib/cairn/generator/" in docs
    assert "src/routers/registry.py" in docs
    assert "--frontend" in docs


@pytest.mark.unit
def test_frontend_docs_reference_source_of_truth_modules():
    docs = (Path(__file__).parents[1] / "docs" / "FRONTEND.md").read_text()

    assert "frontend/package.json" in docs
    assert "frontend/src/shared/config/" in docs
    assert "frontend/src/shared/api/" in docs
    assert "frontend/src/features/registry.ts" in docs
    assert "src/frontend/static.py" in docs


@pytest.mark.unit
def test_jobs_docs_reference_runtime_source_of_truth():
    jobs_doc = (Path(__file__).parents[1] / "docs" / "JOBS.md").read_text()

    assert "src/jobs/definitions.py" in jobs_doc
    assert "src/jobs/runner.py" in jobs_doc
    assert "src/jobs/stores.py" in jobs_doc
    assert "src/jobs/locks.py" in jobs_doc
    assert "GET /jobs/health" in jobs_doc


@pytest.mark.unit
def test_deployment_docs_describe_production_security_controls():
    deployment = (Path(__file__).parents[1] / "docs" / "DEPLOYMENT.md").read_text()

    assert ".env.default" in deployment
    assert "src/settings.py" in deployment
    assert "config/default.yaml" in deployment
    assert "config/models.py" in deployment
    assert "request body size limits" in deployment
    assert "edge or WAF rate limiting" in deployment


@pytest.mark.unit
def test_deployment_docs_distinguish_production_dockerfile_from_local_compose():
    deployment = (Path(__file__).parents[1] / "docs" / "DEPLOYMENT.md").read_text()

    assert "[Dockerfile](../Dockerfile)" in deployment
    assert "production image source of" in deployment
    assert "truth" in deployment
    assert "[docker-compose.yml](../docker-compose.yml) for local development" in deployment
    assert "docker build -t cairn-app ." in deployment
    assert "docker run --rm -p 8000:8000 --env-file <runtime-env-file> cairn-app" in deployment


@pytest.mark.unit
def test_graph_postgres_checkpointing_is_optional_dependency_group():
    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    group = pyproject["tool"]["poetry"]["group"]["graph-postgres"]

    assert group["optional"] is True
    assert "langgraph-checkpoint-postgres" in group["dependencies"]
