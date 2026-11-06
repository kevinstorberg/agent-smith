from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
from typing import Any

from scripts.shared.claude_memory_redaction import redact_for_capture


_CREDENTIAL_KEYS = frozenset(
    {
        "authorization",
        "proxyauthorization",
        "cookie",
        "setcookie",
        "credentials",
        "password",
        "passwd",
        "passphrase",
        "secret",
        "token",
        "apikey",
        "accesstoken",
        "refreshtoken",
        "idtoken",
        "clientsecret",
        "privatekey",
        "awsaccesskeyid",
        "awssecretaccesskey",
        "awssessiontoken",
    }
)
_CREDENTIAL_SUFFIXES = (
    "apikey",
    "password",
    "clientsecret",
    "accesstoken",
    "refreshtoken",
    "privatekey",
    "secretaccesskey",
    "sessiontoken",
    "token",
)


def _credential_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return normalized in _CREDENTIAL_KEYS or normalized.endswith(_CREDENTIAL_SUFFIXES)


def _parameter_snapshot(value: Any, parents: set[int]) -> Any:
    if isinstance(value, str):
        # Capture-specific base64 heuristics would hide legitimate opaque search identifiers.
        return redact_for_capture(value, mask_base64=False)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else "[NONFINITE]"
    if isinstance(value, (dict, list, tuple)):
        identity = id(value)
        if identity in parents:
            return "[CIRCULAR]"
        parents.add(identity)
        try:
            if isinstance(value, dict):
                return {
                    redact_for_capture(key, mask_base64=False)
                    if isinstance(key, str)
                    else "[UNSERIALIZABLE_KEY]": "[REDACTED]"
                    if isinstance(key, str) and _credential_key(key)
                    else _parameter_snapshot(item, parents)
                    for key, item in value.items()
                }
            return [_parameter_snapshot(item, parents) for item in value]
        finally:
            parents.remove(identity)
    return "[UNSERIALIZABLE]"


@dataclass(frozen=True)
class ToolInvocation:
    agent: str
    tool: str
    params_json: str

    @classmethod
    def capture(cls, *, agent: str, tool: str, arguments: Any) -> ToolInvocation:
        return cls(
            agent=redact_for_capture(agent, mask_base64=False)
            if isinstance(agent, str) and agent.strip()
            else "unknown",
            tool=redact_for_capture(tool, mask_base64=False)
            if isinstance(tool, str) and tool.strip()
            else "unknown",
            params_json=json.dumps(
                _parameter_snapshot(arguments if arguments is not None else {}, set()),
                ensure_ascii=True,
                sort_keys=True,
                allow_nan=False,
            ),
        )

    @property
    def prefix(self) -> str:
        return " ".join(
            json.dumps(value, ensure_ascii=True)[1:-1]
            for value in (self.agent, self.tool)
        )
