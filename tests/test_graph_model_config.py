from __future__ import annotations

from pathlib import Path

import pytest

from scripts.shared.env import read_env_file
from services.chat.participants import CHAT_MODEL_ROLE, ChatParticipant, chat_participants
from services.graphs.model_config import load_model_config, resolve_model_id

REPO_ROOT = Path(__file__).resolve().parents[1]
API_KEY = "bedrock-test-key-0123456789abcdef"
MANTLE_TEMPLATE = "https://bedrock-mantle.{region}.api.aws/v1"
RUNTIME_TEMPLATE = "https://bedrock-runtime.{region}.amazonaws.com/openai/v1"
RUNTIME_US_EAST_1 = "https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1"
MANTLE_US_EAST_1 = "https://bedrock-mantle.us-east-1.api.aws/v1"

BASE_ENV = {
    "GRAPH_MODEL_PROVIDER": "bedrock",
    "GRAPH_MODEL_REGION": "us-east-1",
    "GRAPH_MODEL_TEMPERATURE": "1.0",
    "GRAPH_MODEL_TOP_P": "0.95",
    "GRAPH_MODEL_MAX_TOKENS": "8192",
    "GRAPH_MODEL_MAX_RETRIES": "6",
    "GRAPH_MODEL_REQUEST_TIMEOUT": "300",
    "GRAPH_MODEL_STREAMING": "false",
    "BIG_MODEL_ID": "us.moonshotai.kimi-k3",
    "BIG_MODEL_SERVER_URL": RUNTIME_TEMPLATE,
    "BIG_MODEL_MAX_TOKENS": "16384",
    "SMALL_MODEL_ID": "qwen.qwen3-coder-480b-a35b-instruct",
    "SMALL_MODEL_SERVER_URL": MANTLE_TEMPLATE,
    "OPINION_MODEL_PRESET": "BIG",
    "OPINION_MODEL_SERVER_API_KEY": API_KEY,
}


def env(**overrides: str | None) -> dict[str, str]:
    merged = {**BASE_ENV, **overrides}
    return {name: value for name, value in merged.items() if value is not None}


def test_role_reads_model_endpoint_and_limits_from_its_preset():
    config = load_model_config("opinion", env=env())

    assert config.settings_chain == ("OPINION", "BIG", "GRAPH")
    assert config.provider == "bedrock"
    assert config.model_id == "us.moonshotai.kimi-k3"
    assert config.server_url == RUNTIME_US_EAST_1
    assert config.server_api_key == API_KEY
    assert config.max_tokens == 16384
    assert (config.temperature, config.top_p) == (1.0, 0.95)
    assert (config.max_retries, config.request_timeout) == (6, 300.0)
    assert config.streaming is False
    assert config.extra_body is None


def test_role_settings_beat_its_preset():
    config = load_model_config("opinion", env=env(OPINION_MODEL_MAX_TOKENS="32768"))

    assert config.max_tokens == 32768


def test_preset_names_are_normalized():
    config = load_model_config("opinion", env=env(OPINION_MODEL_PRESET=" big "))

    assert config.model_id == "us.moonshotai.kimi-k3"


def test_grader_uses_its_own_preset_and_its_parents_credentials():
    config = load_model_config(
        "opinion_grader", "opinion", env=env(OPINION_GRADER_MODEL_PRESET="SMALL")
    )

    assert config.settings_chain == ("OPINION_GRADER", "SMALL", "OPINION", "GRAPH")
    assert config.model_id == "qwen.qwen3-coder-480b-a35b-instruct"
    assert config.server_url == MANTLE_US_EAST_1
    assert config.server_api_key == API_KEY
    # The parent's preset is not in the grader's chain, so BIG's 16384 cannot leak.
    assert config.max_tokens == 8192


def test_parent_role_settings_reach_the_child_role():
    config = load_model_config(
        "opinion_grader",
        "opinion",
        env=env(OPINION_GRADER_MODEL_PRESET="SMALL", OPINION_MODEL_REQUEST_TIMEOUT="30"),
    )

    assert config.request_timeout == 30.0


def test_role_without_its_own_preset_or_model_id_fails_instead_of_inheriting_one():
    with pytest.raises(ValueError) as failure:
        load_model_config("opinion_grader", "opinion", env=env())

    message = str(failure.value)
    assert "has no MODEL_ID configured" in message
    assert "OPINION_GRADER_MODEL_ID, OPINION_MODEL_ID, GRAPH_MODEL_ID" in message
    assert "OPINION_GRADER_MODEL_PRESET" in message


def test_missing_setting_lists_every_variable_that_could_set_it():
    with pytest.raises(ValueError, match="OPINION_MODEL_MAX_TOKENS, BIG_MODEL_MAX_TOKENS, GRAPH_MODEL_MAX_TOKENS"):
        load_model_config("opinion", env=env(GRAPH_MODEL_MAX_TOKENS=None, BIG_MODEL_MAX_TOKENS=None))


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"OPINION_MODEL_PRESET": "TYPO"}, "no TYPO_MODEL_\\* settings are defined"),
        ({"OPINION_MODEL_PRESET": "  "}, "OPINION_MODEL_PRESET is empty"),
        ({"OPINION_MODEL_PRESET": "-"}, "OPINION_MODEL_PRESET: '-' has no letters or digits"),
        ({"OPINION_MODEL_PRESET": "graph"}, "names a role settings level"),
        ({"BIG_MODEL_PRESET": "SMALL"}, "presets cannot name other presets"),
        ({"GRAPH_MODEL_PRESET": "BIG"}, "GRAPH_MODEL_PRESET is not supported"),
    ],
)
def test_invalid_presets_are_rejected(overrides, match):
    with pytest.raises(ValueError, match=match):
        load_model_config("opinion", env=env(**overrides))


def test_grader_cannot_name_its_parent_role_as_a_preset():
    with pytest.raises(ValueError, match="names a role settings level"):
        load_model_config("opinion_grader", "opinion", env=env(OPINION_GRADER_MODEL_PRESET="opinion"))


@pytest.mark.parametrize(("role", "fallback_role"), [("graph", None), ("opinion", "Opinion")])
def test_roles_must_not_share_a_settings_prefix_with_their_parent_or_graph(role, fallback_role):
    with pytest.raises(ValueError, match="must not share a settings prefix"):
        load_model_config(role, fallback_role, env=env())


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"BIG_MODEL_MAX_TOKENS": "0"}, "BIG_MODEL_MAX_TOKENS must be a positive integer"),
        ({"BIG_MODEL_MAX_TOKENS": "8192.5"}, "BIG_MODEL_MAX_TOKENS must be a positive integer"),
        ({"GRAPH_MODEL_TOP_P": "1.5"}, "GRAPH_MODEL_TOP_P must be a number in \\(0, 1\\]"),
        ({"GRAPH_MODEL_TEMPERATURE": "-1"}, "GRAPH_MODEL_TEMPERATURE must be a number >= 0"),
        ({"GRAPH_MODEL_TEMPERATURE": "nan"}, "GRAPH_MODEL_TEMPERATURE must be a number >= 0"),
        ({"OPINION_MODEL_MAX_RETRIES": "-1"}, "OPINION_MODEL_MAX_RETRIES must be an integer >= 0"),
        ({"OPINION_MODEL_REQUEST_TIMEOUT": "0"}, "OPINION_MODEL_REQUEST_TIMEOUT must be a positive number"),
        ({"GRAPH_MODEL_STREAMING": "yes"}, "GRAPH_MODEL_STREAMING must be true or false"),
        ({"OPINION_MODEL_PROVIDER": "aws_kimi"}, "supported providers: bedrock"),
        ({"OPINION_MODEL_ID": "moonshotai/Kimi-K2.6"}, "dot notation"),
    ],
)
def test_invalid_values_name_the_variable_that_supplied_them(overrides, match):
    with pytest.raises(ValueError, match=match):
        load_model_config("opinion", env=env(**overrides))


@pytest.mark.parametrize(("raw", "expected"), [("true", True), ("TRUE", True), ("false", False)])
def test_streaming_flag_parses_true_or_false(raw, expected):
    assert load_model_config("opinion", env=env(GRAPH_MODEL_STREAMING=raw)).streaming is expected


def test_region_placeholder_uses_the_roles_region():
    config = load_model_config("opinion", env=env(OPINION_MODEL_REGION="us-west-2"))

    assert config.server_url == "https://bedrock-runtime.us-west-2.amazonaws.com/openai/v1"


def test_literal_url_is_accepted_when_it_agrees_with_the_region():
    config = load_model_config("opinion", env=env(OPINION_MODEL_SERVER_URL=MANTLE_US_EAST_1))

    assert config.server_url == MANTLE_US_EAST_1


def test_literal_url_for_another_region_is_rejected():
    with pytest.raises(ValueError, match="targets region eu-central-1, but GRAPH_MODEL_REGION is 'us-east-1'"):
        load_model_config(
            "opinion",
            env=env(OPINION_MODEL_SERVER_URL="https://bedrock-mantle.eu-central-1.api.aws/v1"),
        )


def test_region_placeholder_without_a_region_is_rejected():
    with pytest.raises(ValueError, match="uses \\{region\\}, but graph model role 'opinion' has no MODEL_REGION"):
        load_model_config("opinion", env=env(GRAPH_MODEL_REGION=None))


@pytest.mark.parametrize("region", ["us_east_1", "US-EAST-1", "useast1"])
def test_malformed_region_is_rejected(region):
    with pytest.raises(ValueError, match="must be an AWS region such as us-east-1"):
        load_model_config("opinion", env=env(OPINION_MODEL_REGION=region))


def test_unknown_url_placeholder_is_rejected():
    with pytest.raises(ValueError, match="unknown placeholder"):
        load_model_config(
            "opinion",
            env=env(OPINION_MODEL_SERVER_URL="https://bedrock-runtime.{regoin}.amazonaws.com/openai/v1"),
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:30000/v1",
        "https://example.com/v1",
        "http://bedrock-mantle.us-east-1.api.aws/v1",
        "https://bedrock-runtime.us-east-1.amazonaws.com.evil.example/v1",
        "https://evil.example/bedrock-runtime.us-east-1.amazonaws.com",
    ],
)
def test_non_bedrock_urls_are_rejected(url):
    with pytest.raises(ValueError, match="must be an https Amazon Bedrock endpoint"):
        load_model_config("opinion", env=env(OPINION_MODEL_SERVER_URL=url))


@pytest.mark.parametrize("api_key", ["", "your-bedrock-api-key", "local-kimi", "short-key"])
def test_placeholder_api_keys_are_rejected_without_echoing_them(api_key):
    with pytest.raises(ValueError, match="must be a real Amazon Bedrock API key") as failure:
        load_model_config("opinion", env=env(OPINION_MODEL_SERVER_API_KEY=api_key))

    if api_key:
        assert api_key not in str(failure.value)


def test_missing_api_key_lists_every_variable_that_could_set_it():
    with pytest.raises(ValueError, match="OPINION_MODEL_SERVER_API_KEY, BIG_MODEL_SERVER_API_KEY"):
        load_model_config("opinion", env=env(OPINION_MODEL_SERVER_API_KEY=None))


def test_api_key_is_kept_out_of_the_config_repr():
    assert API_KEY not in repr(load_model_config("opinion", env=env()))


@pytest.mark.parametrize(
    ("variable", "match"),
    [
        ("OPINION_MODEL_THINKING", "OPINION_MODEL_THINKING is obsolete"),
        ("OPINION_MODEL", "OPINION_MODEL is obsolete: it was renamed to MODEL_ID"),
        ("BIG_MODEL_BASE_URL", "BIG_MODEL_BASE_URL is obsolete: it was renamed to MODEL_SERVER_URL"),
        ("GRAPH_MODEL_API_KEY", "GRAPH_MODEL_API_KEY is obsolete: it was renamed to MODEL_SERVER_API_KEY"),
    ],
)
def test_obsolete_settings_fail_loudly(variable, match):
    with pytest.raises(ValueError, match=match):
        load_model_config("opinion", env=env(**{variable: "anything"}))


def test_extra_body_is_parsed_into_a_read_only_mapping():
    config = load_model_config(
        "opinion", env=env(BIG_MODEL_EXTRA_BODY='{"service_tier": "flex", "reasoning_effort": "high"}')
    )

    assert dict(config.extra_body) == {"service_tier": "flex", "reasoning_effort": "high"}
    with pytest.raises(TypeError):
        config.extra_body["service_tier"] = "priority"


@pytest.mark.parametrize("raw", ["not json", "[1, 2]", '"flex"'])
def test_extra_body_must_be_a_json_object(raw):
    with pytest.raises(ValueError, match="GRAPH_MODEL_EXTRA_BODY must be a JSON object"):
        load_model_config("opinion", env=env(GRAPH_MODEL_EXTRA_BODY=raw))


@pytest.mark.parametrize(
    ("field", "remedy"),
    [
        ("max_tokens", "set MODEL_MAX_TOKENS instead"),
        ("stream", "set MODEL_STREAMING instead"),
        ("model", "set MODEL_ID instead"),
        ("messages", "the graph runtime sets it"),
        ("tools", "the graph runtime sets it"),
    ],
)
def test_extra_body_cannot_override_fields_the_runtime_sends(field, remedy):
    with pytest.raises(ValueError, match=f"may not set '{field}': {remedy}"):
        load_model_config("opinion", env=env(OPINION_MODEL_EXTRA_BODY=f'{{"{field}": 1}}'))


def test_model_id_resolves_without_credentials():
    assert resolve_model_id("opinion", env=env(OPINION_MODEL_SERVER_API_KEY=None)) == "us.moonshotai.kimi-k3"


def _shipped_env() -> dict[str, str]:
    values = read_env_file(REPO_ROOT / ".env.default")
    for name in [name for name in values if name.endswith("_MODEL_SERVER_API_KEY")]:
        values[name] = API_KEY
    return values


@pytest.mark.parametrize(
    ("role", "fallback_role"),
    [
        ("opinion", None),
        ("opinion_grader", "opinion"),
        ("curator", None),
        ("curator_grader", "curator"),
        ("curator_reader", "curator"),
        ("chat_kimi", CHAT_MODEL_ROLE),
    ],
)
def test_shipped_config_runs_all_kimi_roles_on_kimi_k3_via_bedrock_runtime(role, fallback_role):
    config = load_model_config(role, fallback_role, env=_shipped_env())

    assert config.model_id == "us.moonshotai.kimi-k3"
    assert config.server_url == RUNTIME_US_EAST_1
    assert config.max_tokens == 16384
    assert (config.streaming, config.request_timeout, config.max_retries) == (True, 120.0, 2)


def test_shipped_config_gives_each_chat_participant_its_own_model():
    shipped = _shipped_env()
    participants = chat_participants(shipped)

    assert participants == [
        ChatParticipant(name="Kimi", model_role="chat_kimi"),
        ChatParticipant(name="Qwen", model_role="chat_qwen"),
    ]
    resolved = {
        p.name: load_model_config(p.model_role, CHAT_MODEL_ROLE, env=shipped) for p in participants
    }
    assert (resolved["Kimi"].model_id, resolved["Kimi"].server_url) == (
        "us.moonshotai.kimi-k3",
        RUNTIME_US_EAST_1,
    )
    assert (resolved["Qwen"].model_id, resolved["Qwen"].server_url) == (
        "qwen.qwen3-coder-480b-a35b-instruct",
        MANTLE_US_EAST_1,
    )


def test_shipped_config_holds_only_placeholder_api_keys():
    with pytest.raises(ValueError, match="must be a real Amazon Bedrock API key"):
        load_model_config("opinion", env=read_env_file(REPO_ROOT / ".env.default"))
