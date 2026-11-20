from typing import Any

import httpx
from jose import JWTError, jwt
from jose.backends.rsa_backend import RSAKey

from app.config import Settings

_jwks_cache: dict[str, Any] | None = None


def _load_jwks(settings: Settings) -> dict[str, Any]:
    global _jwks_cache
    if _jwks_cache is not None:
        return _jwks_cache
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(settings.keycloak_jwks_url)
        resp.raise_for_status()
        _jwks_cache = resp.json()
        return _jwks_cache


def decode_keycloak_token(settings: Settings, token: str) -> dict[str, Any] | None:
    try:
        header = jwt.get_unverified_header(token)
        jwks = _load_jwks(settings)
        kid = header.get("kid")
        key_data = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
        if not key_data:
            return None
        key = RSAKey(key_data, algorithm=header.get("alg", "RS256"))
        return jwt.decode(
            token,
            key,
            algorithms=[header.get("alg", "RS256")],
            audience=settings.keycloak_audience,
            issuer=settings.keycloak_issuer,
            options={"verify_at_hash": False},
        )
    except (JWTError, httpx.HTTPError, StopIteration):
        return None