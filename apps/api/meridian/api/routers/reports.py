"""Briefings and reports."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, model_validator

from meridian.api.auth import Principal, audit_action, get_tx, require
from meridian.api.db import Tx
from meridian.api.errors import ProblemError
from meridian.api.routers.common import dumps, not_found
from meridian.api.services import briefings, reports
from meridian.config import get_settings

router = APIRouter(tags=["briefings and reports"])
MAX_PERIOD = dt.timedelta(days=31)


class BriefingBody(BaseModel):
    kind: Literal["daily", "weekly", "custom"] = "daily"
    period_start: dt.datetime | None = None
    period_end: dt.datetime | None = None

    @model_validator(mode="after")
    def check(self) -> BriefingBody:
        if self.kind == "custom" and not (self.period_start and self.period_end):
            raise ValueError("custom briefings need period_start and period_end")
        if (
            self.period_start
            and self.period_end
            and not (self.period_start < self.period_end <= self.period_start + MAX_PERIOD)
        ):
            raise ValueError("the period must be positive and at most 31 days")
        return self


def _briefing(r: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": str(r[0]),
        "kind": r[1],
        "period_start": r[2],
        "period_end": r[3],
        "evidence": r[4],
        "narrative": r[5],
        "model_version": r[6],
        "created_at": r[7],
    }


BRIEFING_SQL = (
    "SELECT id, kind, period_start, period_end, evidence, narrative, model_version, created_at FROM briefings"
)


@router.post("/briefings", summary="Create a briefing from stored alerts", status_code=201)
def create_briefing(
    body: BriefingBody,
    request: Request,
    principal: Principal = Depends(require("rules.manage")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    end = body.period_end or dt.datetime.now(dt.UTC)
    start = body.period_start or end - (dt.timedelta(days=7) if body.kind == "weekly" else dt.timedelta(days=1))
    evidence = briefings.build_evidence(tx, start, end)
    narrative, version = briefings.narrative_for(evidence)
    row = tx.one(
        f"INSERT INTO briefings (tenant_id, kind, period_start, period_end, evidence, narrative, model_version) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING {BRIEFING_SQL[7 : BRIEFING_SQL.index(' FROM')]}",  # noqa: S608
        (principal.tenant_id, body.kind, start, end, dumps(evidence), narrative, version),
    )
    assert row is not None
    audit_action(tx, request, principal, "briefing.create", "briefing", row[0])
    tx.commit()
    return _briefing(row)


@router.get("/briefings", summary="List briefings")
def list_briefings(
    limit: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(require("view")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    return {"items": [_briefing(r) for r in tx.all(BRIEFING_SQL + " ORDER BY created_at DESC LIMIT %s", (limit,))]}


@router.get("/briefings/{briefing_id}", summary="One briefing")
def get_briefing(
    briefing_id: uuid.UUID, principal: Principal = Depends(require("view")), tx: Tx = Depends(get_tx)
) -> dict[str, Any]:
    row = tx.one(BRIEFING_SQL + " WHERE id = %s", (str(briefing_id),))
    if row is None:
        raise not_found("Briefing")
    return _briefing(row)


def _store(report_id: str, tenant_id: str, content: str, extension: str) -> str:
    folder = get_settings().data_dir / "processed" / "reports" / tenant_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{report_id}.{extension}"
    path.write_text(content, encoding="utf-8")
    return f"{tenant_id}/{report_id}.{extension}"


def _report(r: tuple[Any, ...]) -> dict[str, Any]:
    return {"id": str(r[0]), "kind": r[1], "event_id": str(r[2]) if r[2] else None, "status": r[3], "created_at": r[4]}


@router.post("/reports/incident/{event_id}", summary="Create an incident report", status_code=201)
def create_incident_report(
    event_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require("rules.manage")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    content = reports.incident_html(tx, str(event_id))
    if content is None:
        raise not_found("Event")
    new_id = str(uuid.uuid4())
    ref = _store(new_id, principal.tenant_id or "platform", content, "html")
    row = tx.one(
        "INSERT INTO reports (id, tenant_id, kind, event_id, status, file_ref, created_by) VALUES (%s, %s, 'incident', %s, 'ready', %s, %s) RETURNING id, kind, event_id, status, created_at",
        (new_id, principal.tenant_id, str(event_id), ref, principal.user_id),
    )
    assert row is not None
    audit_action(tx, request, principal, "report.create", "report", new_id, {"kind": "incident"})
    tx.commit()
    return _report(row)


@router.post("/reports/portfolio", summary="Create a portfolio exposure report", status_code=201)
def create_portfolio_report(
    request: Request, principal: Principal = Depends(require("rules.manage")), tx: Tx = Depends(get_tx)
) -> dict[str, Any]:
    new_id = str(uuid.uuid4())
    ref = _store(new_id, principal.tenant_id or "platform", reports.portfolio_html(tx), "html")
    _store(new_id, principal.tenant_id or "platform", reports.portfolio_csv(tx), "csv")
    row = tx.one(
        "INSERT INTO reports (id, tenant_id, kind, status, file_ref, created_by) VALUES (%s, %s, 'portfolio', 'ready', %s, %s) RETURNING id, kind, event_id, status, created_at",
        (new_id, principal.tenant_id, ref, principal.user_id),
    )
    assert row is not None
    audit_action(tx, request, principal, "report.create", "report", new_id, {"kind": "portfolio"})
    tx.commit()
    return _report(row)


@router.get("/reports/{report_id}", summary="A report: metadata, or the file with format=html or format=csv")
def get_report(
    report_id: uuid.UUID,
    format: str = Query(default="meta", pattern="^(meta|html|csv)$"),
    principal: Principal = Depends(require("rules.manage")),
    tx: Tx = Depends(get_tx),
) -> Any:
    row = tx.one(
        "SELECT id, kind, event_id, status, created_at, file_ref FROM reports WHERE id = %s", (str(report_id),)
    )
    if row is None:
        raise not_found("Report")
    if format == "meta":
        return _report(row)
    path = get_settings().data_dir / "processed" / "reports" / (row[5] or "").rsplit(".", 1)[0]
    file = path.with_suffix("." + format)
    if not file.is_file() or get_settings().data_dir not in file.resolve().parents:
        raise not_found("Report file")
    media = "text/html; charset=utf-8" if format == "html" else "text/csv"
    headers = {
        "Content-Disposition": f'attachment; filename="report.{format}"',
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
    }
    return Response(file.read_text(encoding="utf-8"), media_type=media, headers=headers)


_ = ProblemError
