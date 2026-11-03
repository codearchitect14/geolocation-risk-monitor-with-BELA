"""Access tokens (EdDSA JWT), opaque refresh tokens, and CSRF values."""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from functools import lru_cache
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization

from meridian.api.settings import get_api_settings

ISSUER = "meridian-signal"
AUDIENCE = "meridian-api"


@lru_cache(maxsize=4)
def _keys(pem: bytes) -> tuple[Any, Any]:
    private = serialization.load_pem_private_key(pem, password=None)
    return private, private.public_key()


def issue(typ: str, subject: str, ttl_seconds: int, **claims: Any) -> str:
    now = int(time.time())
    private, _ = _keys(get_api_settings().jwt_private_pem)
    payload = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": subject,
        "typ": typ,
        "iat": now,
        "exp": now + ttl_seconds,
        "jti": uuid.uuid4().hex,
        **claims,
    }
    return jwt.encode(payload, private, algorithm="EdDSA")


def decode(token: str, typ: str) -> dict[str, Any] | None:
    """The verified claims, or None for any problem (bad signature, expired, wrong type)."""
    _, public = _keys(get_api_settings().jwt_private_pem)
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            public,
            algorithms=["EdDSA"],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "typ"]},
        )
    except jwt.PyJWTError:
        return None
    return claims if claims.get("typ") == typ else None


def access_token(user_id: str, family_id: str) -> str:
    return issue("access", user_id, get_api_settings().access_ttl_seconds, sid=family_id)


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
