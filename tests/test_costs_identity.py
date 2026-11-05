from datetime import timedelta
import json
from types import SimpleNamespace

import pytest

from services.costs import service
from services.costs.cache import SnapshotCache
from tests.test_costs import NOW, page, report


FIRST = "111111111111"
SECOND = "222222222222"


@pytest.fixture
def aws(monkeypatch, tmp_path):
    boto3 = pytest.importorskip("boto3")
    from botocore.credentials import Credentials
    from botocore.exceptions import ClientError

    monkeypatch.setenv("AWS_COSTS_ENABLED", "true")
    monkeypatch.setenv("AWS_COSTS_ACCOUNT_ID", FIRST)
    monkeypatch.setenv("COSTS_CACHE_PATH", str(tmp_path))
    for name in (
        "AWS_COSTS_PROFILE",
        "AWS_PROFILE",
        "AWS_CONFIG_FILE",
        "AWS_SHARED_CREDENTIALS_FILE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        "scripts.shared.automated_tests.automated_tests_enabled", lambda: False
    )
    state = SimpleNamespace(
        account=FIRST,
        access="PRIVATE_ACCESS_ONE",
        secret="PRIVATE_SECRET_ONE",
        token="PRIVATE_TOKEN_ONE",
        error=None,
        calls=[],
        closed=[],
        sessions=[],
        after_identity=lambda: None,
    )

    class Client:
        def __init__(self, session, name, kwargs):
            self.session, self.name, self.kwargs = session, name, kwargs

        def close(self):
            state.closed.append(self.name)

        def get_caller_identity(self):
            state.calls.append(("sts", self.session.account, self.kwargs))
            if state.error:
                raise ClientError(
                    {
                        "Error": {
                            "Code": state.error,
                            "Message": "PRIVATE_PROVIDER_DETAIL",
                        }
                    },
                    "GetCallerIdentity",
                )
            state.after_identity()
            return {"Account": self.session.account}

        def get_cost_and_usage(self, **kwargs):
            state.calls.append(("ce", self.session.account, self.kwargs))
            return page("1.25" if self.session.account == FIRST else "2.50")

    class Session:
        def __init__(self, **kwargs):
            self.account = state.account
            self.credentials = Credentials(state.access, state.secret, state.token)
            state.sessions.append(kwargs)

        def get_credentials(self):
            return self.credentials

        def client(self, name, **kwargs):
            return Client(self, name, kwargs)

    monkeypatch.setattr(boto3, "Session", Session)
    return state, tmp_path


def calls(state, name):
    return [entry for entry in state.calls if entry[0] == name]


@pytest.mark.parametrize(
    "pin", [None, "", "REPLACE_WITH_ACCOUNT_ID", "123", " 111111111111", "11111111111x"]
)
def test_enabled_costs_require_account_pin_before_credentials_or_provider(
    aws, monkeypatch, pin
):
    state, directory = aws
    if pin is None:
        monkeypatch.delenv("AWS_COSTS_ACCOUNT_ID")
    else:
        monkeypatch.setenv("AWS_COSTS_ACCOUNT_ID", pin)
    result = service.read_aws_costs(NOW)
    assert result["state"] == "not_configured"
    assert "AWS_COSTS_ACCOUNT_ID" in result["error"]["message"]
    assert not state.calls and not state.sessions
    assert not list(directory.glob("*.json"))


def test_disabled_costs_do_not_require_pin_or_touch_sdk(aws, monkeypatch):
    state, _ = aws
    monkeypatch.setenv("AWS_COSTS_ENABLED", "false")
    monkeypatch.delenv("AWS_COSTS_ACCOUNT_ID")
    assert service.read_aws_costs(NOW)["state"] == "disabled"
    assert not state.calls and not state.sessions


def test_wrong_account_is_rejected_before_billable_collection(aws):
    state, directory = aws
    state.account = SECOND
    result = service.read_aws_costs(NOW)
    assert result["state"] == "not_configured"
    assert result["report"] is None
    assert result["error"]["code"] == "account_mismatch"
    assert FIRST in result["error"]["message"] and SECOND in result["error"]["message"]
    assert len(calls(state, "sts")) == 1 and not calls(state, "ce")
    assert state.closed == ["sts"]
    assert not list(directory.glob("*.json"))


def test_warm_cache_cannot_hide_same_profile_account_switch(aws):
    state, _ = aws
    assert service.read_aws_costs(NOW)["state"] == "ready"
    state.account, state.access = SECOND, "PRIVATE_ACCESS_TWO"
    result = service.read_aws_costs(NOW + timedelta(seconds=15))
    assert result["state"] == "not_configured"
    assert result["report"] is None
    assert len(calls(state, "sts")) == 2 and len(calls(state, "ce")) == 1


def test_each_poll_verifies_current_identity_without_refetching_paid_report(aws):
    state, _ = aws
    for seconds in (0, 15, 30, 45):
        result = service.read_aws_costs(NOW + timedelta(seconds=seconds))
        assert result["state"] == "ready" and result["report"]["total"] == "1.25"
    assert len(state.sessions) == len(calls(state, "sts")) == 4
    assert len(calls(state, "ce")) == 1


@pytest.mark.parametrize("field", ["access", "secret", "token"])
def test_same_account_credential_rotation_verifies_without_extra_paid_refresh(
    aws, field
):
    state, _ = aws
    service.read_aws_costs(NOW)
    setattr(state, field, "PRIVATE_ROTATED_VALUE")
    result = service.read_aws_costs(NOW + timedelta(seconds=15))
    assert result["state"] == "ready" and result["report"]["total"] == "1.25"
    assert len(calls(state, "sts")) == 2 and len(calls(state, "ce")) == 1


def test_target_account_has_a_separate_paid_cache_and_returning_reuses_original(
    aws, monkeypatch
):
    state, directory = aws
    first = service.read_aws_costs(NOW)
    state.account, state.access = SECOND, "PRIVATE_ACCESS_TWO"
    monkeypatch.setenv("AWS_COSTS_ACCOUNT_ID", SECOND)
    second = service.read_aws_costs(NOW + timedelta(seconds=15))
    state.account, state.access = FIRST, "PRIVATE_ACCESS_ONE"
    monkeypatch.setenv("AWS_COSTS_ACCOUNT_ID", FIRST)
    returned = service.read_aws_costs(NOW + timedelta(seconds=30))
    assert first["report"]["total"] == returned["report"]["total"] == "1.25"
    assert second["report"]["total"] == "2.50"
    assert len(calls(state, "ce")) == 2 and len(list(directory.glob("*.json"))) == 2


def test_same_frozen_credentials_reach_identity_and_billing_despite_ambient_change(
    aws, monkeypatch
):
    state, _ = aws

    def change():
        state.account, state.access, state.secret, state.token = (
            SECOND,
            "OTHER_ACCESS",
            "OTHER_SECRET",
            "OTHER_TOKEN",
        )
        monkeypatch.setenv("AWS_COSTS_ACCOUNT_ID", SECOND)
        monkeypatch.setenv("AWS_COSTS_PROFILE", "different-profile")

    state.after_identity = change
    result = service.read_aws_costs(NOW)
    assert result["state"] == "ready"
    assert result["report"]["account_id"] == FIRST
    assert state.sessions == [{"profile_name": None}]
    identity, collection = calls(state, "sts")[0][2], calls(state, "ce")[0][2]
    for field, value in [
        ("aws_access_key_id", "PRIVATE_ACCESS_ONE"),
        ("aws_secret_access_key", "PRIVATE_SECRET_ONE"),
        ("aws_session_token", "PRIVATE_TOKEN_ONE"),
    ]:
        assert identity[field] == collection[field] == value
    assert identity["config"].retries["total_max_attempts"] == 1
    assert (
        identity["config"].connect_timeout == 5
        and identity["config"].read_timeout == 10
    )
    assert state.closed == ["sts", "ce"]


def test_current_identity_failure_never_returns_a_previous_cached_account(aws):
    state, _ = aws
    service.read_aws_costs(NOW)
    state.error = "ExpiredToken"
    result = service.read_aws_costs(NOW + timedelta(seconds=15))
    assert result["state"] in {"failed", "not_configured"}
    assert result["report"] is None
    assert len(calls(state, "sts")) == 2 and len(calls(state, "ce")) == 1
    assert "PRIVATE" not in json.dumps(result)


def test_account_id_is_explicit_report_metadata_not_parsed_from_scope_text(aws):
    result = service.read_aws_costs(NOW)
    assert result["report"]["account_id"] == FIRST
    assert "PRIVATE" not in json.dumps(result)


@pytest.mark.parametrize("account", [None, SECOND])
def test_wrong_or_unbound_cached_report_is_rejected_instead_of_relabelled(aws, account):
    state, directory = aws
    service.read_aws_costs(NOW)
    path = next(directory.glob("*.json"))
    value = json.loads(path.read_text())
    value["report"]["account_id"] = account
    path.write_text(json.dumps(value))
    result = service.read_aws_costs(NOW + timedelta(seconds=15))
    assert result["report"] is None
    assert result["error"]["code"] == "invalid_snapshot"
    assert len(calls(state, "ce")) == 1


@pytest.mark.parametrize("explicit_profile", [False, True])
def test_native_env_keys_win_unless_cost_profile_is_explicit(
    monkeypatch, tmp_path, explicit_profile
):
    boto3 = pytest.importorskip("boto3")

    config = tmp_path / "config"
    config.write_text(
        "[profile existing]\nregion=us-east-1\naws_access_key_id=PROFILE_ACCESS\naws_secret_access_key=PROFILE_SECRET\n"
    )
    credentials = tmp_path / "credentials"
    credentials.write_text("")
    for name, value in {
        "AWS_COSTS_ENABLED": "true",
        "AWS_PROFILE": "existing",
        "AWS_CONFIG_FILE": str(config),
        "AWS_SHARED_CREDENTIALS_FILE": str(credentials),
        "AWS_ACCESS_KEY_ID": "ENV_ACCESS",
        "AWS_SECRET_ACCESS_KEY": "ENV_SECRET",
        "AWS_SESSION_TOKEN": "ENV_TOKEN",
        "AWS_EC2_METADATA_DISABLED": "true",
        "COSTS_CACHE_PATH": str(tmp_path / "cache"),
        "AWS_COSTS_ACCOUNT_ID": SECOND if explicit_profile else FIRST,
    }.items():
        monkeypatch.setenv(name, value)
    if explicit_profile:
        monkeypatch.setenv("AWS_COSTS_PROFILE", "existing")
    else:
        monkeypatch.delenv("AWS_COSTS_PROFILE", raising=False)
    monkeypatch.setattr(
        "scripts.shared.automated_tests.automated_tests_enabled", lambda: False
    )
    native_session = boto3.Session
    selected = []

    def factory(**kwargs):
        session = native_session(**kwargs)
        resolved = session.get_credentials()
        selected.append(resolved.method)

        class Client:
            def close(self):
                pass

            def get_caller_identity(self):
                return {"Account": FIRST if resolved.method == "env" else SECOND}

            def get_cost_and_usage(self, **kwargs):
                return page("1.25")

        session.client = lambda *args, **kwargs: Client()
        return session

    monkeypatch.setattr(boto3, "Session", factory)
    result = service.read_aws_costs(NOW)
    assert result["state"] == "ready"
    assert selected == ["config-file" if explicit_profile else "env"]


def test_legacy_profile_only_snapshot_is_untouched_and_not_trusted(aws):
    state, directory = aws
    old = SnapshotCache(directory, "aws", "default-chain:::2026-11-01")
    old.read_or_refresh(NOW, report)
    original = old.path.read_bytes()
    result = service.read_aws_costs(NOW + timedelta(seconds=15))
    assert result["report"]["total"] == "1.25"
    assert old.path.read_bytes() == original
    assert len(calls(state, "ce")) == 1 and len(list(directory.glob("*.json"))) == 2


def test_frozen_auth_objects_and_private_snapshots_do_not_reveal_credentials(aws):
    from services.costs.aws import prepare_aws

    _, directory = aws
    prepared = prepare_aws(expected_account=FIRST)
    assert "PRIVATE" not in repr(prepared) + repr(prepared.credentials)
    service.read_aws_costs(NOW)
    assert all("PRIVATE" not in path.read_text() for path in directory.glob("*.json"))


@pytest.mark.parametrize("account", [None, "invalid", "١١١١١١١١١١١١"])
def test_malformed_sts_account_fails_before_billing(aws, account):
    state, _ = aws
    state.account = account
    result = service.read_aws_costs(NOW)
    assert result["error"]["code"] == "invalid_response"
    assert result["report"] is None and not calls(state, "ce")


def test_router_rejects_account_switch_on_a_cached_read(aws, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from services.api.routers import costs

    state, _ = aws
    monkeypatch.setattr(costs, "read_aws_costs", lambda: service.read_aws_costs(NOW))
    app = FastAPI()
    app.include_router(costs.router, prefix="/api/costs")
    with TestClient(app) as client:
        assert client.get("/api/costs/aws").json()["state"] == "ready"
        state.account, state.access = SECOND, "PRIVATE_ACCESS_TWO"
        result = client.get("/api/costs/aws").json()
        assert result["error"]["code"] == "account_mismatch"
        assert result["report"] is None and len(calls(state, "ce")) == 1


def test_mismatched_generated_report_is_never_persisted(aws, monkeypatch):
    _, directory = aws
    wrong = report().model_copy(update={"account_id": SECOND})
    monkeypatch.setattr(service, "fetch_aws", lambda *args, **kwargs: wrong)
    result = service.read_aws_costs(NOW)
    assert result["error"]["code"] == "invalid_snapshot" and result["report"] is None
    assert json.loads(next(directory.glob("*.json")).read_text())["report"] is None


def test_account_binding_is_rechecked_after_cache_refresh_returns(aws, monkeypatch):
    _, _ = aws
    original = SnapshotCache.read_or_refresh

    def changed(cache, *args):
        result = original(cache, *args)
        result["report"]["account_id"] = SECOND
        return result

    monkeypatch.setattr(SnapshotCache, "read_or_refresh", changed)
    result = service.read_aws_costs(NOW)
    assert result["error"]["code"] == "invalid_snapshot" and result["report"] is None
