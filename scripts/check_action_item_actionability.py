from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from dataclasses import dataclass
import json

from scripts.shared.automated_tests import live_evals_enabled


@dataclass(frozen=True)
class Case:
    name: str
    summary: str
    action: str | None = None
    title_term: str = ""


CASES = (
    Case("pending-call", "Vendor call still pending (earlier meeting ran over)."),
    Case(
        "waiting",
        "Waiting for Jordan's response; the team has no next step until it arrives.",
    ),
    Case("historical", "The onboarding guide was sent last week."),
    Case(
        "reschedule", "Morgan will reschedule the vendor call.", "create", "reschedul"
    ),
    Case("hold-review", "Hold the launch review on Friday.", "create", "review"),
    Case(
        "deliverable", "Morgan will send the launch checklist.", "create", "checklist"
    ),
    Case(
        "completion",
        "Morgan confirmed the release report was sent to the team.",
        "update",
    ),
    Case(
        "mixed",
        "Vendor call still pending (earlier meeting ran over). Morgan will send the launch checklist.",
        "create",
        "checklist",
    ),
)
TASK = {
    "id": 7,
    "revision": 2,
    "title": "Send the release report",
    "description": "Send the report to the team.",
    "project": None,
    "status": "open",
}


def verify_result(case: Case, result: dict) -> None:
    items = result["items"]
    if case.action is None:
        if items:
            raise AssertionError("Status-only context produced an Action Item")
        return
    if len(items) != 1 or items[0]["action"] != case.action:
        raise AssertionError(f"Expected one {case.action} proposal")
    item = items[0]
    if case.action == "update":
        if item.get("target_id") != TASK["id"] or item["changes"] != {
            "status": "completed"
        }:
            raise AssertionError(
                "Explicit completion must update the existing item minimally"
            )
    elif case.title_term not in item["changes"]["title"].casefold():
        raise AssertionError("The concrete next step was not preserved")
    if case.name == "mixed" and not any(
        "send the launch checklist" in entry["quote"] for entry in item["evidence"]
    ):
        raise AssertionError("The mixed case must cite the concrete commitment")


async def check(repeats: int) -> int:
    from services.graphs.model_config import load_model_config
    from services.meetings.action_item_analysis import analyze_action_items

    config = load_model_config("meeting_action_items", "curator")
    print(
        json.dumps(
            {
                "model": config.model_id,
                "temperature": config.temperature,
                "repeats": repeats,
            }
        ),
        flush=True,
    )
    semaphore = asyncio.Semaphore(2)

    async def run(case: Case, repeat: int) -> bool:
        async with semaphore:
            result = None
            try:
                async with asyncio.timeout(150):
                    result = await analyze_action_items(
                        {
                            "id": "00000000-0000-4000-8000-000000000001",
                            "title": "Synthetic planning",
                            "revision": 1,
                            "summary_text": case.summary,
                        },
                        [deepcopy(TASK)] if case.action == "update" else [],
                        [],
                        [],
                    )
                verify_result(case, result)
            except Exception as error:
                print(
                    json.dumps(
                        {
                            "case": case.name,
                            "repeat": repeat,
                            "passed": False,
                            "error_type": type(error).__name__,
                            "error": str(error),
                            "result": result,
                        }
                    ),
                    flush=True,
                )
                return False
            print(
                json.dumps(
                    {
                        "case": case.name,
                        "repeat": repeat,
                        "passed": True,
                        "result": result,
                    }
                ),
                flush=True,
            )
            return True

    async with asyncio.timeout(600):
        passed = await asyncio.gather(
            *(run(case, repeat) for repeat in range(1, repeats + 1) for case in CASES)
        )
    failures = passed.count(False)
    print(
        json.dumps({"passed": len(passed) - failures, "failed": failures}), flush=True
    )
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check synthetic Action Item extraction with the configured live model; no proposals are persisted."
    )
    parser.add_argument("--repeats", type=int, choices=range(1, 4), default=3)
    args = parser.parse_args()
    if not live_evals_enabled():
        parser.error(
            "Set AGENT_SMITH_EVAL_RUN=1 outside automated tests to permit live synthetic model calls"
        )
    return asyncio.run(check(args.repeats))


if __name__ == "__main__":
    raise SystemExit(main())
