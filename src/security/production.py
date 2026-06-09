from config.models import DefaultConfig, SecurityConfig
from src.settings import DEFAULT_SECRET_KEY, Settings

MIN_SECRET_KEY_LENGTH = 32


def parse_csv_setting(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def resolve_trusted_hosts(settings: Settings, security: SecurityConfig) -> list[str]:
    env_hosts = parse_csv_setting(settings.TRUSTED_HOSTS)
    if env_hosts:
        return env_hosts
    return [host.strip() for host in security.trusted_hosts if host.strip()]


def validate_production_settings(settings: Settings, config: DefaultConfig) -> list[str]:
    if settings.APP_ENV.lower() != "production":
        return []

    errors: list[str] = []
    if settings.SECRET_KEY == DEFAULT_SECRET_KEY:
        errors.append("SECRET_KEY must be changed from the template default in production")
    if len(settings.SECRET_KEY) < MIN_SECRET_KEY_LENGTH:
        errors.append(f"SECRET_KEY must be at least {MIN_SECRET_KEY_LENGTH} characters in production")

    trusted_hosts = resolve_trusted_hosts(settings, config.security)
    if _wildcard_only(trusted_hosts):
        errors.append("TRUSTED_HOSTS or security.trusted_hosts must list explicit production hosts")

    if _wildcard_only(config.security.cors_origins):
        errors.append("security.cors_origins must list explicit production origins")

    if config.admin_debug.enabled and config.admin_debug.expose_config_values:
        errors.append("admin_debug.expose_config_values must be false in production")

    return errors


def _wildcard_only(values: list[str]) -> bool:
    normalized = [value.strip() for value in values if value.strip()]
    return not normalized or normalized == ["*"]
