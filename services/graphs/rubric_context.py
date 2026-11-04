from __future__ import annotations

import json
import logging
import re

from deepagents.middleware.rubric import RubricMiddleware, RubricState

logger = logging.getLogger(__name__)

_EMPTY_TRANSCRIPT = re.compile(
    r"(?m)^<transcript-([0-9a-f]{16})>\n\(empty transcript\)\n</transcript-\1>$"
)
_MODEL_MESSAGE_FIELDS = {
    "type", "role", "content", "id", "name", "tool_calls", "invalid_tool_calls", "tool_call_id", "status",
}


class FullContextRubricMiddleware(RubricMiddleware):
    def _build_grader_payload(
        self,
        state: RubricState,
        iteration: int,
        correction: str | None = None,
    ) -> str:
        # Keep the pinned vendor's grading/security envelope authoritative.
        payload = super()._build_grader_payload({**state, "messages": []}, iteration, correction)
        matches = list(_EMPTY_TRANSCRIPT.finditer(payload))
        if len(matches) != 1:
            raise RuntimeError("Full grader context requires exactly one supported empty transcript block")
        match = matches[0]
        nonce = match.group(1)
        opening, closing = f"<transcript-{nonce}>", f"</transcript-{nonce}>"
        if any(len(re.findall(rf"(?m)^{re.escape(marker)}$", payload)) != 1 for marker in (opening, closing)):
            raise RuntimeError("Full grader context encountered an ambiguous transcript envelope")

        messages = state.get("messages", [])
        try:
            transcript = json.dumps(
                [{"type": message.type, "data": message.model_dump(include=_MODEL_MESSAGE_FIELDS)} for message in messages],
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise RuntimeError("Full grader context cannot serialize the complete source messages") from error
        # JSON Unicode escapes preserve source data without admitting payload delimiters.
        transcript = transcript.replace("<", "\\u003c")
        replacement = f"{opening}\n{transcript}\n{closing}"
        logger.info("Full grader context prepared (messages=%d, characters=%d)", len(messages), len(transcript))
        return payload[:match.start()] + replacement + payload[match.end():]
