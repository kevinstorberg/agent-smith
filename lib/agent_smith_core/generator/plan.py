from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from lib.agent_smith_core.generator.render import (
    render_frontend_feature,
    render_migration,
    render_model,
    render_repository,
    render_resource_doc,
    render_router,
    render_router_test,
    render_schema,
    render_schema_test,
    render_service,
)
from lib.agent_smith_core.generator.spec import ResourceSpec

_SHARED_PACKAGE_FILES = {
    Path("db") / "models" / "__init__.py",
    Path("db") / "repositories" / "__init__.py",
}


@dataclass(frozen=True)
class PlannedFile:
    path: Path
    content: str


@dataclass(frozen=True)
class GenerateResult:
    planned_files: tuple[PlannedFile, ...]
    written_files: tuple[Path, ...]
    dry_run: bool


class ResourceGenerator:
    def __init__(
        self,
        repo_root: Path,
        *,
        revision_factory: Callable[[], str] | None = None,
    ) -> None:
        self.repo_root = repo_root
        self._revision_factory = revision_factory or _default_revision

    def plan(
        self,
        spec: ResourceSpec,
        *,
        frontend: bool = False,
        migration_path: Path | None = None,
    ) -> tuple[PlannedFile, ...]:
        migration = migration_path or self._new_migration_path(spec)
        revision = _revision_from_migration_path(migration, spec)
        files = [
            PlannedFile(Path("db") / "models" / "__init__.py", ""),
            PlannedFile(Path("db") / "models" / f"{spec.name}.py", render_model(spec)),
            PlannedFile(Path("db") / "repositories" / "__init__.py", ""),
            PlannedFile(Path("db") / "repositories" / f"{spec.name}.py", render_repository(spec)),
            PlannedFile(Path("src") / "models" / f"{spec.name}.py", render_schema(spec)),
            PlannedFile(Path("src") / "services" / f"{spec.name}.py", render_service(spec)),
            PlannedFile(Path("src") / "routers" / f"{spec.name}.py", render_router(spec)),
            PlannedFile(
                migration,
                render_migration(spec, revision=revision),
            ),
            PlannedFile(Path("tests") / spec.name / "__init__.py", ""),
            PlannedFile(Path("tests") / spec.name / f"test_{spec.name}_schemas.py", render_schema_test(spec)),
            PlannedFile(Path("tests") / spec.name / f"test_{spec.name}_router.py", render_router_test(spec)),
        ]
        if frontend:
            files.append(
                PlannedFile(
                    Path("frontend") / "src" / "features" / spec.name / "feature.tsx",
                    render_frontend_feature(spec),
                )
            )
        files.append(
            PlannedFile(Path("docs") / "resources" / f"{spec.name}.md", render_resource_doc(spec, frontend=frontend))
        )
        return tuple(files)

    def generate(
        self,
        spec: ResourceSpec,
        *,
        dry_run: bool = False,
        force: bool = False,
        frontend: bool = False,
    ) -> GenerateResult:
        existing_migrations = self._existing_resource_migrations(spec)
        if len(existing_migrations) > 1:
            formatted = ", ".join(str(path) for path in existing_migrations)
            raise FileExistsError(f"Multiple existing migrations match resource {spec.name!r}: {formatted}")

        migration_path = existing_migrations[0] if force and existing_migrations else None
        planned_files = self.plan(spec, frontend=frontend, migration_path=migration_path)
        conflicts = self._conflicts_for_generation(planned_files, existing_migrations, force=force)
        if conflicts and not force:
            formatted = ", ".join(str(path) for path in conflicts)
            raise FileExistsError(f"Refusing to overwrite existing files: {formatted}")

        if dry_run:
            return GenerateResult(planned_files=planned_files, written_files=(), dry_run=True)

        written: list[Path] = []
        for file in planned_files:
            target = self.repo_root / file.path
            if self._should_skip_write(file):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(_ensure_trailing_newline(file.content))
            written.append(file.path)
        return GenerateResult(planned_files=planned_files, written_files=tuple(written), dry_run=False)

    def _new_migration_path(self, spec: ResourceSpec) -> Path:
        revision = self._revision_factory()
        return Path("db") / "migrations" / "versions" / f"{revision}_create_{spec.name}.py"

    def _existing_resource_migrations(self, spec: ResourceSpec) -> tuple[Path, ...]:
        versions_dir = self.repo_root / "db" / "migrations" / "versions"
        if not versions_dir.exists():
            return ()
        return tuple(
            sorted(
                path.relative_to(self.repo_root)
                for path in versions_dir.glob(f"*_create_{spec.name}.py")
                if path.is_file()
            )
        )

    def _conflicts_for_generation(
        self,
        planned_files: tuple[PlannedFile, ...],
        existing_migrations: tuple[Path, ...],
        *,
        force: bool,
    ) -> list[Path]:
        conflicts: list[Path] = []
        if not force:
            for file in planned_files:
                if self._should_skip_write(file):
                    continue
                if self._resource_artifact_exists(file) or self._conflicts(file):
                    conflicts.append(file.path)
            for path in existing_migrations:
                if path not in conflicts:
                    conflicts.append(path)
            return conflicts

        return conflicts

    def _conflicts(self, file: PlannedFile) -> bool:
        target = self.repo_root / file.path
        if not target.exists():
            return False
        return target.read_text() != _ensure_trailing_newline(file.content)

    def _resource_artifact_exists(self, file: PlannedFile) -> bool:
        target = self.repo_root / file.path
        if not target.exists():
            return False
        return file.path not in _SHARED_PACKAGE_FILES

    def _should_skip_write(self, file: PlannedFile) -> bool:
        target = self.repo_root / file.path
        return file.path in _SHARED_PACKAGE_FILES and target.exists() and not file.content


def _default_revision() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def _revision_from_migration_path(path: Path, spec: ResourceSpec) -> str:
    suffix = f"_create_{spec.name}"
    stem = path.stem
    if not stem.endswith(suffix):
        raise ValueError(f"Migration path {path} does not match resource {spec.name!r}")
    revision = stem[: -len(suffix)]
    if not revision:
        raise ValueError(f"Migration path {path} does not include a revision")
    return revision


def _ensure_trailing_newline(content: str) -> str:
    if not content:
        return ""
    return content if content.endswith("\n") else f"{content}\n"
