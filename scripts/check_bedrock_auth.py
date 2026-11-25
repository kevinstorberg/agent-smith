from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

import httpx

from services.graphs.bedrock_auth import (
    BedrockAuthenticationError,
    BedrockProfileTokenProvider,
)
from services.graphs.model_config import BedrockProfileAuth


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify an AWS profile with STS and Bedrock model discovery; invokes no model."
    )
    parser.add_argument("--profile", required=True)
    parser.add_argument("--expected-account", required=True)
    parser.add_argument("--region", required=True)
    args = parser.parse_args(argv)
    try:
        authentication = BedrockProfileAuth(args.profile, args.expected_account)
        server_url = f"https://bedrock-mantle.{args.region}.api.aws/v1"
        token = BedrockProfileTokenProvider(authentication, server_url)()
        with httpx.Client(
            timeout=httpx.Timeout(15, connect=5),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = client.get(
                f"{server_url}/models", headers={"Authorization": f"Bearer {token}"}
            )
        if response.status_code != 200:
            print(
                f"Bedrock auth check failed: model discovery HTTP {response.status_code}",
                file=sys.stderr,
            )
            return 1
        payload = response.json()
        models = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(models, list):
            print(
                "Bedrock auth check failed: invalid model discovery response",
                file=sys.stderr,
            )
            return 1
    except (BedrockAuthenticationError, ValueError, httpx.HTTPError):
        print(
            "Bedrock auth check failed: verify the explicit profile, expected account, region, and AWS access",
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "profile": authentication.profile_name,
                "account": authentication.expected_account_id,
                "region": args.region,
                "status": "verified",
                "models_count": len(models),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
