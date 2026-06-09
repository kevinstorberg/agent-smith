import pytest

from config.models import DefaultConfig, SecurityConfig
from src.security.production import parse_csv_setting, resolve_trusted_hosts, validate_production_settings
from src.settings import DEFAULT_SECRET_KEY, Settings


@pytest.mark.unit
def test_parse_csv_setting_trims_empty_values():
    assert parse_csv_setting(" api.example.com, , www.example.com ") == ["api.example.com", "www.example.com"]


@pytest.mark.unit
def test_resolve_trusted_hosts_prefers_runtime_env():
    settings = Settings(TRUSTED_HOSTS="api.example.com,www.example.com")
    security = SecurityConfig(trusted_hosts=["*"])

    assert resolve_trusted_hosts(settings, security) == ["api.example.com", "www.example.com"]


@pytest.mark.unit
def test_non_production_settings_allow_application_defaults():
    settings = Settings(APP_ENV="development", SECRET_KEY=DEFAULT_SECRET_KEY)
    config = DefaultConfig()

    assert validate_production_settings(settings, config) == []


@pytest.mark.unit
def test_production_settings_reject_default_secret_and_wildcards():
    settings = Settings(APP_ENV="production", SECRET_KEY=DEFAULT_SECRET_KEY)
    config = DefaultConfig()

    errors = validate_production_settings(settings, config)

    assert "SECRET_KEY must be changed from the application default in production" in errors
    assert "TRUSTED_HOSTS or security.trusted_hosts must list explicit production hosts" in errors
    assert "security.cors_origins must list explicit production origins" in errors


@pytest.mark.unit
def test_production_settings_reject_short_secret():
    settings = Settings(APP_ENV="production", SECRET_KEY="too-short", TRUSTED_HOSTS="api.example.com")
    config = DefaultConfig(security=SecurityConfig(cors_origins=["https://api.example.com"]))

    errors = validate_production_settings(settings, config)

    assert errors == ["SECRET_KEY must be at least 32 characters in production"]


@pytest.mark.unit
def test_production_settings_pass_with_explicit_values():
    settings = Settings(APP_ENV="production", SECRET_KEY="x" * 32, TRUSTED_HOSTS="api.example.com")
    config = DefaultConfig(security=SecurityConfig(cors_origins=["https://api.example.com"]))

    assert validate_production_settings(settings, config) == []
