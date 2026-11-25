from __future__ import annotations

import json

import httpx
import pytest

from scripts import check_bedrock_auth
from scripts.shared.automated_tests import PaidModelCallBlocked
from services.graphs.bedrock_auth import BedrockAuthenticationError

ARGS = [
    "--profile",
    "test-profile",
    "--expected-account",
    "111122223333",
    "--region",
    "us-east-1",
]
TOKEN = "bedrock-api-key-fake-not-for-output"


@pytest.fixture
def check(monkeypatch):
    captured = {
        "calls": [],
        "status": 200,
        "data": {"data": [{"id": "do-not-print-model"}]},
        "error": None,
    }

    class Client:
        def __init__(self, **kwargs):
            captured["options"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, **kwargs):
            captured["calls"].append((url, kwargs))
            return httpx.Response(captured["status"], json=captured["data"])

    def provider(authentication, url):
        captured["authentication"] = authentication
        captured["url"] = url

        def token():
            if captured["error"]:
                raise captured["error"]
            return TOKEN

        return token

    monkeypatch.setattr(check_bedrock_auth, "BedrockProfileTokenProvider", provider)
    monkeypatch.setattr(check_bedrock_auth.httpx, "Client", Client)
    return captured


def test_check_uses_the_runtime_provider_and_only_lists_models(check, capsys):
    assert check_bedrock_auth.main(ARGS) == 0
    output = capsys.readouterr()
    assert json.loads(output.out) == {
        "profile": "test-profile",
        "account": "111122223333",
        "region": "us-east-1",
        "status": "verified",
        "models_count": 1,
    }
    assert TOKEN not in output.out and "do-not-print-model" not in output.out
    assert check["calls"] == [
        (
            "https://bedrock-mantle.us-east-1.api.aws/v1/models",
            {
                "headers": {"Authorization": f"Bearer {TOKEN}"},
            },
        )
    ]
    assert check["options"]["follow_redirects"] is False
    assert check["options"]["trust_env"] is False
    assert check["options"]["timeout"].connect == 5
    assert check["options"]["timeout"].read == 15


@pytest.mark.parametrize("status", [301, 401, 403, 404, 500])
def test_check_reports_failed_discovery_without_retries_or_response_body(
    check, capsys, status
):
    check["status"] = status
    check["data"] = {"secret": TOKEN}
    assert check_bedrock_auth.main(ARGS) == 1
    output = capsys.readouterr()
    assert str(status) in output.err
    assert not output.out and TOKEN not in output.err
    assert len(check["calls"]) == 1


def test_failed_identity_does_not_send_bearer_request(check, capsys):
    check["error"] = BedrockAuthenticationError("do-not-print-raw-error")
    assert check_bedrock_auth.main(ARGS) == 1
    assert not check["calls"]
    output = capsys.readouterr()
    assert not output.out and "do-not-print-raw-error" not in output.err


def test_check_rejects_invalid_discovery_shape(check, capsys):
    check["data"] = {"unexpected": TOKEN}
    assert check_bedrock_auth.main(ARGS) == 1
    assert TOKEN not in capsys.readouterr().err


def test_real_check_is_blocked_in_automated_mode_before_aws(monkeypatch):
    from services.graphs import bedrock_auth

    monkeypatch.setattr(
        bedrock_auth, "Session", lambda **k: pytest.fail("AWS accessed")
    )
    with pytest.raises(PaidModelCallBlocked):
        check_bedrock_auth.main(ARGS)
