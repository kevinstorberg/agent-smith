from __future__ import annotations

import asyncio

import pytest

from services.graphs.runtime import (
    GraphContractError,
    build_tool_description,
    dispatch,
    scan_library,
)


def test_scan_library_includes_echo():
    registry = scan_library()
    assert "echo" in registry
    assert hasattr(registry["echo"], "INPUT_SCHEMA")
    assert hasattr(registry["echo"], "build_graph")


def test_scan_library_includes_opinion():
    registry = scan_library()
    assert "opinion" in registry
    assert registry["opinion"].INPUT_SCHEMA == {"proposal": "string"}
    assert not hasattr(registry["opinion"], "MODEL")
    assert not hasattr(registry["opinion"], "PROVIDER")


def test_build_tool_description_names_available_types():
    description = build_tool_description()
    assert "echo" in description
    assert "opinion" in description
    assert "proposal" in description


def test_dispatch_echo_round_trips():
    result = asyncio.run(dispatch("echo", {"text": "hello"}))
    assert result == "hello"


def test_dispatch_unknown_type_raises():
    with pytest.raises(KeyError, match="unknown graph type: 'nope'"):
        asyncio.run(dispatch("nope", {"text": "x"}))


def test_dispatch_rejects_missing_input():
    with pytest.raises(ValueError, match="input 'text' missing or wrong type"):
        asyncio.run(dispatch("echo", {}))


def test_dispatch_rejects_wrong_type():
    with pytest.raises(ValueError, match="input 'text' missing or wrong type"):
        asyncio.run(dispatch("echo", {"text": 123}))


def test_dispatch_rejects_empty_type():
    with pytest.raises(AssertionError):
        asyncio.run(dispatch("", {"text": "x"}))


def test_dispatch_rejects_non_dict_inputs():
    with pytest.raises(AssertionError):
        asyncio.run(dispatch("echo", "not a dict"))  # type: ignore[arg-type]


def test_skipped_module_does_not_break_scan(tmp_path, monkeypatch):
    import services.graphs.library as lib_pkg

    broken = tmp_path / "broken.py"
    broken.write_text("# missing INPUT_SCHEMA and build_graph\n")
    monkeypatch.syspath_prepend(str(tmp_path))

    monkeypatch.setattr(
        lib_pkg, "__path__", [*list(lib_pkg.__path__), str(tmp_path)]
    )
    registry = scan_library()
    assert "broken" not in registry
    assert "echo" in registry


def test_graph_contract_error_is_runtime_error():
    assert issubclass(GraphContractError, RuntimeError)


def test_opinion_loads_rules_for_opinion_agent(monkeypatch):
    from services.graphs.library import opinion

    captured = {}

    def _fake_collect(agent, project=None):
        captured["agent"] = agent
        return [("dry", "## DRY\n* **Your Process:**\n    1. Reuse existing logic.")]

    monkeypatch.setattr(
        "services.api.models.rule.collect_rules_from_db", _fake_collect
    )

    rules = opinion._load_selected_rules()

    assert captured["agent"] == "opinion"
    assert [name for name, _ in rules] == ["dry"]


def test_opinion_fails_when_no_rules_assigned_to_opinion_agent(monkeypatch):
    from services.graphs.library import opinion

    monkeypatch.setattr(
        "services.api.models.rule.collect_rules_from_db", lambda agent, project=None: []
    )

    with pytest.raises(ValueError, match="assigned to agent 'opinion'"):
        opinion._load_selected_rules()


def test_rubric_formatting_includes_rule_titles_and_numbered_steps():
    from services.rubric import rules_to_rubric

    rubric = rules_to_rubric([
        (
            "DRY",
            "## DRY\n* **Your Process:**\n    1. Search for existing code.\n    2. Extend it.",
        )
    ])

    assert "- DRY: Search for existing code" in rubric
    assert "- DRY: Extend it" in rubric
