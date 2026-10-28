import json

import pytest

from services.meetings.config import load_source_config
from services.meetings.factory import build_meeting_provider


def source_env(**settings):
    source = {"provider": "granola", "account_key": "personal", "api_key_env": "TEST_GRANOLA_KEY", **settings}
    return {"MEETING_SOURCES_JSON": json.dumps({"work": source}), "TEST_GRANOLA_KEY": "secret-for-tests"}


def test_config_does_not_expose_credentials_or_hash_them():
    config = load_source_config("work", source_env())
    rotated = load_source_config("work", {**source_env(), "TEST_GRANOLA_KEY": "rotated-secret"})
    assert "secret-for-tests" not in repr(config)
    assert config.fingerprint == rotated.fingerprint
    assert config.fingerprint != load_source_config("work", source_env(project="agent-smith")).fingerprint


@pytest.mark.parametrize("settings", [{"account_key": ""}, {"api_key_env": "raw secret"}, {"provider_options": []}, {"project": ""}, {"unexpected": True}])
def test_bad_source_settings_fail_at_boundary(settings):
    with pytest.raises(ValueError):
        load_source_config("work", source_env(**settings))


def test_missing_key_names_the_reference_not_the_value():
    env = source_env()
    env.pop("TEST_GRANOLA_KEY")
    with pytest.raises(ValueError, match="TEST_GRANOLA_KEY"):
        load_source_config("work", env)


def test_duplicate_accounts_cannot_run_as_independent_sources():
    env = source_env()
    sources = json.loads(env["MEETING_SOURCES_JSON"])
    sources["duplicate"] = sources["work"]
    env["MEETING_SOURCES_JSON"] = json.dumps(sources)
    with pytest.raises(ValueError, match="one meeting source"):
        load_source_config("work", env)


def test_unknown_provider_fails_without_connecting():
    with pytest.raises(ValueError, match="Unsupported meeting provider"):
        build_meeting_provider(load_source_config("work", source_env(provider="missing")))


@pytest.mark.parametrize("raw", ["[", "[]", "null"])
def test_invalid_config_json_is_rejected_without_echoing_input(raw):
    with pytest.raises(ValueError, match="JSON object"):
        load_source_config("work", {"MEETING_SOURCES_JSON": raw})
