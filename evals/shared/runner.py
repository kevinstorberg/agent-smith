from __future__ import annotations

import subprocess


def run_agent(model: str, prompt: str, timeout: int = 300) -> str:
    if model.startswith("claude"):
        cmd = ["claude", "-p", prompt, "--model", model]
    elif model.startswith("codex"):
        cmd = ["codex", "-q", prompt]
    elif model.startswith("gemini"):
        cmd = ["gemini", prompt]
    else:
        raise ValueError(f"Unknown model prefix: {model}")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    assert result.returncode == 0, f"Agent failed: {result.stderr}"
    return result.stdout
