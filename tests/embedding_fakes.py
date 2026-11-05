from __future__ import annotations

from types import SimpleNamespace


class FakeEmbeddingClient:
    def __init__(self, count_payload_tokens=None):
        self.max_seq_length = 256
        self.default_prompt_name = None
        self.prompts = {}
        self.tokenizer = SimpleNamespace(num_special_tokens_to_add=lambda pair=False: 2)
        self.count_payload_tokens = count_payload_tokens or (
            lambda text: len(text.split())
        )
        self.prepared = []

    def preprocess(self, texts, *, processing_kwargs):
        self.prepared.append((texts, processing_kwargs))
        return {
            "input_ids": [
                [0, *range(self.count_payload_tokens(text)), 1] for text in texts
            ]
        }
