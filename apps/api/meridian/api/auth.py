"""Request authentication: session cookie or API key, CSRF, rate limits, and permission checks."""

from __future__ import annotations

import hmac
import ipaddress
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from fastapi import Depends, Request

from meridian.api import db
from meridian.api.errors import ProblemError
from meridian.api.permissions import permissions_for_role, permissions_for_scopes
from meridian.api.security import audit, ratelimit, tokens
from meridian.api.settings import get_api_settings

ACCESS_COOKIE = "ms_access"
REFRESH_COOKIE = "ms_refresh"
CSRF_COOKIE = "ms_csrf"
CSRF_HEADER = "x-csrf-token"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass
class Principal:
    kind: str  # user or api_key
    tenant_id: str | None
    role: str
    permissions: frozenset[str]
    user_id: str | None = None
    api_key_id: str | None = None
    session_id: str | None = None
    email: str | None = None
    scopes: list[str] = field(default_factory=list)

    @property
    def bypass(self) -> bool:
        """Platform administrators read across tenants unless they act inside one with X-Tenant-Id."""
        return self.role == "platform_admin" and self.tenant_id is None

    @property
    def actor_type(self) -> str:
        return "api_key" if self.kind == "api_key" else "user"


def client_ip(request: Request) -> str | None:
    """The caller's address when it is a valid IP (stored as inet), otherwise None."""
    candidate = request.client.host if request.client else ""
    if get_api_settings().trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            candidate = forwarded.split(",")[0].strip()
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def _api_key_from(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer msk_"):
        return header[7:].strip()
    key = request.headers.get("x-api-key")
    return key.strip() if key and key.startswith("msk_") else None


def _principal_from_key(request: Request, raw: str) -> Principal:
    from meridian.api.services.apikeys import authenticate

    with db.system_connection() as conn:
        found = authenticate(conn, raw)
        if found is None:
            raise ProblemError(401, "Authentication is required.", code="unauthenticated")
        conn.commit()
    ratelimit.check(
        f"key:{found['id']}", get_api_settings().rate_key_per_minute, 60, detail="API key rate limit exceeded."
    )
    return Principal(
        kind="api_key",
        tenant_id=found["tenant_id"],
        role="api_key",
        permissions=permissions_for_scopes(found["scopes"]),
        api_key_id=found["id"],
        scopes=found["scopes"],
    )


def _principal_from_cookie(request: Request, token: str) -> Principal:
    claims = tokens.decode(token, "access")
    if claims is None:
        raise ProblemError(401, "Authentication is required.", code="unauthenticated")
    with db.system_connection() as conn:
        row = conn.execute(
            """SELECT u.id, u.tenant_id, u.role, u.email FROM users u
                WHERE u.id = %s AND u.status = 'active'
                  AND EXISTS (SELECT 1 FROM refresh_tokens r WHERE r.family_id = %s AND r.user_id = u.id
                                 AND r.revoked_at IS NULL AND r.absolute_expires_at > now())""",
            (claims["sub"], claims.get("sid")),
        ).fetchone()
    if row is None:
        raise ProblemError(401, "Authentication is required.", code="unauthenticated")
    if request.method in UNSAFE:
        header, cookie = request.headers.get(CSRF_HEADER, ""), request.cookies.get(CSRF_COOKIE, "")
        if not header or not hmac.compare_digest(header, cookie):
            raise ProblemError(403, "The CSRF token is missing or does not match.", code="csrf")
    ratelimit.check(f"user:{row[0]}", get_api_settings().rate_user_per_minute, 60, detail="Rate limit exceeded.")
    tenant_id = str(row[1]) if row[1] else None
    acting = request.headers.get("x-tenant-id")
    if acting and row[2] == "platform_admin":
        try:
            tenant_id = str(uuid.UUID(acting))
        except ValueError as exc:
            raise ProblemError(422, "X-Tenant-Id must be a tenant id.", code="invalid-tenant") from exc
        with db.system_connection() as conn:
            if conn.execute("SELECT 1 FROM tenants WHERE id = %s", (tenant_id,)).fetchone() is None:
                raise ProblemError(404, "Tenant not found.", code="not-found")
    return Principal(
        kind="user",
        tenant_id=tenant_id,
        role=row[2],
        permissions=permissions_for_role(row[2]),
        user_id=str(row[0]),
        session_id=str(claims.get("sid")),
        email=row[3],
    )


def get_principal(request: Request) -> Principal:
    cached = getattr(request.state, "principal", None)
    if cached is not None:
        return cached  # type: ignore[no-any-return]
    raw_key = _api_key_from(request)
    token = request.cookies.get(ACCESS_COOKIE)
    if raw_key:
        principal = _principal_from_key(request, raw_key)
    elif token:
        principal = _principal_from_cookie(request, token)
    else:
        raise ProblemError(401, "Authentication is required.", code="unauthenticated")
    request.state.principal = principal
    return principal


def require(permission: str) -> Callable[..., Principal]:
    def dependency(request: Request, principal: Principal = Depends(get_principal)) -> Principal:
        if permission not in principal.permissions:
            with db.system_connection() as conn:
                audit.record(
                    conn,
                    "authz.denied",
                    tenant_id=principal.tenant_id,
                    actor_user_id=principal.user_id,
                    actor_type=principal.actor_type,
                    ip=client_ip(request),
                    request_id=getattr(request.state, "request_id", None),
                    detail={"permission": permission, "method": request.method, "path": request.url.path},
                )
                conn.commit()
            raise ProblemError(403, "You do not have permission to perform this action.", code="forbidden")
        return principal

    return dependency


def get_tx(principal: Principal = Depends(get_principal)) -> Iterator[db.Tx]:
    """A request transaction with Row Level Security context. Writers commit through `tx.commit()`."""
    ctx = db.Context(principal.tenant_id, principal.user_id, principal.role, principal.bypass)
    tx = db.open_tx(ctx)
    try:
        yield tx
    finally:
        tx.close()


def audit_action(
    tx: db.Tx,
    request: Request,
    principal: Principal,
    action: str,
    object_type: str | None = None,
    object_id: Any = None,
    detail: dict[str, Any] | None = None,
) -> None:
    audit.record(
        tx.conn,
        action,
        tenant_id=principal.tenant_id,
        actor_user_id=principal.user_id,
        actor_type=principal.actor_type,
        object_type=object_type,
        object_id=str(object_id) if object_id is not None else None,
        ip=client_ip(request),
        request_id=getattr(request.state, "request_id", None),
        detail=detail,
    )
