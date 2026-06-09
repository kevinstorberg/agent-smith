import uuid

import pytest
from fastapi import Body, HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from assets.errors import InvalidStorageKey
from src.api.errors import REQUEST_ID_HEADER, APIException, RequestIDMiddleware
from src.app import create_app
from src.settings import reset_settings


class ItemPayload(BaseModel):
    name: str
    count: int


def create_error_test_app():
    app = create_app()

    @app.get("/raise-http")
    async def raise_http():
        raise HTTPException(status_code=401, detail="Authentication required")

    @app.get("/raise-api")
    async def raise_api():
        raise APIException(
            status_code=409,
            code="conflict",
            message="Item already exists",
            details=[{"field": "name", "message": "Name is already taken", "type": "unique"}],
        )

    @app.post("/items")
    async def create_item(payload: ItemPayload = Body(...)):
        return payload

    @app.get("/raise-unhandled")
    async def raise_unhandled():
        raise RuntimeError("database password leaked")

    @app.get("/raise-storage-key")
    async def raise_storage_key():
        raise InvalidStorageKey("Invalid storage key: '../escape.txt'")

    return app


@pytest.fixture
async def client():
    app = create_error_test_app()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


@pytest.mark.integration
async def test_successful_response_includes_generated_request_id(client):
    response = await client.get("/health")

    request_id = response.headers[REQUEST_ID_HEADER]
    uuid.UUID(request_id)
    assert response.status_code == 200


@pytest.mark.integration
async def test_incoming_request_id_is_preserved(client):
    response = await client.get("/raise-http", headers={REQUEST_ID_HEADER: "request-123"})
    error = response.json()["error"]

    assert response.headers[REQUEST_ID_HEADER] == "request-123"
    assert error["request_id"] == "request-123"


@pytest.mark.integration
async def test_blank_request_id_is_replaced(client):
    response = await client.get("/raise-http", headers={REQUEST_ID_HEADER: "   "})
    request_id = response.headers[REQUEST_ID_HEADER]
    error = response.json()["error"]

    uuid.UUID(request_id)
    assert error["request_id"] == request_id


@pytest.mark.integration
async def test_excessive_request_id_is_replaced(client):
    response = await client.get("/raise-http", headers={REQUEST_ID_HEADER: "x" * 129})
    request_id = response.headers[REQUEST_ID_HEADER]

    uuid.UUID(request_id)
    assert request_id != "x" * 129


@pytest.mark.integration
async def test_http_exception_uses_error_envelope(client):
    response = await client.get("/raise-http", headers={REQUEST_ID_HEADER: "request-401"})
    body = response.json()

    assert response.status_code == 401
    assert_security_headers(response)
    assert body == {
        "error": {
            "code": "unauthorized",
            "message": "Authentication required",
            "details": [],
            "request_id": "request-401",
        }
    }


@pytest.mark.integration
async def test_starlette_http_exception_uses_error_envelope(client):
    response = await client.get("/missing", headers={REQUEST_ID_HEADER: "request-404"})
    error = response.json()["error"]

    assert response.status_code == 404
    assert error == {
        "code": "not_found",
        "message": "Not Found",
        "details": [],
        "request_id": "request-404",
    }


@pytest.mark.integration
async def test_api_exception_preserves_explicit_error_fields(client):
    response = await client.get("/raise-api", headers={REQUEST_ID_HEADER: "request-409"})
    error = response.json()["error"]

    assert response.status_code == 409
    assert_security_headers(response)
    assert error == {
        "code": "conflict",
        "message": "Item already exists",
        "details": [{"field": "name", "message": "Name is already taken", "type": "unique"}],
        "request_id": "request-409",
    }


@pytest.mark.integration
async def test_validation_error_details_are_normalized(client):
    response = await client.post("/items", json={"count": "many"}, headers={REQUEST_ID_HEADER: "request-422"})
    error = response.json()["error"]
    details_by_field = {detail["field"]: detail for detail in error["details"]}

    assert response.status_code == 422
    assert_security_headers(response)
    assert error["code"] == "validation_error"
    assert error["message"] == "Request validation failed"
    assert error["request_id"] == "request-422"
    assert details_by_field["body.name"]["type"] == "missing"
    assert details_by_field["body.count"]["message"]
    assert all("input" not in detail for detail in error["details"])


@pytest.mark.integration
async def test_unhandled_exception_hides_details_by_default(client):
    response = await client.get("/raise-unhandled", headers={REQUEST_ID_HEADER: "request-500"})
    error = response.json()["error"]

    assert response.status_code == 500
    assert_security_headers(response)
    assert error == {
        "code": "internal_server_error",
        "message": "Internal server error",
        "details": [],
        "request_id": "request-500",
    }
    assert "database password leaked" not in response.text


@pytest.mark.integration
async def test_storage_key_exception_uses_error_envelope(client):
    response = await client.get("/raise-storage-key", headers={REQUEST_ID_HEADER: "request-storage"})
    error = response.json()["error"]

    assert response.status_code == 400
    assert_security_headers(response)
    assert error == {
        "code": "invalid_storage_key",
        "message": "Invalid storage key: '../escape.txt'",
        "details": [],
        "request_id": "request-storage",
    }


@pytest.mark.unit
def test_request_id_middleware_is_plain_asgi_middleware():
    assert not issubclass(RequestIDMiddleware, BaseHTTPMiddleware)


@pytest.mark.integration
async def test_unhandled_exception_can_include_debug_details(monkeypatch):
    monkeypatch.setenv("DEBUG_ERRORS", "true")
    reset_settings()
    try:
        app = create_error_test_app()
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as async_client:
            response = await async_client.get("/raise-unhandled", headers={REQUEST_ID_HEADER: "request-debug"})
    finally:
        reset_settings()

    error = response.json()["error"]

    assert response.status_code == 500
    assert_security_headers(response)
    assert error["request_id"] == "request-debug"
    assert error["details"] == [{"message": "database password leaked", "type": "RuntimeError"}]


def assert_security_headers(response) -> None:
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Permissions-Policy"] == "geolocation=(), microphone=(), camera=()"
