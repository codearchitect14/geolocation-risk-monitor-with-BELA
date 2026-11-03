"""Sessions: refresh token families with rotation, reuse detection, idle and absolute lifetimes, and cookies."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import psycopg
from fastapi import Response

from meridian.api.auth import ACCESS_COOKIE, CSRF_COOKIE, REFRESH_COOKIE
from meridian.api.errors import ProblemError
from meridian.api.security import audit, tokens
from meridian.api.settings import get_api_settings


class Session:
    def __init__(self, access: str, refresh: str, csrf: str, family_id: str) -> None:
        self.access, self.refresh, self.csrf, self.family_id = access, refresh, csrf, family_id


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def start(conn: psycopg.Connection[Any], user_id: str, ip: str | None, user_agent: str | None) -> Session:
    settings = get_api_settings()
    family = str(uuid.uuid4())
    raw = tokens.new_refresh_token()
    now = _now()
    conn.execute(
        """INSERT INTO refresh_tokens (user_id, family_id, token_hash, expires_at, absolute_expires_at, user_agent, ip)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (
            user_id,
            family,
            tokens.sha256_hex(raw),
            now + dt.timedelta(seconds=settings.refresh_idle_seconds),
            now + dt.timedelta(seconds=settings.refresh_absolute_seconds),
            (user_agent or "")[:300],
            ip,
        ),
    )
    conn.execute(
        "UPDATE users SET last_login_at = now(), failed_login_count = 0, locked_until = NULL WHERE id = %s", (user_id,)
    )
    return Session(tokens.access_token(user_id, family), raw, tokens.new_csrf_token(), family)


def rotate(
    conn: psycopg.Connection[Any], raw: str, ip: str | None, user_agent: str | None, request_id: str | None
) -> Session:
    settings = get_api_settings()
    row = conn.execute(
        """SELECT r.id, r.user_id, r.family_id, r.expires_at, r.absolute_expires_at, r.revoked_at, u.status, u.tenant_id
             FROM refresh_tokens r JOIN users u ON u.id = r.user_id WHERE r.token_hash = %s FOR UPDATE OF r""",
        (tokens.sha256_hex(raw),),
    ).fetchone()
    invalid = ProblemError(401, "The session is no longer valid. Sign in again.", code="session-invalid")
    if row is None:
        raise invalid
    token_id, user_id, family, idle_expiry, absolute_expiry, revoked_at, status, tenant_id = row
    now = _now()
    if revoked_at is not None:
        # A rotated token was presented again: assume theft and end every session in the family.
        conn.execute(
            "UPDATE refresh_tokens SET revoked_at = now() WHERE family_id = %s AND revoked_at IS NULL", (family,)
        )
        audit.record(
            conn,
            "auth.refresh_reuse_detected",
            tenant_id=str(tenant_id) if tenant_id else None,
            actor_user_id=str(user_id),
            ip=ip,
            request_id=request_id,
            detail={"family": str(family)},
        )
        conn.commit()
        raise invalid
    if idle_expiry <= now or absolute_expiry <= now or status != "active":
        conn.execute(
            "UPDATE refresh_tokens SET revoked_at = now() WHERE family_id = %s AND revoked_at IS NULL", (family,)
        )
        conn.commit()
        raise invalid
    new_raw = tokens.new_refresh_token()
    new_id = conn.execute(
        """INSERT INTO refresh_tokens (user_id, family_id, token_hash, expires_at, absolute_expires_at, user_agent, ip)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (
            user_id,
            family,
            tokens.sha256_hex(new_raw),
            min(now + dt.timedelta(seconds=settings.refresh_idle_seconds), absolute_expiry),
            absolute_expiry,
            (user_agent or "")[:300],
            ip,
        ),
    ).fetchone()
    assert new_id is not None
    conn.execute(
        "UPDATE refresh_tokens SET revoked_at = now(), replaced_by = %s, last_used_at = now() WHERE id = %s",
        (new_id[0], token_id),
    )
    return Session(tokens.access_token(str(user_id), str(family)), new_raw, tokens.new_csrf_token(), str(family))


def revoke_family(conn: psycopg.Connection[Any], family_id: str) -> None:
    conn.execute(
        "UPDATE refresh_tokens SET revoked_at = now() WHERE family_id = %s AND revoked_at IS NULL", (family_id,)
    )


def revoke_user(conn: psycopg.Connection[Any], user_id: str) -> None:
    conn.execute("UPDATE refresh_tokens SET revoked_at = now() WHERE user_id = %s AND revoked_at IS NULL", (user_id,))


def set_cookies(response: Response, session: Session) -> None:
    settings = get_api_settings()
    common: dict[str, Any] = {"secure": settings.cookie_secure, "samesite": "strict"}
    response.set_cookie(
        ACCESS_COOKIE, session.access, max_age=settings.access_ttl_seconds, httponly=True, path="/api", **common
    )
    response.set_cookie(
        REFRESH_COOKIE,
        session.refresh,
        max_age=settings.refresh_absolute_seconds,
        httponly=True,
        path="/api/v1/auth",
        **common,
    )
    response.set_cookie(
        CSRF_COOKIE, session.csrf, max_age=settings.refresh_absolute_seconds, httponly=False, path="/", **common
    )


def clear_cookies(response: Response) -> None:
    for name, path in ((ACCESS_COOKIE, "/api"), (REFRESH_COOKIE, "/api/v1/auth"), (CSRF_COOKIE, "/")):
        response.delete_cookie(name, path=path)
