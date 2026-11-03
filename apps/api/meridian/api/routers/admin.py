"""Tenant administration: users, API keys, webhooks, audit log, risk configuration, and billing views."""

from __future__ import annotations

import datetime as dt
import secrets
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, EmailStr, Field

from meridian.api import db
from meridian.api.auth import Principal, audit_action, get_tx, require
from meridian.api.db import Tx
from meridian.api.errors import ProblemError
from meridian.api.pagination import clamp_limit, decode_cursor, encode_cursor, page
from meridian.api.permissions import VALID_SCOPES
from meridian.api.routers.common import dumps, not_found
from meridian.api.security import audit, crypto, passwords, ssrf, tokens
from meridian.api.services import apikeys, sessions, webhooks
from meridian.api.services.mailer import Mailer, get_mailer
from meridian.api.services.uploads import clean_text
from meridian.api.settings import get_api_settings

router = APIRouter(tags=["administration"])
INVITE_TTL = dt.timedelta(days=7)


# -- users ----------------------------------------------------------------------------------------------------------
class UserCreate(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=100)
    role: Literal["viewer", "analyst", "manager", "tenant_admin"]
    tenant_id: uuid.UUID | None = Field(default=None, description="Platform administrators only")


class UserPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    role: Literal["viewer", "analyst", "manager", "tenant_admin"] | None = None
    status: Literal["active", "disabled"] | None = None


def _user(r: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": str(r[0]),
        "email": r[1],
        "display_name": r[2],
        "role": r[3],
        "status": r[4],
        "last_login_at": r[5],
        "created_at": r[6],
    }


USER_SQL = "SELECT id, email, display_name, role, status, last_login_at, created_at FROM users"


@router.get("/admin/users", summary="List users of this tenant")
def list_users(principal: Principal = Depends(require("admin.manage")), tx: Tx = Depends(get_tx)) -> dict[str, Any]:
    where, params = (
        ("WHERE tenant_id = %s", [principal.tenant_id]) if principal.tenant_id else ("WHERE tenant_id IS NOT NULL", [])
    )
    return {"items": [_user(r) for r in tx.all(f"{USER_SQL} {where} ORDER BY created_at DESC LIMIT 500", params)]}  # noqa: S608


@router.post("/admin/users", summary="Invite a user", status_code=201)
def create_user(
    body: UserCreate,
    request: Request,
    principal: Principal = Depends(require("admin.manage")),
    tx: Tx = Depends(get_tx),
    mailer: Mailer = Depends(get_mailer),
) -> dict[str, Any]:
    tenant_id = principal.tenant_id or (str(body.tenant_id) if body.tenant_id else None)
    if tenant_id is None:
        raise ProblemError(422, "tenant_id is required.", code="tenant-required")
    if principal.tenant_id and body.tenant_id and str(body.tenant_id) != principal.tenant_id:
        raise ProblemError(403, "You cannot create users in another tenant.", code="forbidden")
    if tx.one("SELECT 1 FROM tenants WHERE id = %s", (tenant_id,)) is None:
        raise not_found("Tenant")
    email = body.email.lower()
    with db.system_connection() as conn:
        if conn.execute("SELECT 1 FROM users WHERE lower(email) = %s", (email,)).fetchone():
            raise ProblemError(409, "A user with this email already exists.", code="duplicate")
    # The password is unusable until the invited person chooses one through the reset link.
    row = tx.one(
        f"INSERT INTO users (tenant_id, email, display_name, password_hash, role, status) VALUES (%s, %s, %s, %s, %s, 'invited') RETURNING {USER_SQL[7 : USER_SQL.index(' FROM')]}",  # noqa: S608
        (
            tenant_id,
            email,
            clean_text(body.display_name, 100),
            passwords.hash_password(secrets.token_urlsafe(32)),
            body.role,
        ),
    )
    assert row is not None
    audit_action(tx, request, principal, "user.create", "user", row[0], {"role": body.role})
    tx.commit()
    raw = secrets.token_urlsafe(32)
    with db.system_connection() as conn:
        conn.execute(
            "INSERT INTO password_reset_tokens (user_id, token_hash, purpose, expires_at) VALUES (%s, %s, 'invite', %s)",
            (row[0], tokens.sha256_hex(raw), dt.datetime.now(dt.UTC) + INVITE_TTL),
        )
        conn.commit()
    mailer.send(
        email,
        "You have been invited to Meridian Signal",
        f"Choose your password within 7 days:\n{get_api_settings().public_url}/reset-password?token={raw}",
    )
    return _user(row)


@router.patch("/admin/users/{user_id}", summary="Change a user's role or status")
def patch_user(
    user_id: uuid.UUID,
    body: UserPatch,
    request: Request,
    principal: Principal = Depends(require("admin.manage")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    current = tx.one(USER_SQL + " WHERE id = %s AND tenant_id IS NOT NULL", (str(user_id),))
    if current is None:
        raise not_found("User")
    data = body.model_dump(exclude_unset=True)
    if str(user_id) == principal.user_id and (
        data.get("role") not in (None, current[3]) or data.get("status") == "disabled"
    ):
        raise ProblemError(409, "You cannot change your own role or disable yourself.", code="self-change")
    sets: list[str] = []
    params: list[Any] = []
    for column in ("display_name", "role", "status"):
        if data.get(column) is not None:
            sets.append(f"{column} = %s")
            params.append(clean_text(data[column], 100) if column == "display_name" else data[column])
    if sets:
        tx.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = %s", [*params, str(user_id)])  # noqa: S608
        audit_action(tx, request, principal, "user.update", "user", user_id, {"fields": sorted(data)})
        tx.commit()
        if data.get("status") == "disabled" or data.get("role"):
            with db.system_connection() as conn:
                sessions.revoke_user(conn, str(user_id))
                conn.commit()
    row = tx.one(USER_SQL + " WHERE id = %s", (str(user_id),))
    assert row is not None
    return _user(row)


# -- API keys -------------------------------------------------------------------------------------------------------
class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(min_length=1, max_length=len(VALID_SCOPES))
    expires_in_days: int | None = Field(default=90, ge=1, le=730)

    model_config = {
        "json_schema_extra": {"example": {"name": "Alert export", "scopes": ["read", "alerts"], "expires_in_days": 90}}
    }


def _key(r: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": str(r[0]),
        "name": r[1],
        "prefix": r[2],
        "scopes": r[3],
        "created_at": r[4],
        "expires_at": r[5],
        "last_used_at": r[6],
        "revoked_at": r[7],
    }


KEY_SQL = "SELECT id, name, prefix, scopes, created_at, expires_at, last_used_at, revoked_at FROM api_keys"


@router.get("/admin/api-keys", summary="List API keys (secrets are never shown)")
def list_keys(principal: Principal = Depends(require("admin.manage")), tx: Tx = Depends(get_tx)) -> dict[str, Any]:
    return {"items": [_key(r) for r in tx.all(KEY_SQL + " ORDER BY created_at DESC LIMIT 200")]}


@router.post("/admin/api-keys", summary="Create an API key; the secret is shown once", status_code=201)
def create_key(
    body: ApiKeyCreate,
    request: Request,
    principal: Principal = Depends(require("admin.manage")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    if principal.tenant_id is None:
        raise ProblemError(
            422, "API keys belong to a tenant. Use a tenant administrator account.", code="tenant-required"
        )
    bad = [s for s in body.scopes if s not in VALID_SCOPES]
    if bad:
        raise ProblemError(422, f"Unknown scope. Valid scopes: {', '.join(VALID_SCOPES)}.", code="invalid-scope")
    full, prefix, digest = apikeys.generate()
    expires = dt.datetime.now(dt.UTC) + dt.timedelta(days=body.expires_in_days) if body.expires_in_days else None
    row = tx.one(
        f"INSERT INTO api_keys (tenant_id, name, prefix, secret_hash, scopes, created_by, expires_at) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING {KEY_SQL[7 : KEY_SQL.index(' FROM')]}",  # noqa: S608
        (principal.tenant_id, clean_text(body.name, 100), prefix, digest, body.scopes, principal.user_id, expires),
    )
    assert row is not None
    audit_action(tx, request, principal, "api_key.create", "api_key", row[0], {"scopes": body.scopes})
    tx.commit()
    return {**_key(row), "key": full, "note": "Store this key now. It cannot be shown again."}


@router.delete("/admin/api-keys/{key_id}", summary="Revoke an API key", status_code=204)
def revoke_key(
    key_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require("admin.manage")),
    tx: Tx = Depends(get_tx),
) -> Response:
    if (
        tx.execute(
            "UPDATE api_keys SET revoked_at = now() WHERE id = %s AND revoked_at IS NULL", (str(key_id),)
        ).rowcount
        == 0
    ):
        raise not_found("API key")
    audit_action(tx, request, principal, "api_key.revoke", "api_key", key_id)
    tx.commit()
    return Response(status_code=204)


# -- webhooks -------------------------------------------------------------------------------------------------------
class WebhookBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=10, max_length=500)
    min_level: Literal["low", "medium", "high", "critical"] = "medium"
    include_coordinates: bool = False


class WebhookPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    url: str | None = Field(default=None, min_length=10, max_length=500)
    min_level: Literal["low", "medium", "high", "critical"] | None = None
    include_coordinates: bool | None = None
    enabled: bool | None = None


HOOK_SQL = "SELECT id, name, url, min_level, include_coordinates, enabled, secret_rotated_at, created_at FROM webhooks"


def _hook(r: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": str(r[0]),
        "name": r[1],
        "url": r[2],
        "min_level": r[3],
        "include_coordinates": r[4],
        "enabled": r[5],
        "secret_rotated_at": r[6],
        "created_at": r[7],
    }


def _safe_url(url: str) -> str:
    try:
        ssrf.validate_url(url)
    except ssrf.UnsafeUrl as exc:
        raise ProblemError(422, str(exc), code="unsafe-url") from exc
    return url.strip()


@router.get("/admin/webhooks", summary="List webhooks")
def list_hooks(principal: Principal = Depends(require("admin.manage")), tx: Tx = Depends(get_tx)) -> dict[str, Any]:
    return {"items": [_hook(r) for r in tx.all(HOOK_SQL + " ORDER BY created_at DESC LIMIT 100")]}


@router.post("/admin/webhooks", summary="Create a webhook; the signing secret is shown once", status_code=201)
def create_hook(
    body: WebhookBody,
    request: Request,
    principal: Principal = Depends(require("admin.manage")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    if principal.tenant_id is None:
        raise ProblemError(422, "Webhooks belong to a tenant.", code="tenant-required")
    url = _safe_url(body.url)
    secret = webhooks.new_secret()
    row = tx.one(
        f"INSERT INTO webhooks (tenant_id, name, url, secret_encrypted, min_level, include_coordinates, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING {HOOK_SQL[7 : HOOK_SQL.index(' FROM')]}",  # noqa: S608
        (
            principal.tenant_id,
            clean_text(body.name, 100),
            url,
            crypto.encrypt(secret),
            body.min_level,
            body.include_coordinates,
            principal.user_id,
        ),
    )
    assert row is not None
    audit_action(tx, request, principal, "webhook.create", "webhook", row[0])
    tx.commit()
    return {**_hook(row), "signing_secret": secret, "note": "Store the signing secret now. It cannot be shown again."}


@router.patch("/admin/webhooks/{hook_id}", summary="Update a webhook")
def patch_hook(
    hook_id: uuid.UUID,
    body: WebhookPatch,
    request: Request,
    principal: Principal = Depends(require("admin.manage")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    if tx.one("SELECT 1 FROM webhooks WHERE id = %s", (str(hook_id),)) is None:
        raise not_found("Webhook")
    data = body.model_dump(exclude_unset=True)
    sets: list[str] = []
    params: list[Any] = []
    for column in ("name", "min_level", "include_coordinates", "enabled"):
        if data.get(column) is not None:
            sets.append(f"{column} = %s")
            params.append(data[column])
    if data.get("url"):
        sets.append("url = %s")
        params.append(_safe_url(data["url"]))
    if sets:
        tx.execute(f"UPDATE webhooks SET {', '.join(sets)} WHERE id = %s", [*params, str(hook_id)])  # noqa: S608
        audit_action(tx, request, principal, "webhook.update", "webhook", hook_id, {"fields": sorted(data)})
        tx.commit()
    row = tx.one(HOOK_SQL + " WHERE id = %s", (str(hook_id),))
    assert row is not None
    return _hook(row)


@router.delete("/admin/webhooks/{hook_id}", summary="Delete a webhook", status_code=204)
def delete_hook(
    hook_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require("admin.manage")),
    tx: Tx = Depends(get_tx),
) -> Response:
    if tx.execute("DELETE FROM webhooks WHERE id = %s", (str(hook_id),)).rowcount == 0:
        raise not_found("Webhook")
    audit_action(tx, request, principal, "webhook.delete", "webhook", hook_id)
    tx.commit()
    return Response(status_code=204)


@router.post(
    "/admin/webhooks/{hook_id}/rotate-secret",
    summary="Rotate the signing secret; the old one stays valid for seven days",
)
def rotate_secret(
    hook_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require("admin.manage")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    secret = webhooks.new_secret()
    done = tx.execute(
        "UPDATE webhooks SET previous_secret_encrypted = secret_encrypted, secret_encrypted = %s, secret_rotated_at = now() WHERE id = %s",
        (crypto.encrypt(secret), str(hook_id)),
    )
    if done.rowcount == 0:
        raise not_found("Webhook")
    audit_action(tx, request, principal, "webhook.rotate_secret", "webhook", hook_id)
    tx.commit()
    return {"signing_secret": secret, "previous_secret_valid_days": 7}


@router.get("/admin/webhooks/{hook_id}/deliveries", summary="Delivery log")
def deliveries(
    hook_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(require("admin.manage")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    if tx.one("SELECT 1 FROM webhooks WHERE id = %s", (str(hook_id),)) is None:
        raise not_found("Webhook")
    rows = tx.all(
        "SELECT id, kind, status, attempts, last_status_code, last_error, created_at, delivered_at, next_attempt_at FROM webhook_deliveries WHERE webhook_id = %s ORDER BY created_at DESC LIMIT %s",
        (str(hook_id), limit),
    )
    return {
        "items": [
            {
                "id": str(r[0]),
                "kind": r[1],
                "status": r[2],
                "attempts": r[3],
                "last_status_code": r[4],
                "last_error": r[5],
                "created_at": r[6],
                "delivered_at": r[7],
                "next_attempt_at": r[8],
            }
            for r in rows
        ]
    }


@router.post("/admin/webhooks/{hook_id}/test", summary="Queue a test delivery", status_code=202)
def test_hook(
    hook_id: uuid.UUID, principal: Principal = Depends(require("admin.manage")), tx: Tx = Depends(get_tx)
) -> dict[str, Any]:
    if tx.one("SELECT 1 FROM webhooks WHERE id = %s", (str(hook_id),)) is None:
        raise not_found("Webhook")
    from meridian.notify import DISCLAIMER

    row = tx.one(
        "INSERT INTO webhook_deliveries (webhook_id, tenant_id, kind, payload) VALUES (%s, %s, 'test', %s) RETURNING id",
        (
            str(hook_id),
            principal.tenant_id,
            dumps({"test": True, "message": "Test delivery from Meridian Signal.", "disclaimer": DISCLAIMER}),
        ),
    )
    assert row is not None
    tx.commit()
    return {"delivery_id": str(row[0])}


# -- audit ----------------------------------------------------------------------------------------------------------
@router.get("/admin/audit", summary="Audit log of this tenant")
def audit_log(
    action: str | None = Query(default=None, max_length=60),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    principal: Principal = Depends(require("audit.view")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    where: list[str] = ["TRUE"]
    params: list[Any] = []
    if action:
        where.append("action = %s")
        params.append(action)
    after = decode_cursor(cursor, 1)
    if after:
        where.append("id < %s")
        params.append(int(after[0]) if after[0].isdigit() else 0)
    rows = tx.all(
        f"SELECT id, actor_user_id, actor_type, action, object_type, object_id, ip::text, request_id, detail, created_at FROM audit_log WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT %s",
        [*params, clamp_limit(limit) + 1],
    )  # noqa: S608
    items = [
        {
            "id": r[0],
            "actor_id": str(r[1]) if r[1] else None,
            "actor_type": r[2],
            "action": r[3],
            "object_type": r[4],
            "object_id": r[5],
            "ip": r[6],
            "request_id": r[7],
            "detail": r[8],
            "at": r[9],
        }
        for r in rows
    ]
    return page(items, clamp_limit(limit), lambda i: encode_cursor(i["id"]))


@router.get("/admin/audit/verify", summary="Verify the hash chain of the whole audit log")
def audit_verify(principal: Principal = Depends(require("audit.view")), tx: Tx = Depends(get_tx)) -> dict[str, Any]:
    result = audit.verify(tx.conn)
    return {"entries_checked": result["entries_checked"], "intact": result["intact"]}


# -- risk configuration ---------------------------------------------------------------------------------------------
class RiskConfig(BaseModel):
    min_level: Literal["low", "medium", "high", "critical"] = "medium"
    include_coordinates: bool = Field(default=False, description="Allow webhooks to include asset coordinates")
    retention_days: int = Field(default=365, ge=30, le=3650)
    model_training_opt_in: bool = False
    daily_briefing: bool = Field(default=False, description="Generate a daily briefing for the previous UTC day")
    weekly_briefing: bool = Field(default=False, description="Generate a weekly briefing every Monday")
    briefing_email: bool = Field(default=False, description="Email generated briefings to opted-in users")

    model_config = {
        "json_schema_extra": {
            "example": {
                "min_level": "medium",
                "include_coordinates": False,
                "retention_days": 365,
                "model_training_opt_in": False,
            }
        }
    }


@router.get("/admin/risk-config", summary="Tenant risk and privacy settings")
def get_risk(principal: Principal = Depends(require("admin.manage")), tx: Tx = Depends(get_tx)) -> dict[str, Any]:
    row = tx.one("SELECT settings FROM tenants WHERE id = %s", (principal.tenant_id,))
    return RiskConfig(**((row[0] if row else {}) or {}).get("risk_config", {})).model_dump()


@router.put("/admin/risk-config", summary="Replace tenant risk and privacy settings")
def put_risk(
    body: RiskConfig,
    request: Request,
    principal: Principal = Depends(require("admin.manage")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    if principal.tenant_id is None:
        raise ProblemError(422, "Risk configuration belongs to a tenant.", code="tenant-required")
    tx.execute(
        "UPDATE tenants SET settings = settings || %s::jsonb WHERE id = %s",
        (dumps({"risk_config": body.model_dump()}), principal.tenant_id),
    )
    audit_action(tx, request, principal, "risk_config.update", "tenant", principal.tenant_id, body.model_dump())
    tx.commit()
    return body.model_dump()


# -- billing --------------------------------------------------------------------------------------------------------
@router.get("/billing/plan", summary="Current plan (demo data)")
def billing_plan(principal: Principal = Depends(require("admin.manage")), tx: Tx = Depends(get_tx)) -> dict[str, Any]:
    row = tx.one(
        """SELECT s.plan_id, p.name, s.billing_cycle, s.price, s.start_date, p.asset_limit,
                  (SELECT count(*) FROM assets WHERE status = 'active')
             FROM subscriptions s JOIN plans p ON p.id = s.plan_id WHERE s.end_date IS NULL ORDER BY s.start_date DESC LIMIT 1"""
    )
    if row is None:
        return {"plan": None, "demo_data": True}
    return {
        "plan": {
            "id": row[0],
            "name": row[1],
            "billing_cycle": row[2],
            "price": float(row[3]),
            "since": row[4],
            "asset_limit": row[5],
            "assets_in_use": row[6],
        },
        "demo_data": True,
    }


@router.get("/billing/invoices", summary="Invoices (demo data)")
def billing_invoices(
    limit: int = Query(default=24, ge=1, le=100),
    principal: Principal = Depends(require("admin.manage")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    rows = tx.all(
        "SELECT id, period_start, period_end, status, total, issued_at, due_at, paid_at FROM invoices ORDER BY period_start DESC LIMIT %s",
        (limit,),
    )
    return {
        "items": [
            {
                "id": str(r[0]),
                "period_start": r[1],
                "period_end": r[2],
                "status": r[3],
                "total": float(r[4]),
                "issued_at": r[5],
                "due_at": r[6],
                "paid_at": r[7],
            }
            for r in rows
        ],
        "demo_data": True,
    }
