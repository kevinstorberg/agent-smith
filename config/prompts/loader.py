"""Prompt template loader for template users.

NOTE: This module is intentionally unused by the template itself.
When you build your application and need to load LLM prompts from files,
use this utility to load them from config/prompts/*.txt files.

Example usage:
    from config.prompts.loader import load_prompt

    system_prompt = load_prompt("system_instructions")
    user_prompt = load_prompt("task_template")
"""

from lib.cairn.paths import get_module_dir

_PROMPTS_DIR = get_module_dir(__file__)


def load_prompt(name: str) -> str:
    """Load a prompt template from a .txt file.

    Template utility: Add your prompt .txt files to config/prompts/ and load them
    with this function. Keeps prompts separate from code for easier editing.

    Args:
        name: Filename without .txt extension (e.g., "system_instructions")

    Returns:
        The prompt text as a string with whitespace stripped

    Raises:
        FileNotFoundError: If the prompt file doesn't exist
    """
    path = _PROMPTS_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text().strip()
