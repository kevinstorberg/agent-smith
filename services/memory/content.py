from __future__ import annotations

import logging
import re

MAX_MEMORY_WORDS = 250
_WORDS = re.compile(r"\S+")
_LOGGER = logging.getLogger("agent_smith.memory.content")


def memory_word_count(content: str) -> int:
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Memory content must be a nonblank string")
    return sum(1 for _ in _WORDS.finditer(content))


def limit_memory_content(content: str, *, max_words: int = MAX_MEMORY_WORDS) -> str:
    if type(max_words) is not int or not 1 <= max_words <= MAX_MEMORY_WORDS:
        raise ValueError(f"Memory word budget must be an integer from 1 to {MAX_MEMORY_WORDS}")
    memory_word_count(content)
    end = 0
    for index, word in enumerate(_WORDS.finditer(content), start=1):
        if index > max_words:
            return content[:end]
        end = word.end()
    return content


def normalize_memory_content(content: str, *, max_words: int = MAX_MEMORY_WORDS) -> str:
    limited = limit_memory_content(content, max_words=max_words)
    if limited != content:
        _LOGGER.info("Memory content truncated original_words=%s final_words=%s",
                     memory_word_count(content), memory_word_count(limited))
    return limited
