from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import ci_python


@pytest.fixture
def interpreters(tmp_path):
    settings = tmp_path / "settings.json"
    calls = tmp_path / "calls.jsonl"
    settings.write_text(
        json.dumps(
            {
                "app": [{"name": "Example_Package", "version": "1.0.0"}],
                "tools": [{"name": "audit-tool", "version": "2.0"}],
                "mode": "valid",
            }
        )
    )
    script = (
        """#!INTERPRETER
import json, os, sys, time
from pathlib import Path
settings = json.loads(Path(SETTINGS).read_text())
label = Path(sys.argv[0]).name
arguments = sys.argv[1:]
with Path(CALLS).open('a') as stream:
    stream.write(json.dumps({'label': label, 'arguments': arguments,
        'pins': Path(arguments[arguments.index('--requirement') + 1]).read_text() if '--requirement' in arguments else None,
        'environment_overrides': [key for key in ('PYTHONHOME','PYTHONPATH','PIPAPI_PYTHON_LOCATION','VIRTUAL_ENV') if key in os.environ]}) + '\\n')
if arguments == ['-m','pip','check']:
    if settings.get('compatibility_failure'):
        print('synthetic incompatible dependencies', file=sys.stderr)
        raise SystemExit(7)
    print('No broken requirements found.')
elif arguments == ['-m','pip','list','--format=json']:
    print(json.dumps(settings[label]))
elif arguments[:2] == ['-m','pip_audit']:
    assert all(flag in arguments for flag in ('--requirement','--no-deps','--disable-pip','--strict','--format'))
    assert '--fix' not in arguments and '--ignore-vuln' not in arguments
    requirements = Path(arguments[arguments.index('--requirement') + 1])
    rows = [dict(zip(('name','version'), value.split('=='))) for value in requirements.read_text().splitlines()]
    rows = [{**row, 'vulns': []} for row in rows]
    mode = settings['mode']
    if mode == 'timeout':
        time.sleep(10)
    if mode == 'missing': rows = rows[1:]
    if mode == 'extra': rows.append({'name':'unexpected','version':'1','vulns':[]})
    if mode == 'duplicate': rows.append(dict(rows[0]))
    if mode == 'changed': rows[0]['version'] = '99'
    if mode == 'skipped': rows[0] = {'name':rows[0]['name'],'skip_reason':'not on registry'}
    if mode == 'vulnerable': rows[0]['vulns'] = [{'id':'TEST-ADVISORY','fix_versions':['2']}]
    if mode == 'malformed': print('not JSON')
    else: print(json.dumps({'dependencies':rows,'fixes':[]}))
    if mode == 'exit': raise SystemExit(9)
else:
    raise AssertionError(arguments)
""".replace("INTERPRETER", sys.executable)
        .replace("SETTINGS", repr(str(settings)))
        .replace("CALLS", repr(str(calls)))
    )
    directory = tmp_path / "interpreters with spaces"
    directory.mkdir()
    paths = []
    for label in ("app", "tools"):
        path = directory / label
        path.write_text(script)
        path.chmod(0o700)
        paths.append(path)
    return paths, settings, calls


def configure(settings, **changes):
    settings.write_text(json.dumps({**json.loads(settings.read_text()), **changes}))


def test_audit_covers_both_actual_inventories_without_resolving_or_leaking_overrides(
    interpreters, monkeypatch, capsys
):
    (app, tools), _, calls = interpreters
    for name in ("PYTHONHOME", "PYTHONPATH", "PIPAPI_PYTHON_LOCATION", "VIRTUAL_ENV"):
        monkeypatch.setenv(name, "hostile interpreter override")
    original_path = ci_python.os.environ["PATH"]
    ci_python.audit(app, tools)
    recorded = [json.loads(line) for line in calls.read_text().splitlines()]
    assert [row["label"] for row in recorded] == [
        "app",
        "app",
        "tools",
        "tools",
        "tools",
        "tools",
    ]
    assert all(not row["environment_overrides"] for row in recorded)
    for row in recorded:
        if row["arguments"][:2] == ["-m", "pip_audit"]:
            temporary = Path(
                row["arguments"][row["arguments"].index("--requirement") + 1]
            )
            assert not temporary.exists()
    assert "Application: audited all 1 installed packages" in capsys.readouterr().out
    assert ci_python.os.environ["PATH"] == original_path
    assert ci_python.os.environ["PYTHONPATH"] == "hostile interpreter override"


@pytest.mark.parametrize(
    "mode",
    ["missing", "extra", "duplicate", "changed", "skipped", "vulnerable", "malformed"],
)
def test_incomplete_or_unsafe_auditor_results_cannot_pass(interpreters, mode):
    (app, tools), settings, _ = interpreters
    configure(settings, mode=mode)
    with pytest.raises(ci_python.CIAuditError):
        ci_python.audit(app, tools)


@pytest.mark.parametrize(
    "inventory",
    [
        [],
        {},
        [{"name": "valid", "version": 1}],
        [{"name": "invalid/name", "version": "1"}],
        [{"name": "valid", "version": "not-a-version"}],
        [{"name": "same_name", "version": "1"}, {"name": "same-name", "version": "2"}],
    ],
)
def test_bad_installed_inventory_fails_before_any_advisory_call(
    interpreters, inventory
):
    (app, tools), settings, calls = interpreters
    configure(settings, app=inventory)
    with pytest.raises(ci_python.CIAuditError):
        ci_python.audit(app, tools)
    assert all(
        json.loads(line)["arguments"][:2] != ["-m", "pip_audit"]
        for line in calls.read_text().splitlines()
    )


@pytest.mark.parametrize(
    "configuration,code", [({"compatibility_failure": True}, 7), ({"mode": "exit"}, 9)]
)
def test_process_failures_keep_their_exit_status(interpreters, configuration, code):
    (app, tools), settings, _ = interpreters
    configure(settings, **configuration)
    with pytest.raises(subprocess.CalledProcessError) as error:
        ci_python.audit(app, tools)
    assert error.value.returncode == code
    assert (
        ci_python.main(["audit", "--python", str(app), "--tools-python", str(tools)])
        == code
    )


def test_auditor_timeout_fails_and_removes_its_temporary_inventory(
    interpreters, monkeypatch
):
    (app, tools), settings, _ = interpreters
    configure(settings, mode="timeout")
    monkeypatch.setattr(ci_python, "AUDIT_TIMEOUT", 0.1)
    original_run = ci_python.run
    inventories = []

    def record_inventory(command, **kwargs):
        if command[1:3] == ["-m", "pip_audit"]:
            inventories.append(Path(command[command.index("--requirement") + 1]))
        return original_run(command, **kwargs)

    monkeypatch.setattr(ci_python, "run", record_inventory)
    with pytest.raises(subprocess.TimeoutExpired):
        ci_python.audit(app, tools)
    assert len(inventories) == 1 and not inventories[0].exists()


def test_inventory_normalizes_names_and_semantically_equivalent_pep440_versions():
    expected = ci_python.packages(
        [{"name": "Example_Package", "version": "1.0.0"}], label="installed"
    )
    ci_python.validate_report(
        {"dependencies": [{"name": "example-package", "version": "1", "vulns": []}]},
        expected,
    )


def test_generated_audit_pins_preserve_installed_release_precision(interpreters):
    (app, tools), settings, calls = interpreters
    configure(settings, app=[{"name": "typing_extensions", "version": "4.15.0"}])
    ci_python.audit(app, tools)
    audited = [
        json.loads(line)
        for line in calls.read_text().splitlines()
        if json.loads(line)["pins"] is not None
    ]
    assert audited[0]["pins"] == "typing-extensions==4.15.0\n"
    assert audited[1]["pins"] == "audit-tool==2.0\n"


@pytest.mark.parametrize(
    "content",
    [
        "ruff>=0.8.0",
        "ruff==0.16.*",
        "ruff==0.16.10; python_version>'3'",
        "ruff==0.16.10\nruff==0.16.10",
        "ruff @ https://example.invalid/ruff.whl",
        "pytest>=8",
    ],
)
def test_invalid_ruff_authority_fails_before_creating_a_tool_environment(
    tmp_path, content
):
    (tmp_path / "requirements.txt").write_text(content)
    destination = tmp_path / "tools"
    with pytest.raises(ci_python.CIAuditError, match="ruff==version"):
        ci_python.setup_tools(destination, repository=tmp_path)
    assert not destination.exists()


def test_ruff_version_comes_only_from_the_exact_repository_requirement(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_text("pytest>=8\nruff==0.16.10 # existing authoritative tool pin\n")
    assert ci_python.ruff_requirement(path) == "ruff==0.16.10"
