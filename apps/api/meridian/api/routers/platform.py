"""Operational analytics, platform administration, and the revenue views for finance."""

from __future__ import annotations

import re
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field

from meridian.api import db
from meridian.api.auth import Principal, audit_action, get_tx, require
from meridian.api.db import Tx
from meridian.api.errors import ProblemError
from meridian.api.routers.common import not_found
from meridian.api.security import passwords
from meridian.api.services.uploads import clean_text

router = APIRouter(tags=["analytics and platform"])


# -- platform administration ----------------------------------------------------------------------------------------
class TenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    industry: str | None = Field(default=None, max_length=60)
    country_code: str | None = Field(default=None, pattern="^[A-Za-z]{2}$")
    is_demo: bool = True
    admin_email: EmailStr
    admin_name: str = Field(min_length=1, max_length=100)


class TenantPatch(BaseModel):
    status: Literal["active", "suspended", "churned"]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:50] or "tenant"


@router.get("/platform/tenants", summary="List tenants")
def list_tenants(
    principal: Principal = Depends(require("platform.manage")), tx: Tx = Depends(get_tx)
) -> dict[str, Any]:
    rows = tx.all(
        """SELECT t.id, t.name, t.slug, t.industry, t.country_code, t.status, t.is_demo, t.created_at,
                  (SELECT count(*) FROM users u WHERE u.tenant_id = t.id), (SELECT count(*) FROM assets a WHERE a.tenant_id = t.id)
             FROM tenants t ORDER BY t.created_at DESC LIMIT 500"""
    )
    return {
        "items": [
            {
                "id": str(r[0]),
                "name": r[1],
                "slug": r[2],
                "industry": r[3],
                "country_code": r[4],
                "status": r[5],
                "is_demo": r[6],
                "created_at": r[7],
                "users": r[8],
                "assets": r[9],
            }
            for r in rows
        ]
    }


@router.post("/platform/tenants", summary="Create a tenant with its first administrator", status_code=201)
def create_tenant(
    body: TenantCreate,
    request: Request,
    principal: Principal = Depends(require("platform.manage")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    with db.system_connection() as conn:
        if conn.execute("SELECT 1 FROM users WHERE lower(email) = %s", (body.admin_email.lower(),)).fetchone():
            raise ProblemError(409, "A user with this email already exists.", code="duplicate")
    slug = _slug(body.name)
    if tx.one("SELECT 1 FROM tenants WHERE slug = %s", (slug,)):
        slug = f"{slug}-{uuid.uuid4().hex[:6]}"
    tenant = tx.one(
        "INSERT INTO tenants (name, slug, industry, country_code, is_demo) VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (
            clean_text(body.name, 100),
            slug,
            body.industry,
            body.country_code.upper() if body.country_code else None,
            body.is_demo,
        ),
    )
    assert tenant is not None
    import secrets as _secrets

    user = tx.one(
        "INSERT INTO users (tenant_id, email, display_name, password_hash, role, status) VALUES (%s, %s, %s, %s, 'tenant_admin', 'invited') RETURNING id",
        (
            tenant[0],
            body.admin_email.lower(),
            clean_text(body.admin_name, 100),
            passwords.hash_password(_secrets.token_urlsafe(32)),
        ),
    )
    assert user is not None
    audit_action(tx, request, principal, "tenant.create", "tenant", tenant[0])
    tx.commit()
    return {
        "id": str(tenant[0]),
        "slug": slug,
        "admin_user_id": str(user[0]),
        "note": "Send the administrator an invitation from the users page.",
    }


@router.patch("/platform/tenants/{tenant_id}", summary="Suspend, reactivate, or close a tenant")
def patch_tenant(
    tenant_id: uuid.UUID,
    body: TenantPatch,
    request: Request,
    principal: Principal = Depends(require("platform.manage")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    if tx.execute("UPDATE tenants SET status = %s WHERE id = %s", (body.status, str(tenant_id))).rowcount == 0:
        raise not_found("Tenant")
    audit_action(tx, request, principal, "tenant.update", "tenant", tenant_id, {"status": body.status})
    tx.commit()
    if body.status != "active":
        from meridian.api.services import sessions

        with db.system_connection() as conn:
            for (uid,) in conn.execute("SELECT id FROM users WHERE tenant_id = %s", (str(tenant_id),)).fetchall():
                sessions.revoke_user(conn, str(uid))
            conn.commit()
    return {"id": str(tenant_id), "status": body.status}
