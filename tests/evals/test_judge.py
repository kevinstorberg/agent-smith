import pytest

from src.evals.judge import build_criteria, extract_steps
from src.evals.results import EvalResult
from src.evals.runner import SUPPORTED_PROVIDERS, EvalRunner


class TestBuildCriteria:
    def test_combines_prompt_and_rule(self):
        result = build_criteria(prompt="Is the response helpful?", rule="Must address the question directly")
        assert "Is the response helpful?" in result
        assert "Must address the question directly" in result

    def test_prompt_only(self):
        result = build_criteria(prompt="Rate clarity")
        assert "Rate clarity" in result

    def test_rule_only(self):
        result = build_criteria(rule="No profanity")
        assert "No profanity" in result


class TestExtractSteps:
    def test_parses_numbered_list(self):
        text = "1. First step\n2. Second step\n3. Third step"
        steps = extract_steps(text)
        assert steps == ["First step", "Second step", "Third step"]

    def test_empty_input(self):
        steps = extract_steps("")
        assert steps == []

    def test_non_numbered_text_returns_empty(self):
        steps = extract_steps("This is just a paragraph with no numbered items.")
        assert steps == []


class TestEvalRunner:
    def test_supported_providers_listed(self):
        assert "anthropic" in SUPPORTED_PROVIDERS
        assert "openai" in SUPPORTED_PROVIDERS

    def test_runner_instantiates(self):
        runner = EvalRunner(provider="anthropic")
        assert runner.provider == "anthropic"

    def test_runner_rejects_unknown_provider(self):
        with pytest.raises(ValueError, match="Unsupported provider"):
            EvalRunner(provider="unknown_provider")


class TestEvalResult:
    def test_result_stores_fields(self):
        result = EvalResult(score=0.85, reasoning="Good answer", criteria="helpfulness")
        assert result.score == 0.85
        assert result.reasoning == "Good answer"
        assert result.criteria == "helpfulness"

    def test_result_passed_property(self):
        passing = EvalResult(score=0.8, reasoning="ok", criteria="test", threshold=0.7)
        failing = EvalResult(score=0.5, reasoning="bad", criteria="test", threshold=0.7)
        assert passing.passed is True
        assert failing.passed is False
