from __future__ import annotations

import os
import sys

from scripts.shared.fs import compose_strings

EXCLUDE_RULES = {"memory"}


def _load_rules_context() -> str:
    from services.api.models.rule import collect_rules_from_db
    items = [
        (name, body) for name, body in collect_rules_from_db("claude")
        if name not in EXCLUDE_RULES
    ]
    return compose_strings(items)


def _collect_stream(chunks) -> str:
    full = []
    for text in chunks:
        if text:
            sys.stdout.write(text)
            sys.stdout.flush()
            full.append(text)
    print()
    return "".join(full)


def run_agent(model: str, prompt: str, extra_context: str | None = None) -> str:
    system = _load_rules_context()
    if extra_context:
        system = f"{system}\n\n{extra_context}"

    if "claude" in model:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        with client.messages.stream(
            model=model,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=16384,
        ) as stream:
            return _collect_stream(stream.text_stream)

    if "gpt" in model or "o4" in model or "o3" in model:
        import openai
        client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        stream = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            max_tokens=16384,
            stream=True,
        )
        return _collect_stream(
            chunk.choices[0].delta.content for chunk in stream
        )

    if "gemini" in model:
        import google.generativeai as genai
        genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
        gmodel = genai.GenerativeModel(model, system_instruction=system)
        return _collect_stream(
            chunk.text for chunk in gmodel.generate_content(prompt, stream=True)
        )

    raise ValueError(f"Unknown model: {model}")
