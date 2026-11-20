from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from jose import JWTError, jwt

from app.config import Settings


def create_access_token(
    settings: Settings,
    *,
    user_id: UUID,
    email: str,
) -> tuple[str, int]:
    expires_minutes = settings.access_token_expire_minutes
    expire = datetime.now(UTC) + timedelta(minutes=expires_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "exp": expire,
        "iat": datetime.now(UTC),
        "typ": "dev",
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    return token, expires_minutes * 60


def decode_dev_token(settings: Settings, token: str) -> dict[str, Any]:
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=["HS256"],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
    )


def is_dev_token_valid(settings: Settings, token: str) -> dict[str, Any] | None:
    try:
        return decode_dev_token(settings, token)
    except JWTError:
        return None