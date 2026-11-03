"""Guided asset upload: template, column mapping, place resolution, review, commit, and result export.

This router is included before the assets router so that /uploads/template is not read as an upload id.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field

from meridian.api.auth import Principal, audit_action, get_tx, require
from meridian.api.db import Tx
from meridian.api.errors import ProblemError
from meridian.api.routers.common import dumps, not_found
from meridian.api.services import staging
from meridian.api.services import uploads as up
from meridian.api.settings import get_api_settings

router = APIRouter(tags=["assets"])
PREVIEW_ROWS = 200


@router.get("/uploads/template", summary="Download an asset upload template")
def template(
    format: str = Query(default="csv", pattern="^(csv|geojson)$"), principal: Principal = Depends(require("view"))
) -> Response:
    if format == "csv":
        return Response(
            staging.TEMPLATE_CSV,
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="assets-template.csv"'},
        )
    return Response(
        json.dumps(staging.TEMPLATE_GEOJSON, indent=2),
        media_type="application/geo+json",
        headers={"Content-Disposition": 'attachment; filename="assets-template.geojson"'},
    )


def _load(tx: Tx, upload_id: uuid.UUID) -> tuple[Any, ...]:
    row = tx.one(
        "SELECT id, filename, kind, status, mapping, staged, rows_total, size_bytes, created_at FROM uploads WHERE id = %s",
        (str(upload_id),),
    )
    if row is None:
        raise not_found("Upload")
    return row


def _staged_view(row: tuple[Any, ...], limit: int = PREVIEW_ROWS) -> dict[str, Any]:
    rows: list[dict[str, Any]] = row[5]
    return {
        "id": str(row[0]),
        "filename": row[1],
        "kind": row[2],
        "status": row[3],
        "mapping": row[4],
        "rows_total": row[6],
        "summary": staging.summary(rows),
        "rows": rows[:limit],
        "preview": staging.preview_features(rows),
        "created_at": row[8],
    }


@router.post("/uploads/stage", summary="Upload a file for review before any asset is created", status_code=201)
async def stage_upload(
    request: Request,
    file: UploadFile = File(...),
    mapping: str | None = Form(default=None, max_length=2000, description='JSON such as {"name": "Site", "city": "Town"}'),
    principal: Principal = Depends(require("assets.write")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    settings = get_api_settings()
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise ProblemError(413, "The file is larger than the allowed size.", code="too-large")
    if not data:
        raise ProblemError(422, "The file is empty.", code="invalid-upload")
    text = up.decode(data)
    kind = up.sniff_kind(file.filename or "", (file.content_type or "").lower(), text)
    chosen: dict[str, Any] | None = None
    if mapping:
        try:
            chosen = json.loads(mapping)
        except json.JSONDecodeError as exc:
            raise ProblemError(422, "The column mapping is not valid JSON.", code="invalid-mapping") from exc
        if not isinstance(chosen, dict):
            raise ProblemError(422, "The column mapping must be an object.", code="invalid-mapping")
    if kind == "csv":
        staged = staging.stage_csv(text, chosen, tx.conn, settings.max_upload_rows)
    else:
        staged = staging.stage_geojson(text, settings.max_upload_rows, settings.max_vertices)
    row = tx.one(
        """INSERT INTO uploads (tenant_id, filename, kind, status, size_bytes, rows_total, mapping, staged, created_by)
           VALUES (%s, %s, %s, 'staged', %s, %s, %s, %s, %s)
           RETURNING id, filename, kind, status, mapping, staged, rows_total, size_bytes, created_at""",
        (
            principal.tenant_id,
            up.clean_text(file.filename or "upload", 200),
            kind,
            len(data),
            staged.rows_total,
            dumps(staged.mapping),
            dumps(staged.rows),
            principal.user_id,
        ),
    )
    assert row is not None
    audit_action(
        tx,
        request,
        principal,
        "asset.upload_stage",
        "upload",
        row[0],
        {"kind": kind, "digest": hashlib.sha256(data).hexdigest()[:16]},
    )
    tx.commit()
    view = _staged_view(row)
    view["headers"] = staged.headers
    return view


@router.get("/uploads/{upload_id}/rows", summary="Rows of a staged upload, optionally only those needing review")
def staged_rows(
    upload_id: uuid.UUID,
    status: str | None = Query(default=None, pattern="^(ready|review|duplicate|error)$"),
    offset: int = Query(default=0, ge=0, le=100000),
    limit: int = Query(default=100, ge=1, le=500),
    principal: Principal = Depends(require("view")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = _load(tx, upload_id)[5]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return {"items": rows[offset : offset + limit], "total": len(rows), "next_offset": offset + limit if offset + limit < len(rows) else None}


class Choice(BaseModel):
    row: int = Field(ge=1)
    place_id: int


class CommitBody(BaseModel):
    choices: list[Choice] = Field(default_factory=list, max_length=10000)
    skip_rows: list[int] = Field(default_factory=list, max_length=10000)

    model_config = {
        "json_schema_extra": {"example": {"choices": [{"row": 3, "place_id": 12345}], "skip_rows": [7]}}
    }


@router.post("/uploads/{upload_id}/commit", summary="Create assets from a staged upload")
def commit_upload(
    upload_id: uuid.UUID,
    body: CommitBody,
    request: Request,
    principal: Principal = Depends(require("assets.write")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    current = tx.one("SELECT status, staged FROM uploads WHERE id = %s FOR UPDATE", (str(upload_id),))
    if current is None:
        raise not_found("Upload")
    if current[0] != "staged":
        raise ProblemError(409, "This upload was already committed or cancelled.", code="not-staged")
    rows: list[dict[str, Any]] = current[1]
    by_number = {r["row"]: r for r in rows}
    picks = {c.row: c.place_id for c in body.choices}
    skipped = set(body.skip_rows)
    for number, place_id in picks.items():
        row = by_number.get(number)
        if row is None or row["status"] != "review" or not staging.choose(row, place_id):
            raise ProblemError(422, f"Row {number} cannot take that place.", code="invalid-choice")
    created = updated = 0
    for row in rows:
        if row["row"] in skipped:
            row["outcome"] = "skipped"
            continue
        if row["status"] != "ready":
            row["outcome"] = {"review": "not_reviewed", "duplicate": "duplicate", "error": "rejected"}[row["status"]]
            continue
        geometry = row["geometry"]
        place = row.get("place")
        existing = (
            tx.one("SELECT 1 FROM assets WHERE tenant_id = %s AND external_id = %s", (principal.tenant_id, row["external_id"]))
            if row.get("external_id")
            else None
        )
        tx.execute(
            """INSERT INTO assets (tenant_id, name, type, geom, criticality, country_code, tags, external_id, source_upload_id,
                                   location_source, location_uncertainty_km, place_id)
               VALUES (%s, %s, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (tenant_id, external_id) WHERE external_id IS NOT NULL
               DO UPDATE SET name = EXCLUDED.name, geom = EXCLUDED.geom, criticality = EXCLUDED.criticality, tags = EXCLUDED.tags,
                             country_code = EXCLUDED.country_code, source_upload_id = EXCLUDED.source_upload_id,
                             location_source = EXCLUDED.location_source, location_uncertainty_km = EXCLUDED.location_uncertainty_km,
                             place_id = EXCLUDED.place_id, updated_at = now()""",
            (
                principal.tenant_id,
                row["name"],
                staging.geometry_type_for(geometry),
                json.dumps(geometry),
                row["criticality"],
                row.get("country_code"),
                row["tags"],
                row.get("external_id"),
                str(upload_id),
                "place" if place else "provided",
                place["uncertainty_km"] if place else None,
                place["place_id"] if place else None,
            ),
        )
        row["outcome"] = "updated" if existing else "created"
        updated += 1 if existing else 0
        created += 0 if existing else 1
    accepted = created + updated
    rejected = sum(1 for r in rows if r.get("outcome") in {"rejected", "duplicate"})
    status = "failed" if accepted == 0 else ("processed" if accepted == len(rows) else "partial")
    errors = [{"row": r["row"], "message": r["message"] or r["outcome"]} for r in rows if r.get("outcome") != "created" and r.get("outcome") != "updated"][:100]
    tx.execute(
        """UPDATE uploads SET status = %s, staged = %s, rows_accepted = %s, rows_rejected = %s, errors = %s, committed_at = now()
            WHERE id = %s""",
        (status, dumps(rows), accepted, rejected, dumps(errors), str(upload_id)),
    )
    audit_action(
        tx, request, principal, "asset.upload_commit", "upload", upload_id, {"created": created, "updated": updated}
    )
    tx.commit()
    return {
        "id": str(upload_id),
        "status": status,
        "created": created,
        "updated": updated,
        "skipped": sum(1 for r in rows if r.get("outcome") in {"skipped", "not_reviewed"}),
        "rejected": rejected,
        "summary": staging.summary(rows),
    }


@router.post("/uploads/{upload_id}/cancel", summary="Discard a staged upload")
def cancel_upload(
    upload_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require("assets.write")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    row = tx.one(
        "UPDATE uploads SET status = 'cancelled', staged = '[]' WHERE id = %s AND status = 'staged' RETURNING id", (str(upload_id),)
    )
    if row is None:
        if tx.one("SELECT 1 FROM uploads WHERE id = %s", (str(upload_id),)) is None:
            raise not_found("Upload")
        raise ProblemError(409, "This upload is not waiting for review.", code="not-staged")
    audit_action(tx, request, principal, "asset.upload_cancel", "upload", upload_id)
    tx.commit()
    return {"id": str(upload_id), "status": "cancelled"}


@router.get("/uploads/{upload_id}/result", summary="Per row outcome of an upload as CSV (formula safe)")
def upload_result(
    upload_id: uuid.UUID, principal: Principal = Depends(require("view")), tx: Tx = Depends(get_tx)
) -> Response:
    rows: list[dict[str, Any]] = _load(tx, upload_id)[5]
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["row", "name", "status", "outcome", "message", "place", "lat", "lon"])
    for r in rows:
        geometry = r.get("geometry") or {}
        coords = geometry.get("coordinates") if geometry.get("type") == "Point" else None
        writer.writerow(
            [
                r["row"],
                up.csv_safe(r.get("name", "")),
                r["status"],
                r.get("outcome", ""),
                up.csv_safe(r.get("message") or ""),
                up.csv_safe((r.get("place") or {}).get("name", "")),
                coords[1] if coords else "",
                coords[0] if coords else "",
            ]
        )
    return Response(
        out.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="upload-result.csv"'}
    )
