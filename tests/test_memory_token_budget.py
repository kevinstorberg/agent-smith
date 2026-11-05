from __future__ import annotations

import logging
from uuid import uuid4

import pytest
from langchain_core.embeddings import Embeddings

from services.memory import db
from services.memory.content import MAX_MEMORY_TOKENS, MemoryTokenBudget
from services.memory.embedding_budget import EmbeddingTokenCounter
from tests.test_memory_content import content_store as content_store
from tests.embedding_fakes import FakeEmbeddingClient


def character_budget(max_tokens=256):
    return MemoryTokenBudget(max_tokens, 2, lambda text: len(text) + 2)


@pytest.mark.parametrize("size", [253, 254])
def test_total_token_boundary_preserves_the_exact_original_string(size):
    content = "a" * size
    budget = character_budget()
    assert MAX_MEMORY_TOKENS == 256
    assert budget.require(content) == content
    assert budget.fit(content) == content


def test_oversize_direct_write_returns_only_a_verified_original_unicode_prefix():
    content = " café東京🙂—" * 80
    budget = character_budget()
    limited = budget.fit(content)
    assert content.startswith(limited) and limited.strip()
    assert budget.total_tokens(limited) <= 256
    assert budget.fit(limited) == limited


def test_fitting_prefix_never_assumes_token_counts_are_monotonic():
    def count(content):
        return 300 if len(content) == 3 else len(content) * 10 + 2

    budget = MemoryTokenBudget(32, 2, count)
    limited = budget.fit("abcdefghijk")
    assert "abcdefghijk".startswith(limited)
    assert budget.total_tokens(limited) <= 32


def test_strict_rewrite_feedback_leads_with_content_allowance_and_has_no_private_text():
    content = "PRIVATE_SENTINEL" * 30
    with pytest.raises(ValueError) as raised:
        character_budget().require(content)
    message = str(raised.value)
    assert "254" in message and "256" in message
    assert "Rewrite" in message and "PRIVATE" not in message


@pytest.mark.parametrize("value", [None, 1, {}, "", " \t\n"])
def test_invalid_memory_content_fails_before_the_counter(value):
    def forbidden(_content):
        raise AssertionError("Invalid content reached the encoder")

    with pytest.raises(ValueError):
        MemoryTokenBudget(256, 2, forbidden).require(value)


@pytest.mark.parametrize(
    "maximum,specials", [(257, 2), (0, 2), (True, 2), (256, -1), (2, 2)]
)
def test_budget_configuration_cannot_exceed_the_native_or_policy_contract(
    maximum, specials
):
    with pytest.raises(ValueError):
        MemoryTokenBudget(maximum, specials, len)


def test_normalization_notice_reports_only_token_counts(caplog):
    budget = character_budget()
    with caplog.at_level(logging.INFO, logger="agent_smith.memory.content"):
        limited = budget.normalize("PRIVATE_SENTINEL" * 30)
    assert budget.total_tokens(limited) <= 256
    assert "original_tokens=" in caplog.text and "final_tokens=" in caplog.text
    assert "PRIVATE" not in caplog.text


class RecordingModel(Embeddings):
    def __init__(self):
        self._client = FakeEmbeddingClient(len)
        self.encode_kwargs = {}
        self.multi_process = False
        self.documents = []
        self.queries = []

    def embed_documents(self, texts):
        self.documents.extend(texts)
        return [[1.0] for _ in texts]

    def embed_query(self, text):
        self.queries.append(text)
        return [1.0]


def test_native_adapter_counts_actual_newline_preparation_without_clipping_or_padding():
    model = RecordingModel()
    counter = EmbeddingTokenCounter(model)
    assert counter.max_tokens == 256 and counter.special_tokens == 2
    assert counter.count("one\ntwo") == 9
    assert model._client.prepared == [
        (["one two"], {"text": {"truncation": False, "padding": False}})
    ]
    assert model.documents == []


def test_actual_smaller_native_capacity_wins_without_increasing_the_model_window():
    model = RecordingModel()
    model._client.max_seq_length = 128
    counter = EmbeddingTokenCounter(model)
    assert counter.max_tokens == 128
    assert model._client.max_seq_length == 128


def test_unsupported_document_prompt_fails_before_any_embedding():
    model = RecordingModel()
    model._client.default_prompt_name = "document"
    model._client.prompts = {"document": "A hidden prefix: "}
    with pytest.raises(ValueError, match="prompt"):
        EmbeddingTokenCounter(model).count("A memory")
    assert model.documents == []


@pytest.mark.parametrize(
    "kwargs",
    [None, {"processing_kwargs": {"text": {"max_length": 4}}}, {"max_length": 4}],
)
def test_unknown_encode_preparation_is_rejected_before_any_embedding(kwargs):
    model = RecordingModel()
    model.encode_kwargs = kwargs
    with pytest.raises(ValueError, match="configuration|preparation"):
        EmbeddingTokenCounter(model).count("A memory")
    assert model.documents == []


def test_native_count_errors_do_not_echo_private_memory_text():
    model = RecordingModel()

    def rejected(*_args, **_kwargs):
        raise ValueError("PRIVATE_MEMORY_TEXT")

    model._client.preprocess = rejected
    with pytest.raises(ValueError) as raised:
        EmbeddingTokenCounter(model).count("PRIVATE_MEMORY_TEXT")
    assert "PRIVATE" not in str(raised.value)


def test_final_document_guard_rejects_the_whole_batch_before_any_embed_but_keeps_queries():
    model = RecordingModel()
    serialized = db._SerializedEmbeddings(model)
    with pytest.raises(ValueError):
        serialized.embed_documents(["Valid", "x" * 255])
    assert model.documents == []
    query = "x" * 400
    assert serialized.embed_query(query) == [1.0]
    assert model.queries == [query]


def test_fitting_document_guard_preserves_the_exact_source_sent_to_embedding():
    model = RecordingModel()
    serialized = db._SerializedEmbeddings(model)
    source = "Complete source.\nPreserve this line."
    assert serialized.embed_documents([source]) == [[1.0]]
    assert model.documents == [source]


@pytest.mark.parametrize("operation", ["add", "update", "publish"])
def test_every_shared_write_stores_and_embeds_the_same_measured_fitting_prefix(
    content_store, monkeypatch, operation
):
    backend, embeddings = content_store
    monkeypatch.setattr(
        embeddings, "memory_token_budget", character_budget, raising=False
    )
    content = " \n" + "naïve東京🙂 " * 80
    id = str(uuid4())
    if operation == "update":
        id = db.add("Original")
        created = backend.get_row(id)["metadata"]["created_at"]
        embeddings.documents.clear()
        db.update(id, content=content)
        assert backend.get_row(id)["metadata"]["created_at"] == created
    elif operation == "publish":
        db.publish(id, content, created_at="2026-11-05T12:00:00Z")
    else:
        id = db.add(content)
    stored = backend.get_row(id)["text"]
    assert content.startswith(stored) and stored.strip()
    assert len(stored) + 2 <= 256
    assert embeddings.documents == [stored]


def test_cached_native_counter_verifies_wordpieces_and_specials_without_inference(
    monkeypatch,
):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    monkeypatch.setattr(db, "_embeddings", None)
    monkeypatch.setattr(db, "MODEL_NAME", "all-MiniLM-L6-v2")
    monkeypatch.setattr(db, "MEMORY_EMBEDDING_DEVICE", "cpu")
    embeddings = db._get_embeddings()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Token counting must not run inference")

    monkeypatch.setattr(embeddings._model._client, "encode", forbidden)
    budget = embeddings.memory_token_budget()
    assert budget.special_tokens == 2 and budget.max_tokens == 256
    assert budget.total_tokens(" ".join(["memory"] * 254)) == 256
    compound_words = " ".join(f"identifier{index}" for index in range(250))
    assert budget.total_tokens(compound_words) > 256
    assert budget.total_tokens(" ".join(["café東京"] * 100)) > 256
    limited = budget.fit(compound_words)
    assert compound_words.startswith(limited) and budget.total_tokens(limited) <= 256
