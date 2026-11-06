from __future__ import annotations

import re

_PRIVATE_KEY = re.compile(r"-----[A-Z ]*PRIVATE KEY-----")
_BASE64_LINE = re.compile(r"(?m)^[A-Za-z0-9+/]{48,}={0,2}$")
_SECRET = re.compile(
    r"""(?im)\b(?:api[_-]?key|password|secret|access[_-]?token|authorization)\b["']?\s*[:=]\s*[^\n,;]+"""
    r"|\bBearer\s+[A-Za-z0-9._~+/-]+=*"
    r"|\b(?:sk-[A-Za-z0-9_-]{16,}|AKIA[A-Z0-9]{16})\b"
    r"|\b\d{3}-\d{2}-\d{4}\b"
    r"|\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?)://[^\s/@]+:[^\s/@]+@"
)


def _mask(text: str) -> str:
    return "".join("\n" if character == "\n" else "*" for character in text)


def redact_for_capture(text: str, *, mask_base64: bool = True) -> str:
    # Preserve source offsets while masking the whole block before pagination.
    if _PRIVATE_KEY.search(text) or (mask_base64 and _BASE64_LINE.search(text)):
        return _mask(text)
    return _SECRET.sub(lambda match: _mask(match.group()), text)
