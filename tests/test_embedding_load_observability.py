import logging

import pytest

from services.memory import db


@pytest.mark.parametrize("offline", [False, True])
def test_cold_embedding_load_logs_before_constructor_and_preserves_local_only(
    monkeypatch, caplog, offline
):
    monkeypatch.setattr(db, "_embeddings", None)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1" if offline else "0")
    caplog.set_level(logging.INFO, logger="agent_smith.action")
    calls = []
    prefix = (
        "HUGGING FACE LOAD [NONBILLABLE]"
        if offline
        else "HUGGING FACE LOAD [BILLABLE?]"
    )

    def build(**kwargs):
        records = [r for r in caplog.records if hasattr(r, "operation_event")]
        assert len(records) == 1 and records[0].getMessage().startswith(prefix)
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(db, "HuggingFaceEmbeddings", build)
    first = db._get_embeddings()
    assert db._get_embeddings() is first
    assert len(calls) == 1
    assert calls[0]["model_kwargs"].get("local_files_only", False) is offline
    assert (
        len(
            [
                r
                for r in caplog.records
                if r.levelno == logging.INFO and hasattr(r, "operation_event")
            ]
        )
        == 1
    )


def test_embedding_load_failure_preserves_error_without_private_text(
    monkeypatch, caplog
):
    monkeypatch.setattr(db, "_embeddings", None)
    error = RuntimeError("PRIVATE_MODEL_PATH_AND_TOKEN")

    def fail(**kwargs):
        raise error

    monkeypatch.setattr(db, "HuggingFaceEmbeddings", fail)
    with pytest.raises(RuntimeError) as caught:
        db._get_embeddings()
    assert caught.value is error
    assert db._embeddings is None
    assert "PRIVATE_MODEL_PATH_AND_TOKEN" not in caplog.text
