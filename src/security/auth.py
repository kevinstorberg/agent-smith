from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request

from src.settings import get_settings


async def extract_token(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return None
    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization header format")
    return parts[1]


async def require_auth(token: str | None = Depends(extract_token)) -> dict:
    """Verify JWT token and return decoded payload.

    Returns decoded token claims (sub, exp, etc.) on success.
    Raises 401 if token is missing, expired, or invalid.
    """
    if token is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def create_token(subject: str, extra_claims: dict | None = None) -> str:
    """Create a signed JWT token.

    Args:
        subject: The 'sub' claim (usually user ID)
        extra_claims: Additional claims to include

    Returns:
        Encoded JWT string
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_EXPIRATION_MINUTES),
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
