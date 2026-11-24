"""Exercise local retrieval and optional model judgement with synthetic data only."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from services.action_items import matching
from services.config import MEMORY_EMBEDDING_DIMENSION, MEMORY_EMBEDDING_MODEL
from services.meetings import action_item_analysis, action_item_filter
from services.memory.db import get_embeddings, get_memory_token_budget


def candidate(title, quote, *, project=None, action="create", target=None, status=None):
    changes = {
        "title": title,
        **({"project": project} if project else {}),
        **({"status": status} if status else {}),
    }
    if action == "update":
        changes = {"status": status}
    return {
        "action": action,
        "changes": changes,
        "rationale": "Explicit synthetic source instruction",
        "evidence": [{"segment_id": "summary-0", "quote": quote}],
        **({"target_id": target, "expected_revision": 1} if target else {}),
    }


def task(title, *, project=None, status="open"):
    return {
        "key": "task:7",
        "kind": "task",
        "data": {
            "id": 7,
            "revision": 1,
            "title": title,
            "description": "",
            "project": project,
            "tags": [],
            "status": status,
            "due_at": None,
        },
    }


def proposal(
    title,
    *,
    status="pending",
    stale=False,
    project=None,
    action="create",
    target=None,
    desired=None,
):
    return {
        "key": "proposal:1",
        "kind": "proposal",
        "data": {
            "id": 1,
            "status": status,
            "action": action,
            "target_id": target,
            "project": project,
            "changes": {"title": title, **({"status": desired} if desired else {})},
            "rationale": "Original synthetic instruction",
            "evidence": [{"quote": "Synthetic prior instruction"}],
            "before_snapshot": None,
            "source_stale": stale,
            "target_stale": False,
            "source_timing": {
                "meeting_start": "2026-11-20T12:00:00+00:00",
                "provider_created_at": "2026-11-20T13:00:00+00:00",
            },
        },
    }


def snapshot(quote):
    return {
        "id": str(uuid4()),
        "revision": 1,
        "content_hash": "a" * 64,
        "title": "Synthetic filter verification",
        "summary_text": quote,
        "meeting_start": "2026-11-24T12:00:00+00:00",
        "provider_created_at": "2026-11-24T13:00:00+00:00",
        "source_url": "https://example.test/synthetic",
    }


def cases():
    quote = "Morgan will send the vendor readiness list."
    base = candidate("Email supplier checklist", quote)
    result = [
        (
            "saved_paraphrase",
            quote,
            [base],
            [task("Send the vendor readiness list")],
            0,
            0,
        ),
        (
            "rejected_paraphrase",
            quote,
            [base],
            [proposal("Send the vendor readiness list", status="rejected")],
            0,
            0,
        ),
        (
            "pending_paraphrase",
            quote,
            [base],
            [proposal("Send the vendor readiness list")],
            0,
            0,
        ),
        (
            "stale_pending",
            quote,
            [base],
            [proposal("Send the vendor readiness list", stale=True)],
            1,
            1,
        ),
    ]
    quote = "Riley will send the vendor readiness list."
    result.append(
        (
            "distinct_owner",
            quote,
            [candidate("Riley: send vendor readiness list", quote)],
            [task("Morgan: send vendor readiness list")],
            1,
            0,
        )
    )
    quote = "Send the launch checklist for Project Atlas."
    result.append(
        (
            "distinct_project",
            quote,
            [candidate("Send launch checklist", quote, project="Atlas")],
            [task("Send launch checklist", project="Orion")],
            1,
            0,
        )
    )
    quote = "Morgan confirmed the integration review is complete."
    completion = candidate(
        "Complete integration review",
        quote,
        action="update",
        target=7,
        status="completed",
    )
    result.append(
        (
            "supported_completion_after_approved_history",
            quote,
            [completion],
            [
                task("Integration review"),
                proposal(
                    "Integration review",
                    status="approved",
                    action="update",
                    target=7,
                    desired="completed",
                ),
            ],
            1,
            0,
        )
    )
    quote = "The vendor call is still pending because the earlier meeting ran over."
    result.append(
        (
            "pending_status_is_not_action",
            quote,
            [candidate("Hold the still-pending vendor call", quote)],
            [],
            0,
            0,
        )
    )
    quote = "Morgan has already completed the handoff."
    result.append(
        (
            "completed_create_is_not_action",
            quote,
            [candidate("Complete handoff", quote, status="completed")],
            [],
            0,
            0,
        )
    )
    quote = "Reschedule the vendor call for Friday."
    result.append(
        (
            "explicit_rescheduling",
            quote,
            [candidate("Reschedule vendor call", quote)],
            [],
            1,
            0,
        )
    )
    quote = "Morgan will send the vendor readiness list."
    result.append(
        (
            "same_batch_paraphrases",
            quote,
            [
                candidate("Email supplier checklist", quote),
                candidate("Send vendor readiness list", quote),
            ],
            [],
            1,
            0,
        )
    )
    return result


def retrieval_probe(embeddings, budget):
    pairs = [
        ("Email the supplier checklist", "Send the vendor readiness list"),
        (
            "Prepare a technical implementation plan",
            "Write the engineering delivery roadmap",
        ),
        (
            "Ask the customer to approve the migration",
            "Get client sign-off for the data move",
        ),
        ("Schedule the launch review", "Book the release readiness meeting"),
        ("Confirm the recurring sync time", "Verify when the regular check-in happens"),
    ]
    output = []
    for left, right in pairs:
        c = candidate(left, left)
        record = task(right)
        searched = matching.search(
            [c],
            [record],
            embeddings=embeddings,
            budget=budget,
            dimensions=MEMORY_EMBEDDING_DIMENSION,
        )
        assert searched["hits"]["0"], f"Equivalent paraphrase was not retrieved: {left}"
        output.append({"case": left, "hits": searched["hits"]["0"]})
    tail = "Unique final-tail instruction: send the vendor readiness list."
    record = task("Planning reference")
    record["data"]["description"] = (
        "An unrelated warehouse inventory observation. " * 250 + tail + "   "
    )
    parts = matching.chunks(matching.text(record), budget)
    assert "".join(parts) == matching.text(record) and len(parts) > 1
    searched = matching.search(
        [candidate("Email supplier checklist", tail)],
        [record],
        embeddings=embeddings,
        budget=budget,
        dimensions=MEMORY_EMBEDDING_DIMENSION,
    )
    assert searched["hits"]["0"], "Decisive long-tail evidence was not retrieved"
    output.append(
        {"case": "long_tail", "chunks": len(parts), "hits": searched["hits"]["0"]}
    )
    return output


def benchmark(embeddings, budget):
    output = []
    candidates = [
        candidate(f"Send vendor readiness list {i}", "Send the vendor readiness list.")
        for i in range(20)
    ]
    for count in [118, 205, 1180]:
        records = []
        for index in range(count):
            record = task(f"Review synthetic delivery {index}")
            record["key"] = f"task:{index}"
            record["data"]["description"] = (
                "Synthetic unrelated release planning context. " * 12
            )
            records.append(record)
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=2) as pool:
            future = pool.submit(
                matching.search,
                candidates,
                records,
                embeddings=embeddings,
                budget=budget,
                dimensions=MEMORY_EMBEDDING_DIMENSION,
            )
            contention = pool.submit(
                embeddings.embed_documents, ["Synthetic concurrent memory encoding."]
            )
            assert len(contention.result(timeout=150)) == 1
            result = future.result(timeout=150)
        windows = action_item_filter.windows(
            snapshot("Send the vendor readiness list."),
            candidates,
            records,
            result["hits"],
        )
        output.append(
            {
                "records": count,
                "candidates": 20,
                "elapsed": time.monotonic() - started,
                "scored_records": result["scored_records"],
                "encoded_chunks": result["encoded_chunks"],
                "hits": sum(len(items) for items in result["hits"].values()),
                "judge_windows": len(windows),
                "max_window_chars": max(
                    len(json.dumps(window, default=str)) for window in windows
                ),
            }
        )
    return output


async def model_checks(embeddings, budget, repetitions, concurrency):
    semaphore = asyncio.Semaphore(concurrency)

    async def run(case, repetition):
        name, quote, candidates, rows, expected_kept, expected_superseded = case
        async with semaphore:
            started = time.monotonic()
            records = [
                *rows,
                *[
                    {"key": f"candidate:{index}", "kind": "candidate", "data": item}
                    for index, item in enumerate(candidates)
                ],
            ]
            searched = await asyncio.to_thread(
                matching.search,
                candidates,
                records,
                embeddings=embeddings,
                budget=budget,
                dimensions=MEMORY_EMBEDDING_DIMENSION,
            )
            source = snapshot(quote)
            results = []
            for data in action_item_filter.windows(
                source, candidates, records, searched["hits"]
            ):
                results.append(await action_item_filter.analyze_window(source, data))
            reduced = action_item_filter.reduce_decisions(candidates, records, results)
            assert len(reduced["keep"]) == expected_kept, (name, reduced, results)
            assert len(reduced["supersede"]) == expected_superseded, (
                name,
                reduced,
                results,
            )
            return {
                "case": name,
                "repetition": repetition,
                "elapsed": time.monotonic() - started,
                "kept": len(reduced["keep"]),
                "superseded": len(reduced["supersede"]),
                "windows": len(results),
            }

    outcomes = await asyncio.gather(
        *(
            run(case, repetition)
            for case in cases()
            for repetition in range(1, repetitions + 1)
        )
    )
    quote = "Morgan will prepare the launch checklist. The supplier call is still pending. Morgan has already sent the old report. Morgan confirmed the integration review is complete."
    for repetition in range(1, repetitions + 1):
        started = time.monotonic()
        inventory = [task("Integration review")["data"]]
        generated = await action_item_analysis.analyze_action_items(
            snapshot(quote), inventory, [], []
        )
        assert len(generated["items"]) == 2, generated
        assert {item["action"] for item in generated["items"]} == {
            "create",
            "update",
        }, generated
        rows = [task("Integration review")]
        candidates = generated["items"]
        rows.extend(
            {"key": f"candidate:{index}", "kind": "candidate", "data": item}
            for index, item in enumerate(candidates)
        )
        searched = await asyncio.to_thread(
            matching.search,
            candidates,
            rows,
            embeddings=embeddings,
            budget=budget,
            dimensions=MEMORY_EMBEDDING_DIMENSION,
        )
        source = snapshot(quote)
        results = [
            await action_item_filter.analyze_window(source, data)
            for data in action_item_filter.windows(
                source, candidates, rows, searched["hits"]
            )
        ]
        reduced = action_item_filter.reduce_decisions(candidates, rows, results)
        assert len(reduced["keep"]) == 2, (generated, reduced)
        outcomes.append(
            {
                "case": "two_node_actionability",
                "repetition": repetition,
                "elapsed": time.monotonic() - started,
                "generated": 2,
                "kept": 2,
            }
        )
    return outcomes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", action="store_true")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repetitions <= 0 or args.concurrency <= 0:
        parser.error("repetitions and concurrency must be positive")
    if args.model and (
        os.environ.get("AGENT_SMITH_EVAL_RUN") != "1"
        or os.environ.get("AGENT_SMITH_AUTOMATED_TESTS") == "1"
    ):
        parser.error(
            "Real synthetic model checks require explicit AGENT_SMITH_EVAL_RUN=1 outside automated tests"
        )
    embeddings, budget = get_embeddings(), get_memory_token_budget()
    report = {
        "model": MEMORY_EMBEDDING_MODEL,
        "dimensions": MEMORY_EMBEDDING_DIMENSION,
        "retrieval": retrieval_probe(embeddings, budget),
        "benchmark": benchmark(embeddings, budget),
    }
    args.output.write_text(json.dumps(report, indent=2))
    if args.model:
        report["model_cases"] = asyncio.run(
            model_checks(embeddings, budget, args.repetitions, args.concurrency)
        )
        args.output.write_text(json.dumps(report, indent=2))
    print(
        json.dumps(
            {
                "output": str(args.output),
                "cases": len(report.get("model_cases", [])),
                "benchmark": report["benchmark"],
            }
        )
    )


if __name__ == "__main__":
    main()
