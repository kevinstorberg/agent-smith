from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping

AUTOMATED_TESTS_ENV = "AGENT_SMITH_AUTOMATED_TESTS"
LIVE_EVALS_ENV = "AGENT_SMITH_EVAL_RUN"
_CREDENTIALS = {
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN",
    "AWS_BEARER_TOKEN_BEDROCK", "AWS_PROFILE", "AWS_DEFAULT_PROFILE",
    "AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE",
}
_TRACING_DISABLED = {
    "LANGCHAIN_TRACING": "false", "LANGCHAIN_TRACING_V2": "false",
    "LANGSMITH_TRACING": "false", "OTEL_SDK_DISABLED": "true",
}


class PaidModelCallBlocked(RuntimeError):
    pass


def automated_tests_enabled(env: Mapping[str, str] | None = None) -> bool:
    return (os.environ if env is None else env).get(AUTOMATED_TESTS_ENV) == "1"


def require_model_calls_allowed() -> None:
    if automated_tests_enabled():
        raise PaidModelCallBlocked("Paid model requests are disabled in automated tests; use a scripted model or fake agent.")


def live_evals_enabled(env: Mapping[str, str] | None = None) -> bool:
    values = os.environ if env is None else env
    return not automated_tests_enabled(values) and values.get(LIVE_EVALS_ENV) == "1"


def sanitize_automated_environment(env: MutableMapping[str, str]) -> None:
    if not automated_tests_enabled(env):
        return
    for name in tuple(env):
        if name in _CREDENTIALS or name.endswith(("_API_KEY", "_API_TOKEN")):
            env.pop(name, None)
    env.pop(LIVE_EVALS_ENV, None)
    env.update(_TRACING_DISABLED)


def activate_automated_tests() -> None:
    os.environ[AUTOMATED_TESTS_ENV] = "1"
    sanitize_automated_environment(os.environ)
