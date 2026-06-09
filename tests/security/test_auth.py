import time

import jwt
import pytest

from src.security.auth import create_token, extract_token, require_auth
from src.settings import get_settings


@pytest.mark.unit
class TestCreateToken:
    def test_creates_valid_jwt(self):
        token = create_token("user-1")
        settings = get_settings()
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        assert payload["sub"] == "user-1"

    def test_includes_iat_and_exp(self):
        token = create_token("user-1")
        settings = get_settings()
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        assert "iat" in payload
        assert "exp" in payload
        assert payload["exp"] > payload["iat"]

    def test_extra_claims_included(self):
        token = create_token("user-1", extra_claims={"role": "admin"})
        settings = get_settings()
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        assert payload["role"] == "admin"

    def test_expiration_respects_settings(self):
        settings = get_settings()
        token = create_token("user-1")
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        expected_duration = settings.JWT_EXPIRATION_MINUTES * 60
        actual_duration = payload["exp"] - payload["iat"]
        assert actual_duration == expected_duration


@pytest.mark.unit
class TestRequireAuth:
    @pytest.mark.asyncio
    async def test_missing_token_raises_401(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await require_auth(None)
        assert exc_info.value.status_code == 401
        assert "Authentication required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_valid_token_returns_payload(self):
        token = create_token("user-42")
        result = await require_auth(token)
        assert result["sub"] == "user-42"

    @pytest.mark.asyncio
    async def test_expired_token_raises_401(self):
        from fastapi import HTTPException

        settings = get_settings()
        payload = {"sub": "user-1", "iat": 1000000, "exp": 1000001}
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

        with pytest.raises(HTTPException) as exc_info:
            await require_auth(token)
        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_invalid_signature_raises_401(self):
        from fastapi import HTTPException

        payload = {"sub": "user-1", "iat": int(time.time()), "exp": int(time.time()) + 3600}
        token = jwt.encode(payload, "wrong-secret-that-is-at-least-32-bytes-long", algorithm="HS256")

        with pytest.raises(HTTPException) as exc_info:
            await require_auth(token)
        assert exc_info.value.status_code == 401
        assert "Invalid token" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_malformed_token_raises_401(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await require_auth("not.a.valid.jwt")
        assert exc_info.value.status_code == 401


@pytest.mark.unit
class TestExtractToken:
    @pytest.mark.asyncio
    async def test_extracts_bearer_token(self):
        class FakeRequest:
            headers = {"Authorization": "Bearer abc123"}

        result = await extract_token(FakeRequest())
        assert result == "abc123"

    @pytest.mark.asyncio
    async def test_missing_header_returns_none(self):
        class FakeRequest:
            headers = {}

        result = await extract_token(FakeRequest())
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_format_raises_401(self):
        from fastapi import HTTPException

        class FakeRequest:
            headers = {"Authorization": "Basic abc123"}

        with pytest.raises(HTTPException) as exc_info:
            await extract_token(FakeRequest())
        assert exc_info.value.status_code == 401
