from __future__ import annotations

import re


def strip_code_blocks(text: str) -> str:
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"```.*", "", text, flags=re.DOTALL)
    return text


def extract_numbered_steps(rule_content: str) -> list[str]:
    stripped = strip_code_blocks(rule_content)
    steps: list[str] = []
    for match in re.finditer(r"^\s*\d+\.\s+(.+)", stripped, re.MULTILINE):
        steps.append(match.group(1).rstrip("."))
    return steps


def rule_to_eval_steps(rule_content: str) -> list[str]:
    return [
        f"Does the output demonstrate: {step}?"
        for step in extract_numbered_steps(rule_content)
    ]


def rules_to_prompt_context(rules: list[tuple[str, str]]) -> str:
    assert rules, "rules must contain at least one rule"
    parts = ["Use these pragmatic engineering rules as binding review principles:"]
    for name, body in rules:
        parts.append(f"## {name}\n{body.strip()}")
    return "\n\n".join(parts)


def rules_to_rubric(rules: list[tuple[str, str]]) -> str:
    assert rules, "rules must contain at least one rule"
    lines: list[str] = []
    for name, body in rules:
        steps = extract_numbered_steps(body)
        if not steps:
            lines.append(f"- {name}: The opinion explicitly applies this rule.")
            continue
        for step in steps:
            lines.append(f"- {name}: {step}")
    return "\n".join(lines)
