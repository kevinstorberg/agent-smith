import pytest
from fastapi import Body
from httpx import ASGITransport, AsyncClient

from config.models import DefaultConfig, SecurityConfig
from src.api.errors import REQUEST_ID_HEADER
from src.settings import DEFAULT_SECRET_KEY, Settings


def create_security_test_app(monkeypatch, *, security: SecurityConfig, settings: Settings | None = None):
    import src.app as app_module

    monkeypatch.setattr(app_module, "load_default_config", lambda: DefaultConfig(security=security))
    monkeypatch.setattr(
        app_module,
        "get_settings",
        lambda: settings or Settings(_env_file=None, APP_ENV="development", ANTHROPIC_API_KEY="key"),
    )
    return app_module.create_app()


@pytest.mark.integration
async def test_health_response_includes_security_headers(monkeypatch):
    app = create_security_test_app(monkeypatch, security=SecurityConfig(rate_limit_enabled=False))
    transport = ASGITransport(app=app, raise_app_exceptions=False)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Permissions-Policy"] == "geolocation=(), microphone=(), camera=()"
    assert "Strict-Transport-Security" not in response.headers


@pytest.mark.integration
async def test_hsts_header_is_enabled_by_runtime_setting(monkeypatch):
    settings = Settings(_env_file=None, APP_ENV="development", SECURE_HEADERS_HSTS_ENABLED=True)
    app = create_security_test_app(
        monkeypatch,
        security=SecurityConfig(rate_limit_enabled=False),
        settings=settings,
    )
    transport = ASGITransport(app=app, raise_app_exceptions=False)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"


@pytest.mark.integration
async def test_request_body_limit_returns_error_envelope(monkeypatch):
    app = create_security_test_app(
        monkeypatch,
        security=SecurityConfig(rate_limit_enabled=False, max_request_body_bytes=4),
    )

    @app.post("/echo")
    async def echo(payload: bytes = Body(...)):
        return {"size": len(payload)}

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/echo", content=b"12345", headers={REQUEST_ID_HEADER: "body-limit"})

    assert response.status_code == 413
    assert response.headers[REQUEST_ID_HEADER] == "body-limit"
    assert response.json() == {
        "error": {
            "code": "request_body_too_large",
            "message": "Request body exceeds 4 bytes",
            "details": [],
            "request_id": "body-limit",
        }
    }


@pytest.mark.integration
async def test_rate_limit_returns_error_envelope_and_retry_after(monkeypatch):
    app = create_security_test_app(
        monkeypatch,
        security=SecurityConfig(rate_limit_enabled=True, rate_limit_requests=1, rate_limit_window_seconds=60),
    )
    transport = ASGITransport(app=app, raise_app_exceptions=False)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.get("/health", headers={REQUEST_ID_HEADER: "rate-1"})
        second = await client.get("/health", headers={REQUEST_ID_HEADER: "rate-2"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers[REQUEST_ID_HEADER] == "rate-2"
    assert second.headers["Retry-After"] == "60"
    assert second.json() == {
        "error": {
            "code": "rate_limit_exceeded",
            "message": "Rate limit exceeded",
            "details": [],
            "request_id": "rate-2",
        }
    }


@pytest.mark.integration
async def test_trusted_host_allows_configured_host_and_rejects_unknown_host(monkeypatch):
    app = create_security_test_app(
        monkeypatch,
        security=SecurityConfig(
            trusted_hosts=["allowed.test"],
            cors_origins=["https://allowed.test"],
            rate_limit_enabled=False,
        ),
    )
    transport = ASGITransport(app=app, raise_app_exceptions=False)

    async with AsyncClient(transport=transport, base_url="http://allowed.test") as client:
        allowed = await client.get("/health")
    async with AsyncClient(transport=transport, base_url="http://blocked.test") as client:
        blocked = await client.get("/health", headers={REQUEST_ID_HEADER: "bad-host"})

    assert allowed.status_code == 200
    assert blocked.status_code == 400
    assert blocked.headers[REQUEST_ID_HEADER] == "bad-host"
    assert blocked.headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.unit
def test_create_app_rejects_unsafe_production_settings(monkeypatch):
    import src.app as app_module

    monkeypatch.setattr(app_module, "load_default_config", lambda: DefaultConfig())
    monkeypatch.setattr(
        app_module,
        "get_settings",
        lambda: Settings(_env_file=None, APP_ENV="production", SECRET_KEY=DEFAULT_SECRET_KEY),
    )

    with pytest.raises(RuntimeError, match="Production security settings are invalid"):
        app_module.create_app()
