from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
RULES_DIR = REPO_ROOT / "harness" / "rules" / "shared"


def _load_rules_context() -> str:
    rules = []
    for f in sorted(RULES_DIR.glob("*.md")):
        rules.append(f.read_text(encoding="utf-8").strip())
    return "\n\n---\n\n".join(rules)


def run_agent(model: str, prompt: str) -> str:
    system = _load_rules_context()

    if "claude" in model:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        full = []
        with client.messages.stream(
            model=model,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4096,
        ) as stream:
            for text in stream.text_stream:
                sys.stdout.write(text)
                sys.stdout.flush()
                full.append(text)
        print()
        return "".join(full)

    if "gpt" in model or "o4" in model or "o3" in model:
        import openai
        client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        full = []
        stream = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            max_tokens=4096,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                sys.stdout.write(delta)
                sys.stdout.flush()
                full.append(delta)
        print()
        return "".join(full)

    if "gemini" in model:
        import google.generativeai as genai
        genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
        gmodel = genai.GenerativeModel(model, system_instruction=system)
        full = []
        for chunk in gmodel.generate_content(prompt, stream=True):
            text = chunk.text
            if text:
                sys.stdout.write(text)
                sys.stdout.flush()
                full.append(text)
        print()
        return "".join(full)

    raise ValueError(f"Unknown model: {model}")
