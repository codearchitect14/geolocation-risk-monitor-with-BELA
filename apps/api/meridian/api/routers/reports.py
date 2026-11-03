"""Briefings and reports."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field, model_validator

from meridian.api.auth import Principal, audit_action, get_tx, require
from meridian.api.db import Tx
from meridian.api.errors import ProblemError
from meridian.api.routers.common import dumps, not_found
from meridian.api.security import ratelimit
from meridian.api.services import briefings, render, reports
from meridian.api.services.mailer import Mailer, get_mailer
from meridian.config import get_settings

router = APIRouter(tags=["briefings and reports"])
MAX_PERIOD = dt.timedelta(days=31)
Writer = Callable[[dict[str, Any]], str] | None


def get_writer() -> Writer:
    """The local model narrative writer, or None when the model server is not running."""
    return briefings.local_model_writer()


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
    writer: Writer = Depends(get_writer),
) -> dict[str, Any]:
    end = body.period_end or dt.datetime.now(dt.UTC)
    start = body.period_start or end - (dt.timedelta(days=7) if body.kind == "weekly" else dt.timedelta(days=1))
    evidence = briefings.build_evidence(tx, start, end)
    narrative, version = briefings.narrative_for(evidence, writer)
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


@router.get("/briefings/{briefing_id}", summary="One briefing, or its HTML or PDF document with format=html or format=pdf")
def get_briefing(
    briefing_id: uuid.UUID,
    format: str = Query(default="json", pattern="^(json|html|pdf)$"),
    principal: Principal = Depends(require("view")),
    tx: Tx = Depends(get_tx),
) -> Any:
    row = tx.one(BRIEFING_SQL + " WHERE id = %s", (str(briefing_id),))
    if row is None:
        raise not_found("Briefing")
    view = _briefing(row)
    if format == "json":
        return view
    document = reports.briefing_html(view)
    if format == "html":
        return Response(document, media_type="text/html; charset=utf-8", headers=_FILE_HEADERS | {"Content-Disposition": 'attachment; filename="briefing.html"'})
    pdf = render.html_to_pdf(document)
    if pdf is None:
        raise ProblemError(503, "PDF export is not available. Use format=html.", code="pdf-unavailable")
    return Response(pdf, media_type="application/pdf", headers=_FILE_HEADERS | {"Content-Disposition": 'attachment; filename="briefing.pdf"'})


class EmailBody(BaseModel):
    to: list[str] = Field(default_factory=list, max_length=20, description="Addresses of users of this organisation; empty sends to all opted-in users")


@router.post("/briefings/{briefing_id}/email", summary="Email a briefing as a PDF to users of this organisation")
def email_briefing(
    briefing_id: uuid.UUID,
    body: EmailBody,
    request: Request,
    principal: Principal = Depends(require("rules.manage")),
    tx: Tx = Depends(get_tx),
    mailer: Mailer = Depends(get_mailer),
) -> dict[str, Any]:
    ratelimit.check(f"briefing-mail:{principal.tenant_id}", 20, 3600, detail="Too many briefing emails. Try again later.")
    row = tx.one(BRIEFING_SQL + " WHERE id = %s", (str(briefing_id),))
    if row is None:
        raise not_found("Briefing")
    users = tx.all("SELECT lower(email), notify_email FROM users WHERE tenant_id = %s AND status = 'active'", (principal.tenant_id,))
    members = {u[0] for u in users}
    if body.to:
        wanted = {a.strip().lower() for a in body.to}
        if wanted - members:
            raise ProblemError(422, "Briefings can only be sent to users of this organisation.", code="invalid-recipient")
        recipients = sorted(wanted)
    else:
        recipients = sorted(u[0] for u in users if u[1])
    view = _briefing(row)
    document = reports.briefing_html(view)
    pdf = render.html_to_pdf(document)
    attachment = ("briefing.pdf", pdf, "application/pdf") if pdf else ("briefing.html", document.encode(), "text/html")
    text = (view["narrative"] or "") + "\n"
    for address in recipients:
        mailer.send(address, f"{view['kind'].capitalize()} briefing", text, [attachment])
    tx.execute("UPDATE briefings SET delivered_at = now() WHERE id = %s", (str(briefing_id),))
    audit_action(tx, request, principal, "briefing.email", "briefing", briefing_id, {"recipients": len(recipients)})
    tx.commit()
    return {"sent": len(recipients), "attachment": attachment[0]}


_FILE_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox",
    "X-Content-Type-Options": "nosniff",
}


def _store(report_id: str, tenant_id: str, content: str | bytes, extension: str) -> str:
    folder = get_settings().data_dir / "processed" / "reports" / tenant_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{report_id}.{extension}"
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return f"{tenant_id}/{report_id}.{extension}"


FORMATS = {
    "html": "text/html; charset=utf-8",
    "pdf": "application/pdf",
    "csv": "text/csv",
}


def _report(r: tuple[Any, ...]) -> dict[str, Any]:
    folder = get_settings().data_dir / "processed" / "reports" / (r[5] or "").rsplit("/", 1)[0] if r[5] else None
    formats = [f for f in FORMATS if folder and (folder / f"{r[0]}.{f}").is_file()]
    return {"id": str(r[0]), "kind": r[1], "event_id": str(r[2]) if r[2] else None, "status": r[3], "created_at": r[4], "formats": formats}


REPORT_SQL = "SELECT id, kind, event_id, status, created_at, file_ref FROM reports"


def _finish(tx: Tx, request: Request, principal: Principal, new_id: str, kind: str, event_id: str | None, html: str, csv_text: str | None) -> dict[str, Any]:
    tenant = principal.tenant_id or "platform"
    ref = _store(new_id, tenant, html, "html")
    pdf = render.html_to_pdf(html)
    if pdf:
        _store(new_id, tenant, pdf, "pdf")
    if csv_text is not None:
        _store(new_id, tenant, csv_text, "csv")
    row = tx.one(
        "INSERT INTO reports (id, tenant_id, kind, event_id, status, file_ref, created_by) VALUES (%s, %s, %s, %s, 'ready', %s, %s) "
        "RETURNING id, kind, event_id, status, created_at, file_ref",
        (new_id, principal.tenant_id, kind, event_id, ref, principal.user_id),
    )
    assert row is not None
    audit_action(tx, request, principal, "report.create", "report", new_id, {"kind": kind, "pdf": bool(pdf)})
    tx.commit()
    return _report(row)


@router.post("/reports/incident/{event_id}", summary="Create an incident report (HTML and PDF)", status_code=201)
def create_incident_report(
    event_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require("rules.manage")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    ratelimit.check(f"report:{principal.user_id or principal.api_key_id}", 20, 3600, detail="Too many reports. Try again later.")
    new_id = str(uuid.uuid4())
    content = reports.incident_html(tx, str(event_id), new_id, dt.datetime.now(dt.UTC))
    if content is None:
        raise not_found("Event")
    return _finish(tx, request, principal, new_id, "incident", str(event_id), content, None)


@router.post("/reports/portfolio", summary="Create a portfolio exposure report (HTML, PDF, and CSV)", status_code=201)
def create_portfolio_report(
    request: Request, principal: Principal = Depends(require("rules.manage")), tx: Tx = Depends(get_tx)
) -> dict[str, Any]:
    ratelimit.check(f"report:{principal.user_id or principal.api_key_id}", 20, 3600, detail="Too many reports. Try again later.")
    new_id = str(uuid.uuid4())
    html = reports.portfolio_html(tx, new_id, dt.datetime.now(dt.UTC))
    return _finish(tx, request, principal, new_id, "portfolio", None, html, reports.portfolio_csv(tx))


@router.get("/reports", summary="List reports")
def list_reports(
    limit: int = Query(default=20, ge=1, le=100), principal: Principal = Depends(require("rules.manage")), tx: Tx = Depends(get_tx)
) -> dict[str, Any]:
    return {"items": [_report(r) for r in tx.all(REPORT_SQL + " ORDER BY created_at DESC LIMIT %s", (limit,))]}


@router.get("/reports/{report_id}", summary="A report: metadata, or a file with format=html, pdf, or csv")
def get_report(
    report_id: uuid.UUID,
    format: str = Query(default="meta", pattern="^(meta|html|pdf|csv)$"),
    principal: Principal = Depends(require("rules.manage")),
    tx: Tx = Depends(get_tx),
) -> Any:
    row = tx.one(REPORT_SQL + " WHERE id = %s", (str(report_id),))
    if row is None:
        raise not_found("Report")
    if format == "meta":
        return _report(row)
    root = (get_settings().data_dir / "processed" / "reports").resolve()
    file = (root / (row[5] or "").rsplit(".", 1)[0]).with_suffix("." + format).resolve()
    if not file.is_file() or root not in file.parents:
        raise not_found("Report file")
    headers = _FILE_HEADERS | {"Content-Disposition": f'attachment; filename="report-{str(report_id)[:8]}.{format}"'}
    data = file.read_bytes()
    return Response(data, media_type=FORMATS[format], headers=headers)
