import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import audit_hook


@pytest.mark.parametrize(
    "url,marker",
    [
        ("http://localhost:7654/api/audit/events", "NONBILLABLE"),
        ("https://remote.example/ingest?key=PRIVATE_URL_TOKEN", "BILLABLE?"),
    ],
)
def test_hook_transport_entry_precedes_actual_post_without_payload(
    monkeypatch, caplog, url, marker
):
    monkeypatch.setenv("AUDIT_INGEST_URL", url)
    caplog.set_level("INFO", logger="agent_smith.audit_hook")
    called = []

    def post(request, timeout):
        records = [r for r in caplog.records if r.name == "agent_smith.audit_hook"]
        assert len(records) == 1
        assert records[0].getMessage().startswith(f"AUDIT INGEST [{marker}]")
        called.append(json.loads(request.data))
        return type("Response", (), {"close": lambda self: None})()

    monkeypatch.setattr(audit_hook.urllib.request, "urlopen", post)
    assert (
        audit_hook.run(
            ["--phase", "pre"],
            json.dumps(
                {"tool_name": "Bash", "tool_input": {"command": "PRIVATE_COMMAND"}}
            ),
        )
        == 0
    )
    assert called[0]["tool_input"] == {"command": "PRIVATE_COMMAND"}
    assert (
        "PRIVATE_COMMAND" not in caplog.text and "PRIVATE_URL_TOKEN" not in caplog.text
    )


def test_standalone_hook_needs_only_stdlib_and_failure_stays_silent_on_stdout(tmp_path):
    script = Path(audit_hook.__file__).resolve()
    program = """
import json, os, runpy, sys, urllib.request
def fail(*args, **kwargs):
    raise OSError('PRIVATE_TRANSPORT_TOKEN')
urllib.request.urlopen = fail
os.environ['AUDIT_DEBUG'] = '1'
module = runpy.run_path(sys.argv[1])
assert module['run'](['--phase', 'pre'], json.dumps({'tool_name': 'Bash', 'tool_input': {'command': 'PRIVATE_COMMAND'}})) == 0
assert not any(name == 'services' or name.startswith('services.') for name in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-S", "-c", program, str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0 and result.stdout == ""
    assert "AUDIT INGEST [NONBILLABLE]" in result.stderr
    assert (
        "PRIVATE_TRANSPORT_TOKEN" not in result.stderr
        and "PRIVATE_COMMAND" not in result.stderr
    )


def test_hook_logging_failure_does_not_prevent_original_transport(monkeypatch):
    def failed_log(*args, **kwargs):
        raise OSError("PRIVATE_LOGGING_FAILURE")

    calls = []
    monkeypatch.setattr(audit_hook, "write_log", failed_log)
    monkeypatch.setattr(
        audit_hook.urllib.request,
        "urlopen",
        lambda *a, **k: (
            calls.append(True) or type("Response", (), {"close": lambda self: None})()
        ),
    )
    assert audit_hook.run(["--phase", "pre"], "{}") == 0
    assert calls == [True]
