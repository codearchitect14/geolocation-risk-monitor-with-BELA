"""Operational analytics, platform administration, and the revenue views for finance."""

from __future__ import annotations

import re
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, EmailStr, Field

from meridian.api import db
from meridian.api.auth import Principal, audit_action, get_tx, require
from meridian.api.db import Tx
from meridian.api.errors import ProblemError
from meridian.api.routers.common import not_found
from meridian.api.security import passwords
from meridian.api.services.uploads import clean_text

router = APIRouter(tags=["analytics and platform"])


# -- tenant analytics -----------------------------------------------------------------------------------------------
@router.get("/analytics/operations", summary="Alert volumes and response times for this tenant")
def operations(
    days: int = Query(default=30, ge=1, le=365),
    principal: Principal = Depends(require("rules.manage")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    by_level = {
        r[0]: r[1]
        for r in tx.all(
            "SELECT level, count(*) FROM alerts WHERE created_at > now() - make_interval(days => %s) GROUP BY level",
            (days,),
        )
    }
    by_status = {
        r[0]: r[1]
        for r in tx.all(
            "SELECT status, count(*) FROM alerts WHERE created_at > now() - make_interval(days => %s) GROUP BY status",
            (days,),
        )
    }
    daily = tx.all(
        "SELECT date_trunc('day', created_at)::date, count(*) FROM alerts WHERE created_at > now() - make_interval(days => %s) GROUP BY 1 ORDER BY 1",
        (days,),
    )
    ack = tx.one(
        """SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM (ae.created_at - a.created_at)) / 60)
             FROM alerts a JOIN alert_events ae ON ae.alert_id = a.id AND ae.kind = 'status_change' AND ae.detail->>'to' = 'acknowledged'
            WHERE a.created_at > now() - make_interval(days => %s)""",
        (days,),
    )
    top_assets = tx.all(
        """SELECT s.name, count(*) FROM alerts a JOIN assets s ON s.id = a.asset_id
            WHERE a.created_at > now() - make_interval(days => %s) GROUP BY s.name ORDER BY 2 DESC LIMIT 10""",
        (days,),
    )
    return {
        "period_days": days, "alerts_by_level": by_level, "alerts_by_status": by_status,
        "alerts_per_day": [{"date": r[0], "alerts": r[1]} for r in daily],
        "median_minutes_to_acknowledge": round(float(ack[0]), 1) if ack and ack[0] is not None else None,
        "most_alerted_assets": [{"asset": r[0], "alerts": r[1]} for r in top_assets],
    }  # fmt: skip


@router.get("/analytics/quality", summary="Event quality signals: confirmation share and corrections")
def quality(
    days: int = Query(default=30, ge=1, le=365),
    principal: Principal = Depends(require("rules.manage")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    conf = {
        r[0]: r[1]
        for r in tx.all(
            "SELECT confirmation, count(*) FROM events WHERE last_seen_at > now() - make_interval(days => %s) GROUP BY 1",
            (days,),
        )
    }
    total = sum(conf.values())
    corrections = {
        f"{r[0]}:{r[1]}": r[2]
        for r in tx.all(
            "SELECT kind, status, count(*) FROM correction_requests WHERE created_at > now() - make_interval(days => %s) GROUP BY 1, 2",
            (days,),
        )
    }
    return {
        "period_days": days, "events": total, "confirmed_share": round(conf.get("confirmed", 0) / total, 3) if total else None,
        "corrections_submitted_by_this_tenant": corrections,
    }  # fmt: skip


@router.get("/analytics/usage", summary="Daily usage for this tenant (demo data)")
def usage(
    days: int = Query(default=30, ge=1, le=365),
    principal: Principal = Depends(require("rules.manage")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    rows = tx.all(
        "SELECT date, assets_monitored, alerts, briefings, api_calls, uploads FROM usage_daily WHERE date > current_date - %s ORDER BY date",
        (days,),
    )
    return {
        "items": [
            {
                "date": r[0],
                "assets_monitored": r[1],
                "alerts": r[2],
                "briefings": r[3],
                "api_calls": r[4],
                "uploads": r[5],
            }
            for r in rows
        ],
        "demo_data": True,
    }


# -- revenue (finance analyst and platform administrator) -------------------------------------------------------------
MRR_SQL = """SELECT COALESCE(sum(CASE WHEN billing_cycle = 'annual' THEN price / 12 ELSE price END), 0)
               FROM subscriptions WHERE start_date <= %s AND (end_date IS NULL OR end_date >= %s)"""


@router.get("/platform/revenue/summary", summary="Revenue summary (demo data)")
def revenue_summary(
    principal: Principal = Depends(require("revenue.view")), tx: Tx = Depends(get_tx)
) -> dict[str, Any]:
    mrr = tx.one(MRR_SQL.replace("%s", "current_date"))
    active = tx.one(
        "SELECT count(DISTINCT tenant_id) FROM subscriptions WHERE end_date IS NULL OR end_date >= current_date"
    )
    paid = tx.one("SELECT COALESCE(sum(total), 0) FROM invoices WHERE status = 'paid' AND paid_at > current_date - 365")
    overdue = tx.one("SELECT COALESCE(sum(total), 0), count(*) FROM invoices WHERE status = 'overdue'")
    assert mrr and active and paid and overdue
    return {
        "mrr": float(mrr[0]),
        "arr": float(mrr[0]) * 12,
        "active_tenants": active[0],
        "paid_last_12_months": float(paid[0]),
        "overdue_total": float(overdue[0]),
        "overdue_invoices": overdue[1],
        "demo_data": True,
    }


@router.get("/platform/revenue/mrr", summary="Monthly recurring revenue series (demo data)")
def revenue_mrr(
    months: int = Query(default=36, ge=1, le=60),
    principal: Principal = Depends(require("revenue.view")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    rows = tx.all(
        """SELECT m::date, COALESCE(sum(CASE WHEN s.billing_cycle = 'annual' THEN s.price / 12 ELSE s.price END), 0), count(DISTINCT s.tenant_id)
             FROM generate_series(date_trunc('month', current_date) - make_interval(months => %s - 1), date_trunc('month', current_date), interval '1 month') m
             LEFT JOIN subscriptions s ON s.start_date <= m + interval '1 month' - interval '1 day' AND (s.end_date IS NULL OR s.end_date >= m)
            GROUP BY m ORDER BY m""",
        (months,),
    )
    return {"items": [{"month": r[0], "mrr": float(r[1]), "tenants": r[2]} for r in rows], "demo_data": True}


@router.get("/platform/revenue/tenants", summary="Revenue by tenant (demo data)")
def revenue_tenants(
    principal: Principal = Depends(require("revenue.view")), tx: Tx = Depends(get_tx)
) -> dict[str, Any]:
    rows = tx.all(
        """SELECT t.id, t.name, s.plan_id, CASE WHEN s.billing_cycle = 'annual' THEN s.price / 12 ELSE s.price END
             FROM tenants t JOIN subscriptions s ON s.tenant_id = t.id AND s.end_date IS NULL ORDER BY 4 DESC LIMIT 200"""
    )
    return {
        "items": [{"tenant_id": str(r[0]), "tenant": r[1], "plan": r[2], "mrr": float(r[3])} for r in rows],
        "demo_data": True,
    }


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
