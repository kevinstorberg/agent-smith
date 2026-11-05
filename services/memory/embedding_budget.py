from __future__ import annotations

from importlib.metadata import version

from services.memory.content import MAX_MEMORY_TOKENS


class EmbeddingTokenCounter:
    def __init__(self, model):
        self._model = model

    def _configuration(self):
        client = getattr(self._model, "_client", None)
        if client is None or not callable(getattr(client, "preprocess", None)):
            raise ValueError(
                "Memory embedding client cannot count its native document tokens"
            )
        kwargs = getattr(self._model, "encode_kwargs", {})
        allowed = {
            "prompt",
            "prompt_name",
            "task",
            "normalize_embeddings",
            "precision",
            "batch_size",
            "convert_to_numpy",
            "convert_to_tensor",
            "truncate_dim",
        }
        if not isinstance(kwargs, dict) or set(kwargs) - allowed:
            raise ValueError(
                "Memory embedding encode preparation configuration is unsupported"
            )
        prompts = getattr(client, "prompts", {})
        prompt_name = kwargs.get("prompt_name") or getattr(
            client, "default_prompt_name", None
        )
        if not isinstance(prompts, dict) or (
            prompt_name is not None and not isinstance(prompt_name, str)
        ):
            raise ValueError("Memory embedding prompt configuration is unsupported")
        prompt = kwargs.get("prompt") or prompts.get(prompt_name, "")
        if prompt or kwargs.get("task") or getattr(self._model, "multi_process", False):
            raise ValueError(
                "Memory embedding document prompt or processing mode is unsupported"
            )
        capacity = getattr(client, "max_seq_length", None)
        tokenizer = getattr(client, "tokenizer", None)
        specials_method = getattr(tokenizer, "num_special_tokens_to_add", None)
        if type(capacity) is not int or capacity < 1 or not callable(specials_method):
            raise ValueError(
                "Memory embedding client has no supported native token capacity"
            )
        specials = specials_method(pair=False)
        maximum = min(MAX_MEMORY_TOKENS, capacity)
        if type(specials) is not int or not 0 <= specials < maximum:
            raise ValueError(
                "Memory embedding special tokens leave no room for content"
            )
        return client, maximum, specials

    @property
    def max_tokens(self):
        return self._configuration()[1]

    @property
    def special_tokens(self):
        return self._configuration()[2]

    def count(self, content: str) -> int:
        client, _, _ = self._configuration()
        try:
            encoded = client.preprocess(
                [content.replace("\n", " ")],
                processing_kwargs={"text": {"truncation": False, "padding": False}},
            )
        except (ValueError, TypeError, RuntimeError, UnicodeError):
            raise ValueError(
                "Memory encoder could not count native document tokens"
            ) from None
        try:
            ids = encoded["input_ids"]
            if len(ids) != 1:
                raise ValueError()
            return len(ids[0])
        except (KeyError, IndexError, TypeError, ValueError):
            raise ValueError(
                "Memory encoder returned an unsupported token-count result"
            ) from None

    def diagnostics(self):
        return {
            "token_limit": self.max_tokens,
            "special_tokens": self.special_tokens,
            "versions": {
                package: version(package)
                for package in (
                    "sentence-transformers",
                    "langchain-huggingface",
                    "transformers",
                    "tokenizers",
                )
            },
        }
