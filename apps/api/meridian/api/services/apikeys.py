"""API keys: `msk_<prefix>_<secret>`. Only a hash of the secret is stored; the full key is shown once at creation."""

from __future__ import annotations

import datetime as dt
import hmac
import secrets
from typing import Any

import psycopg

from meridian.api.security.tokens import sha256_hex

PREFIX_LENGTH = 8


def generate() -> tuple[str, str, str]:
    """(full key, prefix, secret hash)."""
    prefix = secrets.token_hex(PREFIX_LENGTH // 2)
    secret = secrets.token_urlsafe(32)
    return f"msk_{prefix}_{secret}", f"msk_{prefix}", sha256_hex(secret)


def authenticate(conn: psycopg.Connection[Any], raw: str) -> dict[str, Any] | None:
    parts = raw.split("_", 2)
    if len(parts) != 3 or parts[0] != "msk":
        return None
    prefix, secret = f"msk_{parts[1]}", parts[2]
    row = conn.execute(
        """SELECT k.id, k.tenant_id, k.scopes, k.secret_hash, k.expires_at, k.revoked_at, k.last_used_at, t.status
             FROM api_keys k JOIN tenants t ON t.id = k.tenant_id WHERE k.prefix = %s""",
        (prefix,),
    ).fetchone()
    if row is None:
        hmac.compare_digest(sha256_hex(secret), sha256_hex("x"))  # comparable work for unknown prefixes
        return None
    key_id, tenant_id, scopes, stored, expires, revoked, last_used, tenant_status = row
    if not hmac.compare_digest(sha256_hex(secret), stored):
        return None
    now = dt.datetime.now(dt.UTC)
    if revoked is not None or (expires is not None and expires <= now) or tenant_status != "active":
        return None
    if last_used is None or (now - last_used).total_seconds() > 60:
        conn.execute("UPDATE api_keys SET last_used_at = now() WHERE id = %s", (key_id,))
    return {"id": str(key_id), "tenant_id": str(tenant_id), "scopes": list(scopes)}
