import subprocess
import sys
from pathlib import Path

import pytest

from lib.cairn.generator import ResourceGenerator, parse_resource_spec


def _project_spec():
    return parse_resource_spec("project", ["name:string", "status:enum[planned,active,done]", "notes?:text"])


@pytest.mark.unit
def test_resource_generator_dry_run_returns_deterministic_file_plan(tmp_path):
    generator = ResourceGenerator(tmp_path, revision_factory=lambda: "202606041234")

    result = generator.generate(_project_spec(), dry_run=True)

    paths = [str(file.path) for file in result.planned_files]
    assert result.dry_run is True
    assert result.written_files == ()
    assert paths == [
        "db/models/__init__.py",
        "db/models/project.py",
        "db/repositories/__init__.py",
        "db/repositories/project.py",
        "src/models/project.py",
        "src/services/project.py",
        "src/routers/project.py",
        "db/migrations/versions/202606041234_create_project.py",
        "tests/project/__init__.py",
        "tests/project/test_project_schemas.py",
        "tests/project/test_project_router.py",
        "docs/resources/project.md",
    ]
    assert not (tmp_path / "src" / "routers" / "project.py").exists()


@pytest.mark.unit
def test_resource_generator_frontend_opt_in_adds_feature_file(tmp_path):
    generator = ResourceGenerator(tmp_path, revision_factory=lambda: "202606041234")

    result = generator.generate(_project_spec(), dry_run=True, frontend=True)

    planned = {str(file.path): file.content for file in result.planned_files}
    feature = planned["frontend/src/features/project/feature.tsx"]
    doc = planned["docs/resources/project.md"]
    assert "ResourceCrudPage" in feature
    assert 'endpoint: "/projects"' in feature
    assert "},," not in feature
    assert (
        'label: "Status", name: "status", optional: false, type: "enum", enumValues: ["planned", "active", "done"]'
        in feature
    )
    assert "frontend/src/features/project/feature.tsx" in doc


@pytest.mark.unit
def test_resource_generator_writes_conventional_cairn_layers(tmp_path):
    generator = ResourceGenerator(tmp_path, revision_factory=lambda: "202606041234")

    result = generator.generate(_project_spec())

    assert "src/routers/project.py" in {str(path) for path in result.written_files}
    model = (tmp_path / "db" / "models" / "project.py").read_text()
    repository = (tmp_path / "db" / "repositories" / "project.py").read_text()
    service = (tmp_path / "src" / "services" / "project.py").read_text()
    router = (tmp_path / "src" / "routers" / "project.py").read_text()
    migration = (tmp_path / "db" / "migrations" / "versions" / "202606041234_create_project.py").read_text()
    doc = (tmp_path / "docs" / "resources" / "project.md").read_text()

    assert "class Project(UUIDMixin, TimestampMixin, Base):" in model
    assert "def _enum_values(enum_cls):" in model
    assert 'SQLEnum(ProjectStatus, values_callable=_enum_values, name="project_status")' in model
    assert "class ProjectRepository(BaseRepository[Project]):" in repository
    assert "class ProjectService(ApplicationService):" in service
    assert "UnitOfWork" in service
    assert "get_unit_of_work" in router
    assert 'router = create_router(prefix="/projects", tags=["projects"])' in router
    assert 'register_router(router, name="projects")' in router
    assert 'project_status_enum = postgres_enum("project_status", ["planned", "active", "done"])' in migration
    assert "create_postgres_enum(project_status_enum)" in migration
    assert "drop_postgres_enum(project_status_enum)" in migration
    assert 'op.create_table(\n        "projects"' in migration
    assert "Source of truth:" in doc


@pytest.mark.unit
def test_resource_generator_repeated_run_fails_before_duplicate_migration(tmp_path):
    revisions = iter(["202606041234", "202606041235"])
    generator = ResourceGenerator(tmp_path, revision_factory=lambda: next(revisions))
    generator.generate(_project_spec())

    with pytest.raises(FileExistsError, match="Refusing to overwrite existing files"):
        generator.generate(_project_spec())

    migrations = list((tmp_path / "db" / "migrations" / "versions").glob("*_create_project.py"))
    assert [migration.name for migration in migrations] == ["202606041234_create_project.py"]


@pytest.mark.unit
def test_resource_generator_conflict_detection_fails_closed(tmp_path):
    generator = ResourceGenerator(tmp_path, revision_factory=lambda: "202606041234")
    existing = tmp_path / "src" / "models" / "project.py"
    existing.parent.mkdir(parents=True)
    existing.write_text("# existing app code\n")

    with pytest.raises(FileExistsError, match="Refusing to overwrite existing files"):
        generator.generate(_project_spec())

    assert existing.read_text() == "# existing app code\n"


@pytest.mark.unit
def test_resource_generator_force_overwrites_conflicts(tmp_path):
    generator = ResourceGenerator(tmp_path, revision_factory=lambda: "202606041234")
    existing = tmp_path / "src" / "models" / "project.py"
    existing.parent.mkdir(parents=True)
    existing.write_text("# existing app code\n")

    generator.generate(_project_spec(), force=True)

    assert "class ProjectCreate" in existing.read_text()


@pytest.mark.unit
def test_resource_generator_frontend_conflict_detection_uses_existing_semantics(tmp_path):
    generator = ResourceGenerator(tmp_path, revision_factory=lambda: "202606041234")
    existing = tmp_path / "frontend" / "src" / "features" / "project" / "feature.tsx"
    existing.parent.mkdir(parents=True)
    existing.write_text("// existing frontend\n")

    with pytest.raises(FileExistsError, match="Refusing to overwrite existing files"):
        generator.generate(_project_spec(), frontend=True)

    assert existing.read_text() == "// existing frontend\n"


@pytest.mark.unit
def test_resource_generator_force_reuses_single_existing_migration(tmp_path):
    revisions = iter(["202606041234", "202606041235"])
    generator = ResourceGenerator(tmp_path, revision_factory=lambda: next(revisions))
    generator.generate(_project_spec())

    result = generator.generate(_project_spec(), force=True)

    written = {str(path) for path in result.written_files}
    assert "db/migrations/versions/202606041234_create_project.py" in written
    assert not (tmp_path / "db" / "migrations" / "versions" / "202606041235_create_project.py").exists()


@pytest.mark.unit
def test_resource_generator_rejects_multiple_existing_migrations_even_with_force(tmp_path):
    versions = tmp_path / "db" / "migrations" / "versions"
    versions.mkdir(parents=True)
    (versions / "202606041234_create_project.py").write_text("# first\n")
    (versions / "202606041235_create_project.py").write_text("# second\n")
    generator = ResourceGenerator(tmp_path, revision_factory=lambda: "202606041236")

    with pytest.raises(FileExistsError, match="Multiple existing migrations match resource"):
        generator.generate(_project_spec(), force=True)


@pytest.mark.unit
def test_generated_python_files_compile(tmp_path):
    generator = ResourceGenerator(tmp_path, revision_factory=lambda: "202606041234")
    result = generator.generate(_project_spec(), dry_run=True)

    for file in result.planned_files:
        if file.path.suffix == ".py" and file.content:
            compile(file.content, str(file.path), "exec")


@pytest.mark.unit
def test_generated_python_files_pass_ruff_checks(tmp_path):
    generator = ResourceGenerator(tmp_path, revision_factory=lambda: "202606041234")
    generator.generate(_project_spec(), frontend=True)
    python_paths = [str(path) for path in tmp_path.rglob("*.py") if "__pycache__" not in path.parts]

    check = subprocess.run(
        [sys.executable, "-m", "ruff", "check", *python_paths],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert check.returncode == 0, check.stdout + check.stderr

    format_check = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--check", *python_paths],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert format_check.returncode == 0, format_check.stdout + format_check.stderr


@pytest.mark.unit
def test_generator_docs_quote_shell_sensitive_examples():
    doc = Path("docs/GENERATOR.md").read_text()

    assert "project name:string 'status:enum[planned,active,done]' 'due_date?:date'" in doc
    assert "Quote enum and optional field specs" in doc
