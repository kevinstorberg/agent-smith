from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.api.routers.eval_suites import (
    CreateSuiteRequest, UpdateSuiteRequest,
    CreateScenarioRequest, UpdateScenarioRequest,
)
from scripts.shared.validation import MAX_NAME_LENGTH, MAX_BODY_LENGTH


class TestCreateSuiteRequestValidation:
    def test_accepts_valid_request(self):
        body = CreateSuiteRequest(
            name="my_suite", eval_type="harness", subcategory="rules",
            judge_prompt="Rate this output.",
        )
        assert body.name == "my_suite"

    def test_rejects_empty_name(self):
        with pytest.raises(ValidationError, match="name"):
            CreateSuiteRequest(
                name="", eval_type="harness", subcategory="rules",
                judge_prompt="Rate this.",
            )

    def test_rejects_long_name(self):
        with pytest.raises(ValidationError, match="name"):
            CreateSuiteRequest(
                name="x" * (MAX_NAME_LENGTH + 1), eval_type="harness",
                subcategory="rules", judge_prompt="Rate this.",
            )

    def test_rejects_empty_judge_prompt(self):
        with pytest.raises(ValidationError, match="judge_prompt"):
            CreateSuiteRequest(
                name="suite", eval_type="harness", subcategory="rules",
                judge_prompt="",
            )

    def test_defaults(self):
        body = CreateSuiteRequest(
            name="s", eval_type="e", subcategory="sub", judge_prompt="p",
        )
        assert body.items == {}
        assert body.config == {}
        assert body.enabled is True


class TestUpdateSuiteRequestValidation:
    def test_accepts_all_none(self):
        body = UpdateSuiteRequest()
        assert body.name is None
        assert body.eval_type is None

    def test_validates_name_length(self):
        with pytest.raises(ValidationError, match="name"):
            UpdateSuiteRequest(name="x" * (MAX_NAME_LENGTH + 1))

    def test_accepts_partial_update(self):
        body = UpdateSuiteRequest(enabled=False)
        assert body.enabled is False
        assert body.name is None


class TestCreateScenarioRequestValidation:
    def test_accepts_valid(self):
        body = CreateScenarioRequest(name="login_flow", prompt="Test login.")
        assert body.name == "login_flow"

    def test_rejects_empty_name(self):
        with pytest.raises(ValidationError, match="name"):
            CreateScenarioRequest(name="", prompt="Test.")

    def test_rejects_empty_prompt(self):
        with pytest.raises(ValidationError, match="prompt"):
            CreateScenarioRequest(name="test", prompt="")

    def test_default_enabled(self):
        body = CreateScenarioRequest(name="test", prompt="Test.")
        assert body.enabled is True


class TestUpdateScenarioRequestValidation:
    def test_accepts_all_none(self):
        body = UpdateScenarioRequest()
        assert body.name is None
        assert body.prompt is None

    def test_validates_prompt_length(self):
        with pytest.raises(ValidationError, match="prompt"):
            UpdateScenarioRequest(prompt="x" * (MAX_BODY_LENGTH + 1))

    def test_accepts_partial(self):
        body = UpdateScenarioRequest(enabled=False)
        assert body.enabled is False
