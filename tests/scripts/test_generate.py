import tomllib
from pathlib import Path

import pytest

from scripts.cli import main as cairn_main
from scripts.generate import GenerateScript


@pytest.mark.unit
def test_generate_script_dry_run_prints_plan_without_writing(tmp_path, capsys):
    status = GenerateScript().execute(
        ["resource", "project", "name:string", "status:enum[planned,active]", "--dry-run", "--repo-root", str(tmp_path)]
    )

    output = capsys.readouterr()

    assert status == 0
    assert "Planned: src/routers/project.py" in output.out
    assert not (tmp_path / "src" / "routers" / "project.py").exists()


@pytest.mark.unit
def test_generate_script_frontend_dry_run_prints_feature_plan(tmp_path, capsys):
    status = GenerateScript().execute(
        [
            "resource",
            "project",
            "name:string",
            "--frontend",
            "--dry-run",
            "--repo-root",
            str(tmp_path),
        ]
    )

    output = capsys.readouterr()

    assert status == 0
    assert "Planned: frontend/src/features/project/feature.tsx" in output.out
    assert not (tmp_path / "frontend" / "src" / "features" / "project" / "feature.tsx").exists()


@pytest.mark.unit
def test_generate_script_reports_invalid_specs_without_traceback(tmp_path, capsys):
    status = GenerateScript().execute(["resource", "project", "id:uuid", "--repo-root", str(tmp_path)])

    output = capsys.readouterr()

    assert status == 1
    assert "generate: Field 'id' is managed by Cairn base models" in output.err


@pytest.mark.unit
def test_generate_script_reports_conflicts_without_overwriting(tmp_path, capsys):
    target = tmp_path / "src" / "models" / "project.py"
    target.parent.mkdir(parents=True)
    target.write_text("# existing\n")

    status = GenerateScript().execute(["resource", "project", "name:string", "--repo-root", str(tmp_path)])

    output = capsys.readouterr()

    assert status == 1
    assert "Refusing to overwrite existing files" in output.err
    assert target.read_text() == "# existing\n"


@pytest.mark.unit
def test_cairn_cli_dispatches_generate_resource(tmp_path, capsys):
    status = cairn_main(["generate", "resource", "project", "name:string", "--dry-run", "--repo-root", str(tmp_path)])

    output = capsys.readouterr()

    assert status == 0
    assert "Planned: db/models/project.py" in output.out


@pytest.mark.unit
def test_pyproject_exposes_cairn_console_command():
    pyproject = tomllib.loads((Path(__file__).parents[2] / "pyproject.toml").read_text())

    assert pyproject["project"]["scripts"]["cairn"] == "scripts.cli:main"
