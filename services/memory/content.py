from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

MAX_MEMORY_TOKENS = 256

_LOGGER = logging.getLogger("agent_smith.memory.content")


def require_memory_text(content: str) -> str:
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Memory content must be a nonblank string")
    return content


class MemoryTokenLimitError(ValueError):
    def __init__(self, total_tokens: int, max_tokens: int, special_tokens: int):
        self.total_tokens = total_tokens
        self.max_tokens = max_tokens
        self.special_tokens = special_tokens
        super().__init__(
            f"Memory content allowance is {max_tokens - special_tokens} embedding tokens; "
            f"received {total_tokens} total tokens including {special_tokens} special tokens "
            f"(maximum {max_tokens}). Rewrite the memory concisely before saving."
        )


@dataclass(frozen=True)
class MemoryTokenBudget:
    max_tokens: int
    special_tokens: int
    count_tokens: Callable[[str], int]

    def __post_init__(self):
        if (
            type(self.max_tokens) is not int
            or not 1 <= self.max_tokens <= MAX_MEMORY_TOKENS
            or type(self.special_tokens) is not int
            or not 0 <= self.special_tokens < self.max_tokens
            or not callable(self.count_tokens)
        ):
            raise ValueError(
                "Memory token budget or special-token overhead is unsupported"
            )

    def total_tokens(self, content: str) -> int:
        require_memory_text(content)
        total = self.count_tokens(content)
        if type(total) is not int or total <= self.special_tokens:
            raise ValueError(
                "Memory encoder did not return a valid nonblank token count"
            )
        return total

    def require(self, content: str) -> str:
        total = self.total_tokens(content)
        if total > self.max_tokens:
            raise MemoryTokenLimitError(total, self.max_tokens, self.special_tokens)
        return content

    def fit(self, content: str) -> str:
        require_memory_text(content)
        first_content_end = next(
            index + 1
            for index, character in enumerate(content)
            if not character.isspace()
        )
        end = len(content)
        for _ in range(64):
            prefix = content[:end]
            total = self.total_tokens(prefix)
            if total <= self.max_tokens:
                return prefix
            if end == first_content_end:
                break
            end = max(first_content_end, min(end - 1, end * self.max_tokens // total))
        prefix = content[:first_content_end]
        self.require(prefix)
        return prefix

    def normalize(self, content: str) -> str:
        limited = self.fit(content)
        if limited != content:
            _LOGGER.info(
                "Memory content truncated original_tokens=%s final_tokens=%s token_limit=%s",
                self.total_tokens(content),
                self.total_tokens(limited),
                self.max_tokens,
            )
        return limited
