"""Watch zones and alert rules."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field, field_validator

from meridian.api.auth import Principal, audit_action, get_tx, require
from meridian.api.db import Tx
from meridian.api.errors import ProblemError
from meridian.api.routers.assets import _validated_geometry
from meridian.api.routers.common import EVENT_TYPES, LEVELS, dumps, feature_collection, not_found
from meridian.api.services.uploads import clean_text

router = APIRouter(tags=["zones and rules"])
Level = Literal["low", "medium", "high", "critical"]
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class QuietHours(BaseModel):
    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def hhmm(cls, value: str) -> str:
        if not _HHMM.match(value):
            raise ValueError("use HH:MM in UTC")
        return value


class Escalation(BaseModel):
    after_minutes: int = Field(ge=5, le=10080, description="Escalate an alert still in status new after this long")


class ZoneRules(BaseModel):
    min_severity: int = Field(default=1, ge=1, le=4)
    min_level: Level = "medium"
    event_types: list[str] = Field(default_factory=list, max_length=20)
    quiet_hours: QuietHours | None = None

    @field_validator("event_types")
    @classmethod
    def known_types(cls, value: list[str]) -> list[str]:
        if any(t not in EVENT_TYPES for t in value):
            raise ValueError("unknown event type")
        return value


class Circle(BaseModel):
    center: list[float] = Field(min_length=2, max_length=2, description="[lon, lat]")
    radius_km: float = Field(gt=0, le=2000)


class ZoneBody(BaseModel):
    """Give exactly one of: a polygon, a circle (center and radius), or an administrative region from the place table."""

    name: str = Field(min_length=1, max_length=100)
    geometry: dict[str, Any] | None = None
    circle: Circle | None = None
    region_place_id: int | None = None
    rules: ZoneRules = Field(default_factory=ZoneRules)

    model_config = {
        "json_schema_extra": {
            "example": {"name": "Port approaches", "circle": {"center": [4.4, 51.95], "radius_km": 25}, "rules": {"min_level": "high"}}
        }
    }


class ZonePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    geometry: dict[str, Any] | None = None
    circle: Circle | None = None
    region_place_id: int | None = None
    rules: ZoneRules | None = None
    status: Literal["active", "archived"] | None = None


ZONE_SQL = "SELECT id, name, ST_AsGeoJSON(geom)::json, rules, status, created_at FROM watch_zones"


def _zone(r: tuple[Any, ...]) -> dict[str, Any]:
    return {"id": str(r[0]), "name": r[1], "geometry": r[2], "rules": r[3], "status": r[4], "created_at": r[5]}


def _polygon(geometry: dict[str, Any]) -> dict[str, Any]:
    if geometry.get("type") not in ("Polygon", "MultiPolygon"):
        raise ProblemError(422, "A watch zone must be a Polygon or MultiPolygon.", code="invalid-geometry")
    return _validated_geometry(geometry)


def _shape(tx: Tx, geometry: dict[str, Any] | None, circle: Circle | None, region: int | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """The polygon to store and a description of how it was made, so that an editor can reopen it as a circle or region."""
    given = [x for x in (geometry, circle, region) if x is not None]
    if len(given) != 1:
        raise ProblemError(422, "Give exactly one of geometry, circle, or region_place_id.", code="invalid-shape")
    if geometry is not None:
        return _polygon(geometry), {"kind": "polygon"}
    if circle is not None:
        lon, lat = circle.center
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ProblemError(422, "The circle center is outside the valid range.", code="invalid-shape")
        row = tx.one(
            "SELECT ST_AsGeoJSON(ST_Buffer(ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s, 24)::geometry)::json",
            (lon, lat, circle.radius_km * 1000),
        )
        assert row is not None
        return _polygon(row[0]), {"kind": "circle", "center": [lon, lat], "radius_km": circle.radius_km}
    row = tx.one(
        "SELECT name, has_polygon, ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, 0.01), 5)::json FROM places WHERE id = %s",
        (region,),
    )
    if row is None:
        raise ProblemError(404, "Place not found.", code="not-found")
    if not row[1] or row[2]["type"] not in ("Polygon", "MultiPolygon"):
        raise ProblemError(422, "This place has no boundary. Choose an administrative region.", code="no-boundary")
    return _polygon(row[2]), {"kind": "region", "place_id": region, "name": row[0]}


@router.get("/zones", summary="List watch zones")
def list_zones(
    format: str = Query(default="json", pattern="^(json|geojson)$"),
    principal: Principal = Depends(require("view")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    items = [_zone(r) for r in tx.all(ZONE_SQL + " WHERE status = 'active' ORDER BY created_at DESC LIMIT 500")]
    return feature_collection(items) if format == "geojson" else {"items": items}


@router.post("/zones", summary="Create a watch zone", status_code=201)
def create_zone(
    body: ZoneBody, request: Request, principal: Principal = Depends(require("alerts.act")), tx: Tx = Depends(get_tx)
) -> dict[str, Any]:
    geometry, origin = _shape(tx, body.geometry, body.circle, body.region_place_id)
    row = tx.one(
        "INSERT INTO watch_zones (tenant_id, name, geom, rules, created_by) VALUES (%s, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), %s, %s) RETURNING id, name, ST_AsGeoJSON(geom)::json, rules, status, created_at",
        (
            principal.tenant_id,
            clean_text(body.name, 100),
            json.dumps(geometry),
            dumps({**body.rules.model_dump(), "origin": origin}),
            principal.user_id,
        ),
    )
    assert row is not None
    audit_action(tx, request, principal, "zone.create", "zone", row[0])
    tx.commit()
    return _zone(row)


@router.get("/zones/{zone_id}", summary="One watch zone")
def get_zone(
    zone_id: uuid.UUID, principal: Principal = Depends(require("view")), tx: Tx = Depends(get_tx)
) -> dict[str, Any]:
    row = tx.one(ZONE_SQL + " WHERE id = %s", (str(zone_id),))
    if row is None:
        raise not_found("Zone")
    return _zone(row)


@router.patch("/zones/{zone_id}", summary="Update a watch zone")
def patch_zone(
    zone_id: uuid.UUID,
    body: ZonePatch,
    request: Request,
    principal: Principal = Depends(require("alerts.act")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    if tx.one("SELECT 1 FROM watch_zones WHERE id = %s", (str(zone_id),)) is None:
        raise not_found("Zone")
    data = body.model_dump(exclude_unset=True)
    sets: list[str] = []
    params: list[Any] = []
    if data.get("name"):
        sets.append("name = %s")
        params.append(clean_text(data["name"], 100))
    new_origin: dict[str, Any] | None = None
    if any(data.get(k) is not None for k in ("geometry", "circle", "region_place_id")):
        polygon, new_origin = _shape(tx, data.get("geometry"), body.circle, data.get("region_place_id"))
        sets.append("geom = ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)")
        params.append(json.dumps(polygon))
    if data.get("rules") is not None or new_origin is not None:
        previous = tx.one("SELECT rules FROM watch_zones WHERE id = %s", (str(zone_id),))
        merged = {**(previous[0] if previous else {}), **(body.rules.model_dump() if body.rules else {})}
        if new_origin is not None:
            merged["origin"] = new_origin
        sets.append("rules = %s")
        params.append(dumps(merged))
    if data.get("status"):
        sets.append("status = %s")
        params.append(data["status"])
    if sets:
        tx.execute(f"UPDATE watch_zones SET {', '.join(sets)} WHERE id = %s", [*params, str(zone_id)])  # noqa: S608
        audit_action(tx, request, principal, "zone.update", "zone", zone_id, {"fields": sorted(data)})
        tx.commit()
    row = tx.one(ZONE_SQL + " WHERE id = %s", (str(zone_id),))
    assert row is not None
    return _zone(row)


@router.delete("/zones/{zone_id}", summary="Delete a watch zone", status_code=204)
def delete_zone(
    zone_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require("alerts.act")),
    tx: Tx = Depends(get_tx),
) -> Response:
    if tx.execute("DELETE FROM watch_zones WHERE id = %s", (str(zone_id),)).rowcount == 0:
        raise not_found("Zone")
    audit_action(tx, request, principal, "zone.delete", "zone", zone_id)
    tx.commit()
    return Response(status_code=204)


# -- alert rules ----------------------------------------------------------------------------------------------------
class RuleBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    event_types: list[str] = Field(default_factory=list, max_length=20)
    min_severity: int = Field(default=1, ge=1, le=4)
    min_level: Level = "medium"
    asset_group_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    quiet_hours: QuietHours | None = None
    escalation: Escalation | None = None
    enabled: bool = True

    @field_validator("event_types")
    @classmethod
    def known_types(cls, value: list[str]) -> list[str]:
        if any(t not in EVENT_TYPES for t in value):
            raise ValueError("unknown event type")
        return value

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "High and critical industrial events",
                "event_types": ["industrial_accident"],
                "min_severity": 2,
                "min_level": "high",
            }
        }
    }


class RulePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    event_types: list[str] | None = Field(default=None, max_length=20)
    min_severity: int | None = Field(default=None, ge=1, le=4)
    min_level: Level | None = None
    asset_group_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)
    quiet_hours: QuietHours | None = None
    escalation: Escalation | None = None
    enabled: bool | None = None

    @field_validator("event_types")
    @classmethod
    def known_types(cls, value: list[str] | None) -> list[str] | None:
        if value and any(t not in EVENT_TYPES for t in value):
            raise ValueError("unknown event type")
        return value


RULE_SQL = "SELECT id, name, event_types, min_severity, min_level, asset_group_ids, quiet_hours, escalation, enabled, created_at FROM alert_rules"


def _rule(r: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": str(r[0]),
        "name": r[1],
        "event_types": r[2],
        "min_severity": r[3],
        "min_level": r[4],
        "asset_group_ids": [str(g) for g in r[5]],
        "quiet_hours": r[6] or None,
        "escalation": r[7],
        "enabled": r[8],
        "created_at": r[9],
    }


def _check_groups(tx: Tx, groups: list[uuid.UUID]) -> list[str]:
    ids = [str(g) for g in groups]
    if ids and tx.one("SELECT count(*) FROM asset_groups WHERE id = ANY(%s::uuid[])", (ids,))[0] != len(set(ids)):  # type: ignore[index]
        raise ProblemError(422, "An asset group does not exist.", code="invalid-group")
    return ids


@router.get("/rules", summary="List alert rules")
def list_rules(principal: Principal = Depends(require("view")), tx: Tx = Depends(get_tx)) -> dict[str, Any]:
    return {
        "items": [_rule(r) for r in tx.all(RULE_SQL + " ORDER BY created_at DESC LIMIT 200")],
        "default_when_none": {"min_level": "medium"},
    }


@router.post("/rules", summary="Create an alert rule", status_code=201)
def create_rule(
    body: RuleBody, request: Request, principal: Principal = Depends(require("rules.manage")), tx: Tx = Depends(get_tx)
) -> dict[str, Any]:
    groups = _check_groups(tx, body.asset_group_ids)
    row = tx.one(
        f"INSERT INTO alert_rules (tenant_id, name, event_types, min_severity, min_level, asset_group_ids, quiet_hours, escalation, enabled) VALUES (%s, %s, %s, %s, %s, %s::uuid[], %s, %s, %s) RETURNING {RULE_SQL[7 : RULE_SQL.index(' FROM')]}",  # noqa: S608
        (
            principal.tenant_id,
            clean_text(body.name, 100),
            body.event_types,
            body.min_severity,
            body.min_level,
            groups,
            dumps(body.quiet_hours.model_dump() if body.quiet_hours else {}),
            dumps({"after_minutes": body.escalation.after_minutes} if body.escalation else {}),
            body.enabled,
        ),
    )
    assert row is not None
    audit_action(tx, request, principal, "rule.create", "rule", row[0])
    tx.commit()
    return _rule(row)


@router.patch("/rules/{rule_id}", summary="Update an alert rule")
def patch_rule(
    rule_id: uuid.UUID,
    body: RulePatch,
    request: Request,
    principal: Principal = Depends(require("rules.manage")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    if tx.one("SELECT 1 FROM alert_rules WHERE id = %s", (str(rule_id),)) is None:
        raise not_found("Rule")
    data = body.model_dump(exclude_unset=True)
    sets: list[str] = []
    params: list[Any] = []
    for column in ("name", "event_types", "min_severity", "min_level", "enabled"):
        if column in data and data[column] is not None:
            sets.append(f"{column} = %s")
            params.append(clean_text(data[column], 100) if column == "name" else data[column])
    if data.get("asset_group_ids") is not None:
        sets.append("asset_group_ids = %s::uuid[]")
        params.append(_check_groups(tx, body.asset_group_ids or []))
    if "quiet_hours" in data:
        sets.append("quiet_hours = %s")
        params.append(dumps(data["quiet_hours"] or {}))
    if "escalation" in data:
        sets.append("escalation = %s")
        params.append(dumps(data["escalation"] or {}))
    if sets:
        tx.execute(f"UPDATE alert_rules SET {', '.join(sets)} WHERE id = %s", [*params, str(rule_id)])  # noqa: S608
        audit_action(tx, request, principal, "rule.update", "rule", rule_id, {"fields": sorted(data)})
        tx.commit()
    row = tx.one(RULE_SQL + " WHERE id = %s", (str(rule_id),))
    assert row is not None
    return _rule(row)


_ = LEVELS
