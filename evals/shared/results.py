from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def save_eval_result(
    results_dir: Path,
    eval_type: str,
    scenario_name: str,
    model: str,
    judge_model: str,
    threshold: float,
    output: str,
    results: list[dict],
) -> Path:
    ts = datetime.now(timezone.utc)
    ts_str = ts.strftime("%Y%m%d%H%M%S")
    type_dir = results_dir / eval_type
    type_dir.mkdir(parents=True, exist_ok=True)
    result_file = type_dir / f"{ts_str}_{scenario_name}_{model}_eval.json"
    result_file.write_text(
        json.dumps({
            "timestamp": ts.isoformat(),
            "eval_type": eval_type,
            "scenario": scenario_name,
            "model": model,
            "judge_model": judge_model,
            "threshold": threshold,
            "output": output,
            "results": results,
        }, indent=2),
        encoding="utf-8",
    )
    return result_file
