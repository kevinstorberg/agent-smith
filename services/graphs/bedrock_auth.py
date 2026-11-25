from __future__ import annotations

from contextlib import closing
from datetime import timedelta
import logging
from threading import Lock

from aws_bedrock_token_generator import provide_token
from botocore.config import Config
from botocore.credentials import CredentialProvider, ReadOnlyCredentials
from botocore.session import Session

from scripts.shared.automated_tests import require_model_calls_allowed
from services.graphs.model_config import BedrockProfileAuth, bedrock_profile_region
from services.observability import billable_operation

_TOKEN_EXPIRY = timedelta(minutes=15)
_logger = logging.getLogger(__name__)
_PROFILE_CREDENTIAL_PROVIDERS = frozenset(
    {
        "assume-role",
        "assume-role-with-web-identity",
        "sso",
        "shared-credentials-file",
        "login",
        "custom-process",
        "config-file",
    }
)


class BedrockAuthenticationError(RuntimeError):
    pass


class _FrozenCredentialProvider(CredentialProvider):
    def __init__(self, credentials: ReadOnlyCredentials) -> None:
        self._credentials = credentials

    def load(self) -> ReadOnlyCredentials:
        return self._credentials


class BedrockProfileTokenProvider:
    def __init__(self, authentication: BedrockProfileAuth, server_url: str) -> None:
        self._authentication = authentication
        self._region = bedrock_profile_region(server_url)
        self._session: Session | None = None
        self._verified_credentials: ReadOnlyCredentials | None = None
        self._lock = Lock()

    def __call__(self) -> str:
        require_model_calls_allowed()
        with self._lock:
            frozen = self._freeze_credentials()
            if frozen != self._verified_credentials:
                self._verify_account(frozen)
                self._verified_credentials = frozen
                _logger.info(
                    "Bedrock authentication verified: profile=%s account=%s region=%s",
                    self._authentication.profile_name,
                    self._authentication.expected_account_id,
                    self._region,
                )
            try:
                token = provide_token(
                    region=self._region,
                    aws_credentials_provider=_FrozenCredentialProvider(frozen),
                    expiry=_TOKEN_EXPIRY,
                )
            except Exception:
                raise BedrockAuthenticationError(
                    "Unable to generate the AWS profile's Bedrock token"
                ) from None
            if not isinstance(token, str) or not token.startswith("bedrock-api-key-"):
                raise BedrockAuthenticationError(
                    "AWS Bedrock token generator returned an invalid token"
                )
            return token

    def _freeze_credentials(self) -> ReadOnlyCredentials:
        try:
            if self._session is None:
                session = Session(profile=self._authentication.profile_name)
                # Login/assume-role refresh clients inherit these bounds as well as STS.
                session.set_default_client_config(
                    Config(
                        connect_timeout=5,
                        read_timeout=10,
                        retries={"total_max_attempts": 1},
                        ignore_configured_endpoint_urls=True,
                    )
                )
                resolver = session.get_component("credential_provider")
                # An empty named profile must not fall through to ambient host credentials.
                for provider in tuple(resolver.providers):
                    if provider.METHOD not in _PROFILE_CREDENTIAL_PROVIDERS:
                        resolver.remove(provider.METHOD)
                self._session = session
            credentials = self._session.get_credentials()
            if credentials is None:
                raise BedrockAuthenticationError(
                    "GRAPH_MODEL_AWS_PROFILE has no AWS credentials"
                )
            return credentials.get_frozen_credentials()
        except BedrockAuthenticationError:
            raise
        except Exception:
            raise BedrockAuthenticationError(
                "Unable to resolve GRAPH_MODEL_AWS_PROFILE credentials"
            ) from None

    def _verify_account(self, frozen: ReadOnlyCredentials) -> None:
        assert self._session is not None, (
            "AWS credentials must be resolved before identity verification"
        )
        try:
            # STS must authenticate the same snapshot that will sign the bearer token.
            with closing(
                self._session.create_client(
                    "sts",
                    region_name=self._region,
                    aws_access_key_id=frozen.access_key,
                    aws_secret_access_key=frozen.secret_key,
                    aws_session_token=frozen.token,
                )
            ) as client:
                with billable_operation(
                    "aws_sts",
                    "get_caller_identity",
                    source="model_auth",
                    reason="bedrock_routing",
                    billing="nonbillable",
                    sdk_retries=0,
                ):
                    response = client.get_caller_identity()
        except Exception:
            raise BedrockAuthenticationError(
                "Unable to verify GRAPH_MODEL_AWS_PROFILE with AWS STS"
            ) from None
        if (
            not isinstance(response, dict)
            or response.get("Account") != self._authentication.expected_account_id
        ):
            raise BedrockAuthenticationError(
                "AWS profile account does not match GRAPH_MODEL_AWS_ACCOUNT_ID"
            )
