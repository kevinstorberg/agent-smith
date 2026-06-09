import pytest


@pytest.fixture(autouse=True)
def reset_settings_cache():
    from src.settings import reset_settings

    reset_settings()
    yield
    reset_settings()


@pytest.mark.unit
class TestDeepMerge:
    def test_merges_nested_dicts(self):
        from config.loader import _deep_merge

        base = {"a": {"b": 1, "c": 2}, "d": 3}
        override = {"a": {"c": 99}, "e": 5}
        _deep_merge(base, override)
        assert base == {"a": {"b": 1, "c": 99}, "d": 3, "e": 5}

    def test_override_replaces_non_dict(self):
        from config.loader import _deep_merge

        base = {"a": {"b": 1}}
        override = {"a": "replaced"}
        _deep_merge(base, override)
        assert base == {"a": "replaced"}

    def test_empty_override_noop(self):
        from config.loader import _deep_merge

        base = {"a": 1}
        _deep_merge(base, {})
        assert base == {"a": 1}

    def test_adds_new_nested_keys(self):
        from config.loader import _deep_merge

        base = {"a": {"b": 1}}
        override = {"a": {"c": 2, "d": {"e": 3}}}
        _deep_merge(base, override)
        assert base == {"a": {"b": 1, "c": 2, "d": {"e": 3}}}


@pytest.mark.unit
class TestLoadDefaultConfig:
    def test_loads_successfully(self):
        from config.loader import load_default_config

        config = load_default_config()
        assert config.llm.provider is not None
        assert config.llm.model is not None
        assert config.llm.max_tokens > 0
        assert config.security.trusted_hosts == ["*"]
        assert config.security.rate_limit_enabled is True
        assert config.security.rate_limit_requests == 120
        assert config.security.max_request_body_bytes == 10485760
        assert config.security.headers.content_type_options == "nosniff"
        assert config.frontend.enabled is False
        assert config.frontend.static_dir == "frontend/dist"
        assert config.frontend.mount_path == "/ui"
        assert config.frontend.spa_fallback is True

    def test_caching_returns_same_instance(self):
        from config.loader import load_default_config

        c1 = load_default_config()
        c2 = load_default_config()
        assert c1 is c2


@pytest.mark.unit
class TestLoadGraphConfig:
    def test_nonexistent_graph_returns_defaults(self):
        from config.loader import load_graph_config

        config = load_graph_config("nonexistent_graph_xyz")
        assert config.name == "nonexistent_graph_xyz"
        assert config.llm is not None
        assert config.tools == []
        assert config.runtime.kind == "react"
        assert config.runtime.recursion_limit == 25
        assert config.checkpoint.backend == "none"

    def test_required_graph_file_raises_for_missing_config(self):
        from config.loader import GraphConfigNotFound, load_graph_config

        with pytest.raises(GraphConfigNotFound, match="Graph config not found"):
            load_graph_config("nonexistent_required_graph_xyz", require_file=True)

    def test_legacy_checkpointing_true_maps_to_memory_checkpoint_backend(self):
        from config.models import GraphConfig

        config = GraphConfig(checkpointing=True)

        assert config.checkpoint.backend == "memory"


@pytest.mark.unit
class TestSettings:
    def test_loads_app_env(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "test")
        from src.settings import Settings

        s = Settings()
        assert s.APP_ENV == "test"

    def test_backend_development_defaults_are_explicit(self, monkeypatch):
        from src.settings import Settings

        for name in (
            "APP_NAME",
            "APP_PORT",
            "POSTGRES_IMAGE",
            "POSTGRES_PORT",
            "REDIS_URL",
            "REDIS_PORT",
            "DOCUMENTDB_URI",
            "TRUSTED_HOSTS",
            "SECURE_HEADERS_HSTS_ENABLED",
        ):
            monkeypatch.delenv(name, raising=False)

        s = Settings(_env_file=None)

        assert s.APP_NAME == "cairn"
        assert s.APP_PORT == 8000
        assert s.POSTGRES_IMAGE == "pgvector/pgvector:pg16"
        assert s.POSTGRES_PORT == 5432
        assert s.REDIS_URL == "redis://localhost:6379/0"
        assert s.REDIS_PORT == 6379
        assert s.DOCUMENTDB_URI == ""
        assert s.TRUSTED_HOSTS == ""
        assert s.SECURE_HEADERS_HSTS_ENABLED is False

    def test_database_url_property_uses_current_app_env(self):
        from src.settings import Settings

        s = Settings(
            APP_ENV="test",
            DATABASE_URL_TEST="",
            POSTGRES_HOST="127.0.0.1",
            POSTGRES_PORT=55432,
            POSTGRES_USER="test_user",
            POSTGRES_PASSWORD="test_password",
            POSTGRES_DB_TEST="test_db",
        )
        assert s.database_url == "postgresql+asyncpg://test_user:test_password@127.0.0.1:55432/test_db"

    def test_database_url_for_assembles_from_postgres_components(self):
        from src.settings import Settings

        s = Settings(
            DATABASE_URL_TEST="",
            POSTGRES_HOST="localhost",
            POSTGRES_PORT=55432,
            POSTGRES_USER="cairn",
            POSTGRES_PASSWORD="cairn",
            POSTGRES_DB_TEST="cairn_test",
        )
        assert s.database_url_for("test") == "postgresql+asyncpg://cairn:cairn@localhost:55432/cairn_test"

    def test_database_url_for_explicit_url_overrides_components(self):
        from src.settings import Settings

        s = Settings(
            DATABASE_URL_TEST="postgresql+asyncpg://override:override@db.example:5432/override_db",
            POSTGRES_HOST="localhost",
            POSTGRES_PORT=55432,
            POSTGRES_USER="ignored",
            POSTGRES_PASSWORD="ignored",
            POSTGRES_DB_TEST="ignored",
        )
        assert s.database_url_for("test") == "postgresql+asyncpg://override:override@db.example:5432/override_db"

    def test_database_url_for_unknown_env_raises(self):
        from src.settings import Settings

        s = Settings()
        with pytest.raises(ValueError, match="Unknown database environment 'staging'"):
            s.database_url_for("staging")

    def test_missing_database_components_raise(self):
        from src.settings import Settings

        s = Settings(DATABASE_URL_PRODUCTION="", POSTGRES_DB_PRODUCTION="")
        with pytest.raises(ValueError, match="POSTGRES_DB_PRODUCTION"):
            s.database_url_for("production")
