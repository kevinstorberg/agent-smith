from __future__ import annotations

import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from threading import Event
from time import monotonic
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx2
import pytest
from aws_bedrock_token_generator import provide_token
from botocore.credentials import ReadOnlyCredentials
from langchain_openai import ChatOpenAI

from scripts.shared.automated_tests import (
    PaidModelCallBlocked,
    require_model_calls_allowed,
)
from services.graphs import bedrock_auth
from services.graphs.bedrock_auth import (
    BedrockAuthenticationError,
    BedrockProfileTokenProvider,
)
from services.graphs.model_config import BedrockProfileAuth

ACCOUNT = "180425283135"
AUTH = BedrockProfileAuth("paralign-source", ACCOUNT)
RUNTIME = "https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1"
MANTLE = "https://bedrock-mantle.us-west-2.api.aws/v1"
FIRST = ReadOnlyCredentials("ASIAFAKEFIRST", "fake-secret-one", "fake-session-one")
SECOND = ReadOnlyCredentials("ASIAFAKESECOND", "fake-secret-two", "fake-session-two")


@pytest.fixture
def sdk(monkeypatch):
    state = SimpleNamespace(
        snapshot=FIRST,
        account=ACCOUNT,
        sessions=[],
        configs=[],
        clients=[],
        signed=[],
        freezes=0,
        closes=0,
        sts_calls=0,
        credentials=True,
        freeze_error=None,
        session_error=None,
        sts_error=None,
        token_error=None,
        during_sts=None,
        removed=[],
    )

    class Credentials:
        def get_frozen_credentials(self):
            state.freezes += 1
            if state.freeze_error:
                raise state.freeze_error
            return state.snapshot

    class Client:
        def get_caller_identity(self):
            state.sts_calls += 1
            if state.during_sts:
                state.during_sts()
            if state.sts_error:
                raise state.sts_error
            return {"Account": state.account}

        def close(self):
            state.closes += 1

    class Resolver:
        providers = [
            SimpleNamespace(METHOD=name)
            for name in [
                "login",
                "env",
                "container-role",
                "iam-role",
                "boto-config",
                "ec2-credentials-file",
            ]
        ]

        def remove(self, name):
            state.removed.append(name)

    class Session:
        def __init__(self, *, profile):
            state.sessions.append(profile)
            if state.session_error:
                raise state.session_error

        def set_default_client_config(self, config):
            state.configs.append(config)

        def get_component(self, name):
            assert name == "credential_provider"
            return Resolver()

        def get_credentials(self):
            return Credentials() if state.credentials else None

        def create_client(self, service, **kwargs):
            state.clients.append((service, kwargs))
            return Client()

    def token(*, region, aws_credentials_provider, expiry):
        if state.token_error:
            raise state.token_error
        state.signed.append((region, aws_credentials_provider.load(), expiry))
        return "bedrock-api-key-fake-" + str(len(state.signed))

    monkeypatch.setattr(bedrock_auth, "Session", Session)
    monkeypatch.setattr(bedrock_auth, "provide_token", token)
    monkeypatch.setattr(
        bedrock_auth, "billable_operation", lambda *a, **k: nullcontext()
    )
    monkeypatch.setattr(bedrock_auth, "require_model_calls_allowed", lambda: None)
    return state


def test_provider_is_lazy_and_uses_explicit_profile_and_bounded_aws_endpoints(
    sdk, monkeypatch
):
    monkeypatch.setenv("AWS_PROFILE", "another-profile")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ambient-fake-key")
    monkeypatch.setenv("AWS_ENDPOINT_URL_STS", "https://untrusted.invalid")
    provider = BedrockProfileTokenProvider(AUTH, RUNTIME)
    assert not sdk.sessions
    provider()
    assert sdk.sessions == ["paralign-source"]
    assert set(sdk.removed) == {
        "env",
        "container-role",
        "iam-role",
        "boto-config",
        "ec2-credentials-file",
    }
    config = sdk.configs[0]
    assert (config.connect_timeout, config.read_timeout, config.retries) == (
        5,
        10,
        {"total_max_attempts": 1},
    )
    assert config.ignore_configured_endpoint_urls is True
    assert sdk.clients == [
        (
            "sts",
            {
                "region_name": "us-east-1",
                "aws_access_key_id": FIRST.access_key,
                "aws_secret_access_key": FIRST.secret_key,
                "aws_session_token": FIRST.token,
            },
        )
    ]
    assert sdk.closes == 1


def test_each_request_freezes_credentials_and_rotated_snapshot_is_reverified(sdk):
    provider = BedrockProfileTokenProvider(AUTH, RUNTIME)
    assert provider() != provider()
    assert (sdk.freezes, sdk.sts_calls, len(sdk.signed)) == (2, 1, 2)
    sdk.snapshot = SECOND
    provider()
    assert (sdk.freezes, sdk.sts_calls, len(sdk.signed)) == (3, 2, 3)
    assert [entry[1] for entry in sdk.signed] == [FIRST, FIRST, SECOND]
    assert sdk.clients[-1][1]["aws_access_key_id"] == SECOND.access_key


def test_sts_and_signing_share_one_snapshot_despite_a_concurrent_credential_change(sdk):
    sdk.during_sts = lambda: setattr(sdk, "snapshot", SECOND)
    BedrockProfileTokenProvider(AUTH, RUNTIME)()
    assert sdk.freezes == 1
    assert sdk.clients[0][1]["aws_access_key_id"] == FIRST.access_key
    assert sdk.signed[0][1] == FIRST


@pytest.mark.parametrize("initial", [True, False])
def test_wrong_account_never_generates_a_bearer_token(sdk, initial):
    provider = BedrockProfileTokenProvider(AUTH, RUNTIME)
    if not initial:
        provider()
        sdk.snapshot = SECOND
    before = len(sdk.signed)
    sdk.account = "716067668072"
    with pytest.raises(
        BedrockAuthenticationError, match="does not match GRAPH_MODEL_AWS_ACCOUNT_ID"
    ):
        provider()
    assert len(sdk.signed) == before
    assert sdk.closes == sdk.sts_calls


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("credentials", False, "has no AWS credentials"),
        (
            "session_error",
            RuntimeError("do-not-log-secret"),
            "resolve GRAPH_MODEL_AWS_PROFILE",
        ),
        (
            "freeze_error",
            RuntimeError("do-not-log-secret"),
            "resolve GRAPH_MODEL_AWS_PROFILE",
        ),
        (
            "sts_error",
            RuntimeError("do-not-log-secret"),
            "verify GRAPH_MODEL_AWS_PROFILE",
        ),
        ("token_error", RuntimeError("do-not-log-secret"), "generate the AWS profile"),
    ],
)
def test_failures_are_closed_and_do_not_expose_credentials(sdk, field, value, message):
    setattr(sdk, field, value)
    provider = BedrockProfileTokenProvider(AUTH, RUNTIME)
    with pytest.raises(BedrockAuthenticationError, match=message) as error:
        provider()
    assert "do-not-log-secret" not in str(error.value)
    assert error.value.__suppress_context__ or field == "credentials"
    assert not sdk.signed
    assert FIRST.secret_key not in repr(provider)
    assert FIRST.token not in repr(provider)


def test_sts_failure_is_not_cached_and_client_is_closed(sdk):
    provider = BedrockProfileTokenProvider(AUTH, RUNTIME)
    sdk.sts_error = RuntimeError("timeout")
    with pytest.raises(BedrockAuthenticationError):
        provider()
    sdk.sts_error = None
    provider()
    assert sdk.sts_calls == sdk.closes == 2


def test_concurrent_requests_share_only_the_last_verified_snapshot(sdk):
    provider = BedrockProfileTokenProvider(AUTH, RUNTIME)
    with ThreadPoolExecutor(max_workers=8) as pool:
        tokens = list(pool.map(lambda _: provider(), range(8)))
    assert len(set(tokens)) == 8
    assert sdk.freezes == 8 and sdk.sts_calls == 1


def test_automated_mode_blocks_before_credential_or_token_access(sdk, monkeypatch):
    monkeypatch.setattr(
        bedrock_auth, "require_model_calls_allowed", require_model_calls_allowed
    )
    monkeypatch.setenv("AGENT_SMITH_AUTOMATED_TESTS", "1")
    with pytest.raises(PaidModelCallBlocked):
        BedrockProfileTokenProvider(AUTH, RUNTIME)()
    assert not sdk.sessions and not sdk.clients and not sdk.signed


def test_official_generator_signs_the_verified_frozen_snapshot_and_region(
    sdk, monkeypatch
):
    monkeypatch.setattr(bedrock_auth, "provide_token", provide_token)
    token = BedrockProfileTokenProvider(AUTH, MANTLE)()
    decoded = base64.b64decode(token.removeprefix("bedrock-api-key-")).decode()
    query = parse_qs(urlparse("https://" + decoded).query)
    assert query["X-Amz-Credential"][0].startswith(FIRST.access_key + "/")
    assert "/us-west-2/bedrock/aws4_request" in query["X-Amz-Credential"][0]
    assert query["X-Amz-Security-Token"] == [FIRST.token]
    assert query["X-Amz-Expires"] == ["900"]


def _response(request, *, stream):
    if not stream:
        return httpx2.Response(
            200,
            json={
                "id": "fake",
                "object": "chat.completion",
                "created": 0,
                "model": "synthetic",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )
    return httpx2.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=(
            'data: {"id":"fake","object":"chat.completion.chunk","created":0,"model":"synthetic",'
            '"choices":[{"index":0,"delta":{"role":"assistant","content":"ok"},"finish_reason":null}]}\n\n'
            'data: {"id":"fake","object":"chat.completion.chunk","created":0,"model":"synthetic",'
            '"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
        ),
    )


@pytest.mark.parametrize("stream", [False, True])
def test_real_transport_refreshes_sync_async_and_streamed_request_headers(sdk, stream):
    seen = []

    def handler(request):
        seen.append(request.headers["authorization"])
        return _response(request, stream=stream)

    with httpx2.Client(transport=httpx2.MockTransport(handler)) as sync:

        async def run():
            async with httpx2.AsyncClient(
                transport=httpx2.MockTransport(handler)
            ) as asynchronous:
                model = ChatOpenAI(
                    model="synthetic",
                    base_url=RUNTIME,
                    max_retries=0,
                    api_key=BedrockProfileTokenProvider(AUTH, RUNTIME),
                    http_client=sync,
                    http_async_client=asynchronous,
                )
                if stream:
                    assert (
                        "".join(chunk.content for chunk in model.stream("fake")) == "ok"
                    )
                    assert (
                        "".join(
                            [chunk.content async for chunk in model.astream("fake")]
                        )
                        == "ok"
                    )
                else:
                    assert model.invoke("fake").content == "ok"
                    assert (await model.ainvoke("fake")).content == "ok"

        asyncio.run(run())
    assert seen == ["Bearer bedrock-api-key-fake-1", "Bearer bedrock-api-key-fake-2"]
    assert sdk.freezes == 2 and sdk.sts_calls == 1


def test_real_sdk_retry_requests_a_new_token(sdk):
    seen = []

    def handler(request):
        seen.append(request.headers["authorization"])
        if len(seen) == 1:
            return httpx2.Response(
                500, json={"error": {"message": "synthetic", "type": "server_error"}}
            )
        return _response(request, stream=False)

    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        model = ChatOpenAI(
            model="synthetic",
            base_url=RUNTIME,
            max_retries=1,
            api_key=BedrockProfileTokenProvider(AUTH, RUNTIME),
            http_client=client,
        )
        assert model.invoke("fake").content == "ok"
    assert seen == ["Bearer bedrock-api-key-fake-1", "Bearer bedrock-api-key-fake-2"]


def test_slow_credential_verification_runs_off_the_async_event_loop(sdk):
    started, release = Event(), Event()

    def slow_sts():
        started.set()
        release.wait(3)

    sdk.during_sts = slow_sts
    with httpx2.Client(
        transport=httpx2.MockTransport(lambda r: _response(r, stream=False))
    ) as sync:

        async def run():
            async with httpx2.AsyncClient(
                transport=httpx2.MockTransport(lambda r: _response(r, stream=False))
            ) as client:
                model = ChatOpenAI(
                    model="synthetic",
                    base_url=RUNTIME,
                    max_retries=0,
                    api_key=BedrockProfileTokenProvider(AUTH, RUNTIME),
                    http_client=sync,
                    http_async_client=client,
                )
                before = monotonic()
                task = asyncio.create_task(model.ainvoke("fake"))
                try:
                    assert await asyncio.to_thread(started.wait, 1)
                    await asyncio.sleep(0)
                    assert monotonic() - before < 1
                    assert not task.done()
                finally:
                    release.set()
                    await task

        asyncio.run(run())


def test_real_botocore_ignores_custom_identity_endpoint(monkeypatch, tmp_path):
    from botocore.session import Session

    config = tmp_path / "config"
    config.write_text(
        "[profile paralign-source]\nregion=us-east-1\nendpoint_url=https://global.invalid\n"
    )
    credentials = tmp_path / "credentials"
    credentials.write_text("")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(config))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(credentials))
    monkeypatch.setenv("AWS_ENDPOINT_URL_STS", "https://sts-override.invalid")
    monkeypatch.setenv("AWS_ENDPOINT_URL", "https://ambient.invalid")
    session = Session(profile="paralign-source")
    monkeypatch.setattr(
        session,
        "get_credentials",
        lambda: SimpleNamespace(get_frozen_credentials=lambda: FIRST),
    )
    create_client = session.create_client
    endpoints = []

    def client(service, **kwargs):
        result = create_client(service, **kwargs)
        endpoints.append(result.meta.endpoint_url)
        monkeypatch.setattr(result, "get_caller_identity", lambda: {"Account": ACCOUNT})
        return result

    monkeypatch.setattr(session, "create_client", client)
    monkeypatch.setattr(bedrock_auth, "Session", lambda **kwargs: session)
    monkeypatch.setattr(bedrock_auth, "require_model_calls_allowed", lambda: None)
    monkeypatch.setattr(
        bedrock_auth, "billable_operation", lambda *a, **k: nullcontext()
    )
    BedrockProfileTokenProvider(AUTH, RUNTIME)()
    assert endpoints == ["https://sts.us-east-1.amazonaws.com"]


def test_real_empty_profile_cannot_use_ambient_credentials(monkeypatch, tmp_path):
    from botocore.session import Session

    config = tmp_path / "config"
    config.write_text("[profile paralign-source]\nregion=us-east-1\n")
    credentials = tmp_path / "credentials"
    credentials.write_text("")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(config))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(credentials))
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ambient-fake-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "ambient-fake-secret")
    monkeypatch.setenv(
        "AWS_CONTAINER_CREDENTIALS_FULL_URI", "https://container.invalid"
    )
    session = Session(profile="paralign-source")
    resolver = session.get_component("credential_provider")
    for provider in resolver.providers:
        if provider.METHOD not in bedrock_auth._PROFILE_CREDENTIAL_PROVIDERS:
            monkeypatch.setattr(
                provider,
                "load",
                lambda: pytest.fail("Ambient credential provider executed"),
            )
    monkeypatch.setattr(bedrock_auth, "Session", lambda **kwargs: session)
    monkeypatch.setattr(bedrock_auth, "require_model_calls_allowed", lambda: None)
    with pytest.raises(BedrockAuthenticationError, match="has no AWS credentials"):
        BedrockProfileTokenProvider(AUTH, RUNTIME)()


def test_automated_environment_removes_model_profile_identifiers():
    from scripts.shared.automated_tests import sanitize_automated_environment

    settings = {
        "AGENT_SMITH_AUTOMATED_TESTS": "1",
        "GRAPH_MODEL_AUTH_MODE": "aws_profile",
        "GRAPH_MODEL_AWS_PROFILE": "paralign-source",
        "GRAPH_MODEL_AWS_ACCOUNT_ID": "180425283135",
    }
    sanitize_automated_environment(settings)
    assert "GRAPH_MODEL_AUTH_MODE" not in settings
    assert "GRAPH_MODEL_AWS_PROFILE" not in settings
    assert "GRAPH_MODEL_AWS_ACCOUNT_ID" not in settings


def test_activated_environment_sanitizes_authentication_before_normal_test_fakes():
    from scripts.shared.automated_tests import sanitize_automated_environment
    from services.graphs.model_config import BedrockApiKeyAuth, load_model_config
    from tests.test_graph_model_factory import API_KEY, FACTORY_ENV

    inherited = {
        **FACTORY_ENV,
        "AGENT_SMITH_AUTOMATED_TESTS": "1",
        "GRAPH_MODEL_AUTH_MODE": "aws_profile",
        "GRAPH_MODEL_AWS_PROFILE": "paralign-source",
        "GRAPH_MODEL_AWS_ACCOUNT_ID": ACCOUNT,
    }
    sanitize_automated_environment(inherited)
    assert (
        not {
            "GRAPH_MODEL_AUTH_MODE",
            "GRAPH_MODEL_AWS_PROFILE",
            "GRAPH_MODEL_AWS_ACCOUNT_ID",
        }
        & inherited.keys()
    )
    inherited["OPINION_MODEL_SERVER_API_KEY"] = API_KEY
    assert load_model_config(
        "opinion", env=inherited
    ).authentication == BedrockApiKeyAuth(API_KEY)
