"""Alerts, comments, and corrections."""

from __future__ import annotations

import json
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from meridian import notify
from meridian.api.auth import Principal, audit_action, get_tx, require
from meridian.api.db import Tx
from meridian.api.errors import ProblemError
from meridian.api.pagination import clamp_limit, decode_cursor, encode_cursor, page
from meridian.api.routers.common import dumps, not_found
from meridian.api.services.uploads import clean_text

router = APIRouter(tags=["alerts"])
STATUSES = ("new", "acknowledged", "monitoring", "escalated", "dismissed", "resolved")
TERMINAL = {"dismissed", "resolved"}

ALERT_SQL = """SELECT a.id, a.level, a.status, a.last_score, a.assignee_id, a.dismissal_reason, a.created_at, a.updated_at,
                      e.id, e.title, e.type, e.subtype, e.severity, e.status, e.confirmation, e.last_seen_at,
                      s.id, s.name, x.distance_km, a.zone_id
                 FROM alerts a JOIN events e ON e.id = a.event_id LEFT JOIN assets s ON s.id = a.asset_id
                 LEFT JOIN exposures x ON x.event_id = a.event_id AND x.asset_id = a.asset_id"""


def _alert(r: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": str(r[0]), "level": r[1], "status": r[2], "score": round(float(r[3] or 0), 4), "assignee_id": str(r[4]) if r[4] else None,
        "dismissal_reason": r[5], "created_at": r[6], "updated_at": r[7],
        "event": {"id": str(r[8]), "title": r[9], "type": r[10], "subtype": r[11], "severity": r[12], "status": r[13], "confirmation": r[14],
                  "confirmation_text": "confirmed by a second source" if r[14] == "confirmed" else "reported, not yet confirmed", "last_seen_at": r[15]},
        "asset": {"id": str(r[16]), "name": r[17], "distance_km": round(float(r[18]), 1) if r[18] is not None else None} if r[16] else None,
        "zone_id": str(r[19]) if r[19] else None, "disclaimer": notify.DISCLAIMER,
    }  # fmt: skip


@router.get("/alerts", summary="List alerts")
def list_alerts(
    status: str | None = Query(default=None, pattern="^(new|acknowledged|monitoring|escalated|dismissed|resolved)$"),
    level: str | None = Query(default=None, pattern="^(low|medium|high|critical)$"),
    asset_id: uuid.UUID | None = None,
    event_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    principal: Principal = Depends(require("view")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    where: list[str] = ["TRUE"]
    params: list[Any] = []
    for clause, value in (
        ("a.status = %s", status),
        ("a.level = %s", level),
        ("a.asset_id = %s", str(asset_id) if asset_id else None),
        ("a.event_id = %s", str(event_id) if event_id else None),
    ):
        if value is not None:
            where.append(clause)
            params.append(value)
    after = decode_cursor(cursor, 2)
    if after:
        where.append("(a.created_at, a.id) < (%s::timestamptz, %s::uuid)")
        params += after
    rows = tx.all(
        f"{ALERT_SQL} WHERE {' AND '.join(where)} ORDER BY a.created_at DESC, a.id DESC LIMIT %s",
        [*params, clamp_limit(limit) + 1],
    )  # noqa: S608
    result = page(
        [_alert(r) for r in rows], clamp_limit(limit), lambda i: encode_cursor(i["created_at"].isoformat(), i["id"])
    )
    result["disclaimer"] = notify.DISCLAIMER
    return result


@router.get("/alerts/{alert_id}", summary="One alert with its history")
def get_alert(
    alert_id: uuid.UUID, principal: Principal = Depends(require("view")), tx: Tx = Depends(get_tx)
) -> dict[str, Any]:
    row = tx.one(ALERT_SQL + " WHERE a.id = %s", (str(alert_id),))
    if row is None:
        raise not_found("Alert")
    history = tx.all(
        "SELECT kind, detail, actor_user_id, created_at FROM alert_events WHERE alert_id = %s ORDER BY created_at, id",
        (str(alert_id),),
    )
    return {
        **_alert(row),
        "history": [
            {"kind": h[0], "detail": h[1], "actor_id": str(h[2]) if h[2] else None, "at": h[3]} for h in history
        ],
    }


class AlertPatch(BaseModel):
    status: Literal["new", "acknowledged", "monitoring", "escalated", "dismissed", "resolved"] | None = None
    dismissal_reason: str | None = Field(default=None, max_length=300)
    assignee_id: uuid.UUID | None = None

    model_config = {
        "json_schema_extra": {"example": {"status": "dismissed", "dismissal_reason": "Known maintenance window"}}
    }


@router.patch("/alerts/{alert_id}", summary="Acknowledge, dismiss, escalate, resolve, or assign an alert")
def patch_alert(
    alert_id: uuid.UUID,
    body: AlertPatch,
    request: Request,
    principal: Principal = Depends(require("alerts.act")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    current = tx.one("SELECT status, assignee_id FROM alerts WHERE id = %s FOR UPDATE", (str(alert_id),))
    if current is None:
        raise not_found("Alert")
    data = body.model_dump(exclude_unset=True)
    if "assignee_id" in data and data["assignee_id"] is not None:
        if (
            tx.one(
                "SELECT 1 FROM users WHERE id = %s AND tenant_id = %s AND status = 'active'",
                (str(data["assignee_id"]), principal.tenant_id),
            )
            is None
        ):
            raise ProblemError(422, "The assignee is not a user of this tenant.", code="invalid-assignee")
    sets: list[str] = ["updated_at = now()"]
    params: list[Any] = []
    if body.status and body.status != current[0]:
        if body.status == "dismissed" and not (body.dismissal_reason or "").strip():
            raise ProblemError(422, "A reason is required to dismiss an alert.", code="reason-required")
        sets.append("status = %s")
        params.append(body.status)
        if body.status == "dismissed":
            sets.append("dismissal_reason = %s")
            params.append(clean_text(body.dismissal_reason or "", 300))
        tx.execute(
            "INSERT INTO alert_events (alert_id, tenant_id, actor_user_id, kind, detail) VALUES (%s, %s, %s, 'status_change', %s)",
            (str(alert_id), principal.tenant_id, principal.user_id, dumps({"from": current[0], "to": body.status})),
        )
    if "assignee_id" in data:
        sets.append("assignee_id = %s")
        params.append(str(data["assignee_id"]) if data["assignee_id"] else None)
        tx.execute(
            "INSERT INTO alert_events (alert_id, tenant_id, actor_user_id, kind, detail) VALUES (%s, %s, %s, 'assignment', %s)",
            (
                str(alert_id),
                principal.tenant_id,
                principal.user_id,
                dumps({"assignee_id": str(data["assignee_id"]) if data["assignee_id"] else None}),
            ),
        )
    tx.execute(f"UPDATE alerts SET {', '.join(sets)} WHERE id = %s", [*params, str(alert_id)])  # noqa: S608
    audit_action(tx, request, principal, "alert.update", "alert", alert_id, {"status": body.status})
    tx.commit()
    row = tx.one(ALERT_SQL + " WHERE a.id = %s", (str(alert_id),))
    assert row is not None
    return _alert(row)


class CommentBody(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@router.post("/alerts/{alert_id}/comments", summary="Comment on an alert", status_code=201)
def add_comment(
    alert_id: uuid.UUID,
    body: CommentBody,
    request: Request,
    principal: Principal = Depends(require("alerts.act")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    if tx.one("SELECT 1 FROM alerts WHERE id = %s", (str(alert_id),)) is None:
        raise not_found("Alert")
    row = tx.one(
        "INSERT INTO alert_events (alert_id, tenant_id, actor_user_id, kind, detail) VALUES (%s, %s, %s, 'comment', %s) RETURNING id, created_at",
        (str(alert_id), principal.tenant_id, principal.user_id, json.dumps({"text": clean_text(body.text, 2000)})),
    )
    assert row is not None
    audit_action(tx, request, principal, "alert.comment", "alert", alert_id)
    tx.commit()
    return {"id": row[0], "alert_id": str(alert_id), "text": clean_text(body.text, 2000), "created_at": row[1]}


# -- corrections ----------------------------------------------------------------------------------------------------
class CorrectionBody(BaseModel):
    event_id: uuid.UUID
    kind: Literal["wrong_location", "wrong_type", "duplicate"]
    note: str = Field(default="", max_length=1000)
    suggested_place: str | None = Field(default=None, max_length=200)
    suggested_type: str | None = Field(default=None, max_length=40)
    duplicate_of: uuid.UUID | None = None
    consent_for_gold: bool = False


class CorrectionReview(BaseModel):
    status: Literal["accepted", "rejected"]
    note: str = Field(default="", max_length=500)


@router.post("/corrections", summary="Report a wrong location, wrong type, or duplicate", status_code=201)
def create_correction(
    body: CorrectionBody, request: Request, principal: Principal = Depends(require("view")), tx: Tx = Depends(get_tx)
) -> dict[str, Any]:
    if tx.one("SELECT 1 FROM events WHERE id = %s", (str(body.event_id),)) is None:
        raise not_found("Event")
    details = {
        "note": clean_text(body.note, 1000),
        "suggested_place": body.suggested_place,
        "suggested_type": body.suggested_type,
        "duplicate_of": str(body.duplicate_of) if body.duplicate_of else None,
    }
    row = tx.one(
        "INSERT INTO correction_requests (tenant_id, event_id, kind, details, consent_for_gold, submitted_by) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id, created_at",
        (principal.tenant_id, str(body.event_id), body.kind, dumps(details), body.consent_for_gold, principal.user_id),
    )
    assert row is not None
    audit_action(tx, request, principal, "correction.create", "correction", row[0], {"kind": body.kind})
    tx.commit()
    return {
        "id": str(row[0]),
        "status": "open",
        "created_at": row[1],
        "message": "Thank you. The correction will be reviewed and the outcome recorded here.",
    }


@router.get("/corrections", summary="Corrections submitted by this tenant (all tenants for platform administrators)")
def list_corrections(
    status: str | None = Query(default=None, pattern="^(open|accepted|rejected)$"),
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(require("view")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    sql = (
        "SELECT id, event_id, kind, details, status, consent_for_gold, created_at, reviewed_at FROM correction_requests"
    )
    params: list[Any] = []
    if status:
        sql += " WHERE status = %s"
        params.append(status)
    rows = tx.all(sql + " ORDER BY created_at DESC LIMIT %s", [*params, limit])
    return {
        "items": [
            {
                "id": str(r[0]),
                "event_id": str(r[1]),
                "kind": r[2],
                "details": r[3],
                "status": r[4],
                "consent_for_gold": r[5],
                "created_at": r[6],
                "reviewed_at": r[7],
            }
            for r in rows
        ]
    }


@router.patch("/corrections/{correction_id}", summary="Review a correction (platform administrators)")
def review_correction(
    correction_id: uuid.UUID,
    body: CorrectionReview,
    request: Request,
    principal: Principal = Depends(require("platform.manage")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    row = tx.one(
        "UPDATE correction_requests SET status = %s, reviewed_by = %s, reviewed_at = now(), details = details || %s WHERE id = %s RETURNING id, status",
        (body.status, principal.user_id, dumps({"review_note": clean_text(body.note, 500)}), str(correction_id)),
    )
    if row is None:
        raise not_found("Correction")
    audit_action(tx, request, principal, "correction.review", "correction", correction_id, {"status": body.status})
    tx.commit()
    return {"id": str(row[0]), "status": row[1]}
