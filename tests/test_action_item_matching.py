from __future__ import annotations

import math

import pytest
from langchain_core.embeddings import Embeddings

from services.action_items import matching
from services.memory.content import MemoryTokenBudget


class Encoder(Embeddings):
    def __init__(self):
        self.seen = []

    def embed_documents(self, texts):
        self.seen.extend(texts)
        return [[1.0, 0.5] for text in texts]

    def embed_query(self, text):
        pytest.fail("Matching must use budget-validated documents on both sides")


BUDGET = MemoryTokenBudget(64, 2, lambda text: len(text.split()) + 2)


def test_action_item_matching_covers_over_200_records_and_over_20_candidates():
    encoder = Encoder()
    candidates = [{"changes": {"title": f"Task {i}"}} for i in range(21)]
    records = [
        {"key": f"task:{i}", "kind": "task", "data": {"id": i, "title": f"Record {i}"}}
        for i in range(205)
    ]
    result = matching.search(
        candidates, records, embeddings=encoder, budget=BUDGET, dimensions=2
    )
    assert result["scored_records"] == 205
    assert len(result["hits"]) == 21
    assert all(len(hits) == 205 for hits in result["hits"].values())
    assert "task:204" in {hit["key"] for hit in result["hits"]["20"]}


def test_action_item_matching_lossless_chunks_preserve_tail_and_whitespace():
    value = "  " + "long original clause " * 200 + "decisive supplier checklist tail   "
    parts = matching.chunks(value, BUDGET)
    assert len(parts) > 1 and "".join(parts) == value
    assert parts[-1].endswith("decisive supplier checklist tail   ")
    for piece in parts:
        BUDGET.require(piece)


@pytest.mark.parametrize(
    "vectors",
    [
        [],
        [[0.0, 0.0]],
        [[math.nan, 1]],
        [[math.inf, 1]],
        [[True, 1]],
        [[1]],
        [["x", 1]],
    ],
)
def test_action_item_matching_rejects_invalid_encoder_output(vectors):
    with pytest.raises(ValueError):
        matching._validated_vectors(vectors, 1, 2)


def test_action_item_matching_mandatory_lanes_do_not_infer_assignees():
    candidate = {"changes": {"title": "Unrelated", "project": "Work"}}
    record = {
        "key": "proposal:1",
        "kind": "proposal",
        "data": {
            "id": 1,
            "status": "pending",
            "project": "Work",
            "target_name": "Different",
        },
    }
    assert matching.mandatory(candidate, record)
    record["data"]["status"] = "rejected"
    assert not matching.mandatory(candidate, record)


@pytest.mark.parametrize("status", ["open", "completed"])
def test_saved_tasks_are_compared_even_below_both_retrieval_thresholds(status):
    class UnrelatedEncoder(Encoder):
        def embed_documents(self, texts):
            return [[1.0, 0.0], [-1.0, 0.0]]

    candidate = {"changes": {"title": "a" * 200, "project": "New project"}}
    record = {
        "key": "task:7",
        "kind": "task",
        "data": {"id": 7, "title": "z" * 200, "status": status},
    }
    result = matching.search(
        [candidate],
        [record],
        embeddings=UnrelatedEncoder(),
        budget=BUDGET,
        dimensions=2,
    )
    hit = result["hits"]["0"][0]
    assert hit["key"] == "task:7" and hit["mandatory"]
    assert hit["cosine"] < matching.COSINE_FLOOR
    assert hit["lexical"] < matching.LEXICAL_FLOOR
