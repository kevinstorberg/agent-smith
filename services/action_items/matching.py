from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from difflib import SequenceMatcher
from numbers import Real

from langchain_core.embeddings import Embeddings

from services.memory.content import MemoryTokenBudget

# Calibrated against the configured encoder by the synthetic retrieval gate.
COSINE_FLOOR = 0.25
LEXICAL_FLOOR = 0.45
POLICY_VERSION = 2


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def comparison_digest(record: dict) -> str:
    if record["kind"] != "task":
        return digest(record)
    data = {key: value for key, value in record["data"].items() if key != "revision"}
    return digest({**record, "data": data})


def chunks(text: str, budget: MemoryTokenBudget) -> list[str]:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Matching text must be nonblank")
    result, offset = [], 0
    while offset < len(text):
        remaining = text[offset:]
        if not remaining.strip():
            result[-1] += remaining
            budget.require(result[-1])
            offset = len(text)
            break
        piece = budget.fit(remaining)
        if not piece or not remaining.startswith(piece):
            raise ValueError("Embedding chunker made no lossless progress")
        budget.require(piece)
        result.append(piece)
        offset += len(piece)
    if "".join(result) != text:
        raise ValueError("Embedding chunks did not cover the original matching text")
    return result


def _validated_vectors(values, count: int, dimensions: int) -> list[list[float]]:
    if type(dimensions) is not int or dimensions <= 0:
        raise ValueError("Embedding dimensions must be positive")
    if not isinstance(values, list) or len(values) != count:
        raise ValueError("Encoder returned the wrong number of document vectors")
    result = []
    for vector in values:
        if not isinstance(vector, (list, tuple)) or len(vector) != dimensions:
            raise ValueError("Encoder returned an unexpected vector dimension")
        if any(
            isinstance(value, bool)
            or not isinstance(value, Real)
            or not math.isfinite(value)
            for value in vector
        ):
            raise ValueError("Encoder returned a nonfinite or nonnumeric vector")
        norm = math.sqrt(math.fsum(float(value) ** 2 for value in vector))
        if not norm:
            raise ValueError("Encoder returned a zero-length vector")
        result.append([float(value) / norm for value in vector])
    return result


def _content(value: dict) -> dict:
    data = value.get("data", value)
    return {
        key: data[key]
        for key in (
            "title",
            "description",
            "project",
            "tags",
            "status",
            "due_at",
            "action",
            "changes",
            "rationale",
            "evidence",
            "before_snapshot",
            "target_name",
        )
        if key in data
    }


def text(value: dict) -> str:
    return json.dumps(_content(value), sort_keys=True, ensure_ascii=False, default=str)


def _title(value: dict) -> str:
    data = value.get("data", value)
    return (
        data.get("changes", {}).get("title")
        or data.get("title")
        or data.get("target_name")
        or ""
    )


def _project(value: dict):
    data = value.get("data", value)
    return data.get("changes", {}).get("project", data.get("project"))


def mandatory(candidate: dict, record: dict) -> bool:
    data = record["data"]
    if record["kind"] in {"task", "candidate"}:
        return True
    if candidate.get("target_id") is not None and candidate["target_id"] == (
        data.get("id") if record["kind"] == "task" else data.get("target_id")
    ):
        return True
    if " ".join(_title(candidate).casefold().split()) == " ".join(
        _title(record).casefold().split()
    ):
        return True
    return (
        record["kind"] == "proposal"
        and data["status"] == "pending"
        and _project(candidate) == _project(record)
    )


def search(
    candidates: Sequence[dict],
    records: Sequence[dict],
    *,
    embeddings: Embeddings,
    budget: MemoryTokenBudget,
    dimensions: int,
) -> dict:
    keys = [record["key"] for record in records]
    if len(keys) != len(set(keys)) or any(
        not isinstance(key, str) or not key for key in keys
    ):
        raise ValueError("Matching corpus requires unique nonblank record keys")
    texts = [text(candidate) for candidate in candidates] + [
        text(record) for record in records
    ]
    parts = [chunks(value, budget) for value in texts]
    flat = [part for group in parts for part in group]
    vectors = (
        _validated_vectors(embeddings.embed_documents(flat), len(flat), dimensions)
        if flat
        else []
    )
    groups, offset = [], 0
    for group in parts:
        groups.append(vectors[offset : offset + len(group)])
        offset += len(group)
    result = {}
    for index, candidate in enumerate(candidates):
        hits = []
        for record_index, record in enumerate(records):
            if record["kind"] == "candidate" and record["key"] == f"candidate:{index}":
                continue
            other = record_index + len(candidates)
            cosine = max(
                math.fsum(a * b for a, b in zip(left, right, strict=True))
                for left in groups[index]
                for right in groups[other]
            )
            lexical = max(
                SequenceMatcher(
                    None,
                    texts[index].casefold(),
                    texts[other].casefold(),
                    autojunk=False,
                ).ratio(),
                SequenceMatcher(
                    None,
                    _title(candidate).casefold(),
                    _title(record).casefold(),
                    autojunk=False,
                ).ratio(),
            )
            required = mandatory(candidate, record)
            if required or cosine >= COSINE_FLOOR or lexical >= LEXICAL_FLOOR:
                hits.append(
                    {
                        "key": record["key"],
                        "cosine": cosine,
                        "lexical": lexical,
                        "mandatory": required,
                    }
                )
        result[str(index)] = sorted(
            hits, key=lambda hit: (-max(hit["cosine"], hit["lexical"]), hit["key"])
        )
    return {
        "hits": result,
        "scored_records": len(records),
        "encoded_chunks": len(flat),
        "policy": {
            "version": POLICY_VERSION,
            "cosine_floor": COSINE_FLOOR,
            "lexical_floor": LEXICAL_FLOOR,
        },
    }
