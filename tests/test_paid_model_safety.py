from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from contextlib import contextmanager

import httpx
import pytest

from scripts import manage
from scripts.shared.automated_tests import (
    AUTOMATED_TESTS_ENV, LIVE_EVALS_ENV, PaidModelCallBlocked,
    automated_tests_enabled, live_evals_enabled, sanitize_automated_environment,
)
from scripts.shared.env import load_dotenv
from services.graphs.model_factory import build_chat_model
from tests.test_graph_model_factory import FACTORY_ENV, model_env as model_env

ROOT = Path(__file__).resolve().parent.parent
AUTOMATED_AT_COLLECTION = automated_tests_enabled()


def test_automated_mode_is_active_at_collection():
    assert AUTOMATED_AT_COLLECTION


def test_plain_pytest_activates_protection_before_collection_despite_inherited_live_opt_in():
    env = {**os.environ, LIVE_EVALS_ENV: "1"}
    env.pop(AUTOMATED_TESTS_ENV, None)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_paid_model_safety.py", "-k", "automated_mode_is_active_at_collection"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "1 passed" in result.stdout


@pytest.fixture
def protected_model(monkeypatch, model_env):
    sends = []

    def send(*args, **kwargs):
        sends.append("sync")
        raise AssertionError("A protected model reached HTTP send")

    async def send_async(*args, **kwargs):
        sends.append("async")
        raise AssertionError("A protected model reached HTTP send")

    monkeypatch.setattr(httpx.Client, "send", send)
    monkeypatch.setattr(httpx.AsyncClient, "send", send_async)
    monkeypatch.setenv("GRAPH_MODEL_MAX_RETRIES", "0")
    return build_chat_model("opinion"), sends


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["invoke", "ainvoke", "stream", "astream"])
async def test_real_model_is_blocked_before_any_http_send(protected_model, monkeypatch, mode):
    model, sends = protected_model
    monkeypatch.setenv(LIVE_EVALS_ENV, "1")
    with pytest.raises(PaidModelCallBlocked, match="disabled in automated tests"):
        if mode == "invoke":
            model.invoke("synthetic canary")
        elif mode == "ainvoke":
            await model.ainvoke("synthetic canary")
        elif mode == "stream":
            list(model.stream("synthetic canary"))
        else:
            async for _ in model.astream("synthetic canary"):
                pytest.fail("Protected model yielded a chunk")
    assert sends == []


def test_model_guard_is_inherited_by_a_child_even_if_it_selects_production():
    code = """
import asyncio, json, os
import httpx
from scripts.shared.automated_tests import automated_tests_enabled, PaidModelCallBlocked
from services.graphs.model_factory import build_chat_model
os.environ['APP_ENV'] = 'production'
assert automated_tests_enabled()
sends = []
def send(*args, **kwargs):
    sends.append('sync')
    raise AssertionError('Child reached HTTP send')
async def send_async(*args, **kwargs):
    sends.append('async')
    raise AssertionError('Child reached HTTP send')
httpx.Client.send, httpx.AsyncClient.send = send, send_async
model = build_chat_model('opinion')
blocked = []
async def check():
    for mode in ('invoke', 'ainvoke', 'stream', 'astream'):
        try:
            if mode == 'invoke': model.invoke('synthetic canary')
            elif mode == 'ainvoke': await model.ainvoke('synthetic canary')
            elif mode == 'stream': list(model.stream('synthetic canary'))
            else:
                async for _ in model.astream('synthetic canary'): pass
        except PaidModelCallBlocked:
            blocked.append(mode)
    assert len(blocked) == 4 and not sends
asyncio.run(check())
print(json.dumps({'blocked': blocked, 'sends': len(sends)}))
"""
    env = {**os.environ, **FACTORY_ENV, "GRAPH_MODEL_MAX_RETRIES": "0", LIVE_EVALS_ENV: "1"}
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"blocked": ["invoke", "ainvoke", "stream", "astream"], "sends": 0}


@pytest.mark.parametrize("model", ["claude-test", "gpt-test", "gemini-test"])
def test_direct_evaluator_agent_is_denied_before_context_or_sdk_use(monkeypatch, model):
    from evals.shared import runner

    monkeypatch.setattr(runner, "_load_rules_context", lambda: pytest.fail("Evaluator read context before the paid-call guard"))
    monkeypatch.setenv(LIVE_EVALS_ENV, "1")
    with pytest.raises(PaidModelCallBlocked):
        runner.run_agent(model, "synthetic canary")


def test_direct_judge_is_denied_before_metric_construction(monkeypatch):
    from evals.shared import judge

    monkeypatch.setattr(judge, "GEval", lambda **kwargs: pytest.fail("Judge constructed a live metric"))
    with pytest.raises(PaidModelCallBlocked):
        judge.evaluate("synthetic", "synthetic", judge_prompt="synthetic", rule_content="synthetic")


def test_eval_cli_is_denied_before_selecting_an_environment_or_launching_pytest(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["manage", "evals"])
    monkeypatch.setattr(manage, "selected_environment", lambda *_: pytest.fail("Eval CLI selected a live environment"))
    assert manage.main() == 1
    assert "disabled in automated tests" in capsys.readouterr().err


def test_audit_forces_automated_mode_and_sanitizes_its_pytest_environment(tmp_path, monkeypatch):
    (tmp_path / ".env.test").write_text("OPENAI_API_KEY=fake-file\nLANGSMITH_TRACING=true\n")
    monkeypatch.setattr(manage, "ROOT", tmp_path)
    monkeypatch.setattr(manage, "python_executable", lambda: sys.executable)
    monkeypatch.setenv(LIVE_EVALS_ENV, "1")
    monkeypatch.setenv("PERSONA_MODEL_SERVER_API_KEY", "fake-inherited")
    captured = []

    @contextmanager
    def cluster():
        yield "postgresql://owned-db/agent_smith_test"

    monkeypatch.setattr(manage, "temporary_postgres", cluster)
    monkeypatch.setattr(manage, "checked", lambda command, **kwargs: captured.append((command, kwargs)))
    manage.audit(type("Args", (), {"backend_only": True})(), [])
    command, options = next(item for item in captured if "pytest" in item[0])
    assert "tests/" in command
    env = options["env"]
    assert env[AUTOMATED_TESTS_ENV] == "1" and env["DATABASE_URL_TEST"] == "postgresql://owned-db/agent_smith_test"
    assert not {LIVE_EVALS_ENV, "OPENAI_API_KEY", "PERSONA_MODEL_SERVER_API_KEY"} & env.keys()
    assert env["LANGSMITH_TRACING"] == "false"


@pytest.mark.parametrize("opt_in", [False, True])
def test_live_evaluation_collection_is_denied_before_database_collection(opt_in):
    env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "DATABASE_URL_TEST": ""}
    env.pop(LIVE_EVALS_ENV, None)
    if opt_in:
        env[LIVE_EVALS_ENV] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "evals/test_suite.py"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 4
    assert "Live evaluations require ./evals.sh" in result.stderr
    assert "DATABASE_URL_TEST is required" not in result.stderr


@pytest.mark.parametrize("automated,opt_in,expected", [(False, False, False), (False, True, True), (True, False, False), (True, True, False)])
def test_live_opt_in_never_overrides_automated_mode(automated, opt_in, expected):
    env = {AUTOMATED_TESTS_ENV: "1" if automated else "0", LIVE_EVALS_ENV: "1" if opt_in else "0"}
    assert live_evals_enabled(env) is expected


def test_environment_sanitization_preserves_database_and_local_embedding_settings():
    env = {
        AUTOMATED_TESTS_ENV: "1", LIVE_EVALS_ENV: "1", "OPENAI_API_KEY": "fake",
        "PERSONA_MODEL_SERVER_API_KEY": "fake", "AWS_SESSION_TOKEN": "fake", "AWS_PROFILE": "fake",
        "LANGSMITH_TRACING": "true", "DATABASE_URL_TEST": "owned-db", "MEMORY_EMBEDDING_DEVICE": "cpu",
    }
    sanitize_automated_environment(env)
    assert not {LIVE_EVALS_ENV, "OPENAI_API_KEY", "PERSONA_MODEL_SERVER_API_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE"} & env.keys()
    assert env["LANGSMITH_TRACING"] == "false"
    assert env["DATABASE_URL_TEST"] == "owned-db" and env["MEMORY_EMBEDDING_DEVICE"] == "cpu"


def test_dotenv_reload_removes_actual_inherited_credentials_and_rejects_file_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "environ", {
        AUTOMATED_TESTS_ENV: "1", LIVE_EVALS_ENV: "1", "APP_ENV": "test",
        "OPENAI_API_KEY": "fake-inherited", "LANGSMITH_TRACING": "true", "DATABASE_URL_TEST": "owned-db",
    })
    (tmp_path / ".env.test").write_text("ANTHROPIC_API_KEY=fake-file\nPERSONA_MODEL_SERVER_API_KEY=fake-file\nLANGCHAIN_TRACING_V2=true\n")
    load_dotenv(tmp_path)
    assert not {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "PERSONA_MODEL_SERVER_API_KEY", LIVE_EVALS_ENV} & os.environ.keys()
    assert os.environ["LANGCHAIN_TRACING_V2"] == os.environ["LANGSMITH_TRACING"] == "false"
    assert os.environ["DATABASE_URL_TEST"] == "owned-db"


def test_ordinary_application_environment_is_unchanged():
    env = {"OPENAI_API_KEY": "fake", LIVE_EVALS_ENV: "1", "LANGSMITH_TRACING": "true"}
    expected = dict(env)
    sanitize_automated_environment(env)
    assert env == expected
