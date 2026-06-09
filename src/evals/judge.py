import re


def build_criteria(prompt: str = "", rule: str = "") -> str:
    if not prompt and not rule:
        raise ValueError("At least one of prompt or rule must be provided")
    parts = []
    if prompt:
        parts.append(f"Evaluation prompt: {prompt}")
    if rule:
        parts.append(f"Rule: {rule}")
    return "\n".join(parts)


def extract_steps(text: str) -> list[str]:
    pattern = re.compile(r"^\d+\.\s+(.+)$", re.MULTILINE)
    return pattern.findall(text)
