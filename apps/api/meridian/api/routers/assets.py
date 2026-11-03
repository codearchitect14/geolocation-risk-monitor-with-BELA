"""Assets, asset groups, and file uploads."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Header, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field

from meridian.api.auth import Principal, audit_action, get_tx, require
from meridian.api.db import Tx
from meridian.api.errors import ProblemError
from meridian.api.pagination import clamp_limit, decode_cursor, encode_cursor, page
from meridian.api.routers.common import ASSET_COLUMNS, asset_view, dumps, feature_collection, not_found
from meridian.api.services import uploads as up
from meridian.api.settings import get_api_settings

router = APIRouter(tags=["assets"])


class AssetBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: Literal["site", "route", "region"] = "site"
    geometry: dict[str, Any]
    criticality: int = Field(default=3, ge=1, le=5)
    country_code: str | None = Field(default=None, pattern="^[A-Za-z]{2}$")
    tags: list[str] = Field(default_factory=list, max_length=10)
    external_id: str | None = Field(default=None, max_length=100)
    maintenance_windows: list[dict[str, str]] = Field(default_factory=list, max_length=20)

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "Rotterdam terminal (illustrative)",
                "type": "site",
                "geometry": {"type": "Point", "coordinates": [4.4, 51.95]},
                "criticality": 4,
            }
        }
    }


class AssetPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    geometry: dict[str, Any] | None = None
    criticality: int | None = Field(default=None, ge=1, le=5)
    country_code: str | None = Field(default=None, pattern="^[A-Za-z]{2}$")
    tags: list[str] | None = Field(default=None, max_length=10)
    status: Literal["active", "archived"] | None = None
    maintenance_windows: list[dict[str, str]] | None = Field(default=None, max_length=20)


class GroupBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    asset_ids: list[uuid.UUID] = Field(default_factory=list, max_length=5000)


def _validated_geometry(geometry: dict[str, Any], asset_type: str | None = None) -> dict[str, Any]:
    problem = up._check_geometry(geometry, get_api_settings().max_vertices)
    if problem:
        raise ProblemError(422, problem[0].upper() + problem[1:] + ".", code="invalid-geometry")
    if asset_type and up.GEOMETRY_TYPES[geometry["type"]] != asset_type:
        raise ProblemError(422, f"A {asset_type} needs a matching geometry type.", code="invalid-geometry")
    return {"type": geometry["type"], "coordinates": geometry["coordinates"]}


def _windows(value: list[dict[str, str]]) -> list[dict[str, str]]:
    cleaned = []
    for w in value:
        if not isinstance(w, dict) or set(w) - {"start", "end", "reason"} or "start" not in w or "end" not in w:
            raise ProblemError(422, "Maintenance windows need start and end timestamps.", code="invalid-window")
        cleaned.append({k: str(v)[:80] for k, v in w.items()})
    return cleaned


@router.get("/assets", summary="List assets")
def list_assets(
    request: Request,
    q: str | None = Query(default=None, max_length=100),
    type: str | None = Query(default=None, pattern="^(site|route|region)$"),
    bbox: str | None = Query(default=None, description="min_lon,min_lat,max_lon,max_lat"),
    status: str = Query(default="active", pattern="^(active|archived)$"),
    format: str = Query(default="json", pattern="^(json|geojson)$"),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    principal: Principal = Depends(require("view")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    where: list[str] = ["status = %s"]
    params: list[Any] = [status]
    if q:
        where.append("name ILIKE %s")
        params.append("%" + q.replace("%", "").replace("_", "") + "%")
    if type:
        where.append("type = %s")
        params.append(type)
    if bbox:
        try:
            x0, y0, x1, y1 = (float(v) for v in bbox.split(","))
        except ValueError as exc:
            raise ProblemError(422, "bbox needs four numbers.", code="invalid-bbox") from exc
        where.append("geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)")
        params += [x0, y0, x1, y1]
    after = decode_cursor(cursor, 2)
    if after:
        where.append("(created_at, id) < (%s::timestamptz, %s::uuid)")
        params += after
    rows = tx.all(
        f"SELECT {ASSET_COLUMNS} FROM assets WHERE {' AND '.join(where)} ORDER BY created_at DESC, id DESC LIMIT %s",
        [*params, clamp_limit(limit) + 1],
    )  # noqa: S608
    result = page(
        [asset_view(r) for r in rows], clamp_limit(limit), lambda i: encode_cursor(i["created_at"].isoformat(), i["id"])
    )
    if format == "geojson":
        return {**feature_collection(result["items"]), "next_cursor": result["next_cursor"]}
    return result


@router.post("/assets", summary="Create an asset", status_code=201)
def create_asset(
    body: AssetBody, request: Request, principal: Principal = Depends(require("assets.write")), tx: Tx = Depends(get_tx)
) -> dict[str, Any]:
    geometry = _validated_geometry(body.geometry, body.type)
    try:
        row = tx.one(
            f"""INSERT INTO assets (tenant_id, name, type, geom, criticality, country_code, tags, external_id, maintenance_windows)
                VALUES (%s, %s, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), %s, %s, %s, %s, %s) RETURNING {ASSET_COLUMNS}""",  # noqa: S608
            (
                principal.tenant_id,
                up.clean_text(body.name),
                body.type,
                json.dumps(geometry),
                body.criticality,
                body.country_code.upper() if body.country_code else None,
                [up.clean_text(t, 40) for t in body.tags],
                body.external_id,
                dumps(_windows(body.maintenance_windows)),
            ),
        )
    except Exception as exc:
        tx.rollback()
        if "assets_external_ix" in str(exc):
            raise ProblemError(409, "An asset with this external_id already exists.", code="duplicate") from exc
        raise
    assert row is not None
    audit_action(tx, request, principal, "asset.create", "asset", row[0], {"type": body.type})
    tx.commit()
    return asset_view(row)


def _get_asset(tx: Tx, asset_id: uuid.UUID) -> tuple[Any, ...]:
    row = tx.one(f"SELECT {ASSET_COLUMNS} FROM assets WHERE id = %s", (str(asset_id),))  # noqa: S608
    if row is None:
        raise not_found("Asset")
    return row


@router.get("/assets/{asset_id}", summary="One asset")
def get_asset(
    asset_id: uuid.UUID, principal: Principal = Depends(require("view")), tx: Tx = Depends(get_tx)
) -> dict[str, Any]:
    return asset_view(_get_asset(tx, asset_id))


@router.patch("/assets/{asset_id}", summary="Update an asset")
def patch_asset(
    asset_id: uuid.UUID,
    body: AssetPatch,
    request: Request,
    principal: Principal = Depends(require("assets.write")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    current = _get_asset(tx, asset_id)
    sets: list[str] = []
    params: list[Any] = []
    data = body.model_dump(exclude_unset=True)
    if "geometry" in data and data["geometry"] is not None:
        sets.append("geom = ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)")
        params.append(json.dumps(_validated_geometry(data["geometry"], current[2])))
    for column in ("name", "criticality", "status"):
        if data.get(column) is not None:
            sets.append(f"{column} = %s")
            params.append(up.clean_text(data[column]) if column == "name" else data[column])
    if data.get("country_code") is not None:
        sets.append("country_code = %s")
        params.append(data["country_code"].upper())
    if data.get("tags") is not None:
        sets.append("tags = %s")
        params.append([up.clean_text(t, 40) for t in data["tags"]])
    if data.get("maintenance_windows") is not None:
        sets.append("maintenance_windows = %s")
        params.append(dumps(_windows(data["maintenance_windows"])))
    if not sets:
        return asset_view(current)
    row = tx.one(
        f"UPDATE assets SET {', '.join(sets)}, updated_at = now() WHERE id = %s RETURNING {ASSET_COLUMNS}",
        [*params, str(asset_id)],
    )  # noqa: S608
    assert row is not None
    audit_action(tx, request, principal, "asset.update", "asset", asset_id, {"fields": sorted(data)})
    tx.commit()
    return asset_view(row)


@router.delete("/assets/{asset_id}", summary="Delete an asset", status_code=204)
def delete_asset(
    asset_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require("assets.write")),
    tx: Tx = Depends(get_tx),
) -> Response:
    _get_asset(tx, asset_id)
    tx.execute("DELETE FROM assets WHERE id = %s", (str(asset_id),))
    audit_action(tx, request, principal, "asset.delete", "asset", asset_id)
    tx.commit()
    return Response(status_code=204)


def _exposure_view(r: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "event_id": str(r[0]), "title": r[1], "type": r[2], "subtype": r[3], "severity": r[4], "event_status": r[5],
        "confirmation": r[6], "last_seen_at": r[7], "distance_km": round(float(r[8]), 2), "within_uncertainty": r[9],
        "score": round(float(r[10]), 4), "level": r[11], "components": r[12], "computed_at": r[13],
    }  # fmt: skip


EXPOSURE_SQL = """SELECT e.id, e.title, e.type, e.subtype, e.severity, e.status, e.confirmation, e.last_seen_at, x.distance_km, x.within_uncertainty,
                         x.score, x.level, x.components, x.computed_at
                    FROM exposures x JOIN events e ON e.id = x.event_id WHERE x.asset_id = %s"""


@router.get(
    "/assets/{asset_id}/exposure", summary="Exposure of one asset to current events, with every score component"
)
def asset_exposure(
    asset_id: uuid.UUID, principal: Principal = Depends(require("view")), tx: Tx = Depends(get_tx)
) -> dict[str, Any]:
    asset = asset_view(_get_asset(tx, asset_id))
    rows = tx.all(EXPOSURE_SQL + " ORDER BY x.score DESC LIMIT 100", (str(asset_id),))
    return {"asset": asset, "exposures": [_exposure_view(r) for r in rows]}


@router.get("/assets/{asset_id}/events", summary="Events that affect one asset")
def asset_events(
    asset_id: uuid.UUID,
    status: str | None = Query(default=None, pattern="^(new|developing|ongoing|resolved)$"),
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(require("view")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    _get_asset(tx, asset_id)
    sql = EXPOSURE_SQL + (" AND e.status = %s" if status else "") + " ORDER BY e.last_seen_at DESC LIMIT %s"
    params = [str(asset_id), *([status] if status else []), limit]
    return {"items": [_exposure_view(r) for r in tx.all(sql, params)]}


# -- groups ---------------------------------------------------------------------------------------------------------
@router.get("/asset-groups", summary="List asset groups")
def list_groups(principal: Principal = Depends(require("view")), tx: Tx = Depends(get_tx)) -> dict[str, Any]:
    rows = tx.all(
        "SELECT g.id, g.name, (SELECT count(*) FROM asset_group_members m WHERE m.group_id = g.id) FROM asset_groups g ORDER BY g.name"
    )
    return {"items": [{"id": str(r[0]), "name": r[1], "asset_count": r[2]} for r in rows]}


@router.post("/asset-groups", summary="Create an asset group", status_code=201)
def create_group(
    body: GroupBody, request: Request, principal: Principal = Depends(require("assets.write")), tx: Tx = Depends(get_tx)
) -> dict[str, Any]:
    row = tx.one(
        "INSERT INTO asset_groups (tenant_id, name) VALUES (%s, %s) RETURNING id",
        (principal.tenant_id, up.clean_text(body.name, 100)),
    )
    assert row is not None
    added = 0
    for asset_id in body.asset_ids:
        added += tx.execute(
            "INSERT INTO asset_group_members (group_id, asset_id) SELECT %s, id FROM assets WHERE id = %s ON CONFLICT DO NOTHING",
            (row[0], str(asset_id)),
        ).rowcount
    audit_action(tx, request, principal, "asset_group.create", "asset_group", row[0], {"members": added})
    tx.commit()
    return {"id": str(row[0]), "name": body.name, "asset_count": added}


# -- uploads --------------------------------------------------------------------------------------------------------
@router.post("/uploads", summary="Upload assets as CSV or GeoJSON", status_code=201)
async def upload_assets(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    idempotency_key: str | None = Header(default=None, max_length=100, pattern="^[A-Za-z0-9._:-]+$"),
    principal: Principal = Depends(require("assets.write")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    settings = get_api_settings()
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise ProblemError(413, "The file is larger than the allowed size.", code="too-large")
    if not data:
        raise ProblemError(422, "The file is empty.", code="invalid-upload")
    digest = hashlib.sha256(data).hexdigest()
    if idempotency_key:
        prior = tx.one(
            "SELECT request_hash, response, status_code FROM idempotency_keys WHERE scope = 'upload' AND key = %s",
            (idempotency_key,),
        )
        if prior:
            if prior[0] != digest:
                raise ProblemError(
                    422, "This idempotency key was used with a different file.", code="idempotency-mismatch"
                )
            response.headers["Idempotent-Replay"] = "true"
            response.status_code = prior[2]
            return prior[1]  # type: ignore[no-any-return]
    text = up.decode(data)
    kind = up.sniff_kind(file.filename or "", (file.content_type or "").lower(), text)
    parsed = (up.parse_csv if kind == "csv" else up.parse_geojson)(
        text, settings.max_upload_rows, settings.max_vertices
    )
    upload = tx.one(
        "INSERT INTO uploads (tenant_id, filename, kind, size_bytes, created_by) VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (principal.tenant_id, up.clean_text(file.filename or "upload", 200), kind, len(data), principal.user_id),
    )
    assert upload is not None
    accepted = 0
    for item in parsed.assets:
        tx.execute(
            """INSERT INTO assets (tenant_id, name, type, geom, criticality, country_code, tags, external_id, source_upload_id)
               VALUES (%s, %s, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), %s, %s, %s, %s, %s)
               ON CONFLICT (tenant_id, external_id) WHERE external_id IS NOT NULL
               DO UPDATE SET name = EXCLUDED.name, geom = EXCLUDED.geom, criticality = EXCLUDED.criticality, tags = EXCLUDED.tags,
                             country_code = EXCLUDED.country_code, source_upload_id = EXCLUDED.source_upload_id, updated_at = now()""",
            (
                principal.tenant_id,
                item.name,
                item.type,
                json.dumps(item.geometry),
                item.criticality,
                item.country_code,
                item.tags,
                item.external_id,
                upload[0],
            ),
        )
        accepted += 1
    rejected = len(parsed.errors)
    status = "processed" if rejected == 0 else ("partial" if accepted else "failed")
    result = {
        "id": str(upload[0]),
        "kind": kind,
        "status": status,
        "rows_total": parsed.rows_total,
        "rows_accepted": accepted,
        "rows_rejected": rejected,
        "errors": parsed.errors[:100],
    }
    tx.execute(
        "UPDATE uploads SET status = %s, rows_total = %s, rows_accepted = %s, rows_rejected = %s, errors = %s WHERE id = %s",
        (status, parsed.rows_total, accepted, rejected, dumps(parsed.errors[:100]), upload[0]),
    )
    if idempotency_key:
        tx.execute(
            "INSERT INTO idempotency_keys (tenant_id, scope, key, request_hash, response, status_code) VALUES (%s, 'upload', %s, %s, %s, 201)",
            (principal.tenant_id, idempotency_key, digest, dumps(result)),
        )
    audit_action(
        tx,
        request,
        principal,
        "asset.upload",
        "upload",
        upload[0],
        {"kind": kind, "accepted": accepted, "rejected": rejected},
    )
    tx.commit()
    return result


@router.get("/uploads/{upload_id}", summary="One upload and its row errors")
def get_upload(
    upload_id: uuid.UUID, principal: Principal = Depends(require("view")), tx: Tx = Depends(get_tx)
) -> dict[str, Any]:
    r = tx.one(
        "SELECT id, filename, kind, status, size_bytes, rows_total, rows_accepted, rows_rejected, errors, created_at FROM uploads WHERE id = %s",
        (str(upload_id),),
    )
    if r is None:
        raise not_found("Upload")
    return {
        "id": str(r[0]),
        "filename": r[1],
        "kind": r[2],
        "status": r[3],
        "size_bytes": r[4],
        "rows_total": r[5],
        "rows_accepted": r[6],
        "rows_rejected": r[7],
        "errors": r[8],
        "created_at": r[9],
    }


@router.get("/assets-export", summary="Export assets as CSV (formula safe)")
def export_assets(principal: Principal = Depends(require("view")), tx: Tx = Depends(get_tx)) -> Response:
    import csv
    import io

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["name", "type", "criticality", "country_code", "external_id", "lat", "lon"])
    for r in tx.all(
        "SELECT name, type, criticality, country_code, external_id, ST_Y(ST_PointOnSurface(geom)), ST_X(ST_PointOnSurface(geom)) FROM assets WHERE status = 'active' ORDER BY name LIMIT 10000"
    ):
        writer.writerow(
            [up.csv_safe(r[0]), r[1], r[2], r[3] or "", up.csv_safe(r[4] or ""), round(r[5], 6), round(r[6], 6)]
        )
    return Response(
        out.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="assets.csv"'}
    )
