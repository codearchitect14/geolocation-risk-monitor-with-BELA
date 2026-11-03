"""Helpers shared by routers."""

from __future__ import annotations

import json
from typing import Any

from meridian.api.errors import ProblemError

ASSET_COLUMNS = "id, name, type, ST_AsGeoJSON(geom)::json, criticality, country_code, tags, status, external_id, maintenance_windows, created_at"
EVENT_TYPES = (
    "industrial_accident", "natural_hazard", "transport_disruption", "labor_action", "civil_unrest", "security_incident",
    "infrastructure_outage", "health_outbreak", "other",
)  # fmt: skip
LEVELS = ("low", "medium", "high", "critical")


def not_found(what: str) -> ProblemError:
    return ProblemError(404, f"{what} not found.", code="not-found")


def asset_view(r: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": str(r[0]), "name": r[1], "type": r[2], "geometry": r[3], "criticality": r[4], "country_code": r[5],
        "tags": r[6], "status": r[7], "external_id": r[8], "maintenance_windows": r[9], "created_at": r[10],
    }  # fmt: skip


def feature_collection(items: list[dict[str, Any]], geometry_key: str = "geometry") -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": i["id"],
                "geometry": i[geometry_key],
                "properties": {k: v for k, v in i.items() if k != geometry_key},
            }
            for i in items
        ],
    }


def dumps(value: Any) -> str:
    return json.dumps(value, default=str)
