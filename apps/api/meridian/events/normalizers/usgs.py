"""USGS earthquake GeoJSON features to normalized events."""

from __future__ import annotations

import datetime as dt
from typing import Any

from meridian.events.config import EventsConfig
from meridian.events.types import NormalizedEvent


def magnitude_severity(magnitude: float, depth_km: float | None, pager: str | None, cfg: EventsConfig) -> int:
    rules = cfg.raw["hazard_feeds"]["usgs"]
    severity = 1
    for row in rules["magnitude_classes"]:
        if magnitude >= row["min"]:
            severity = int(row["severity"])
    if depth_km is not None and depth_km > rules["deep_km"]:
        severity = max(1, severity - 1)
    if pager:
        severity = max(severity, int(rules["pager_alert_severity"].get(pager.lower(), 1)))
    return min(severity, 4)


def normalize(feature: dict[str, Any], cfg: EventsConfig) -> NormalizedEvent | None:
    props = feature.get("properties") or {}
    coords = (feature.get("geometry") or {}).get("coordinates") or []
    magnitude = props.get("mag")
    if len(coords) < 2 or not isinstance(magnitude, int | float) or props.get("type") not in (None, "earthquake"):
        return None
    occurred = dt.datetime.fromtimestamp(props["time"] / 1000, dt.UTC)
    updated = dt.datetime.fromtimestamp(props["updated"] / 1000, dt.UTC) if props.get("updated") else occurred
    depth = float(coords[2]) if len(coords) > 2 else None
    severity = magnitude_severity(float(magnitude), depth, props.get("alert"), cfg)
    return NormalizedEvent(
        source_kind="usgs",
        source_ref=str(feature["id"]),
        type="natural_hazard",
        subtype="earthquake",
        severity=severity,
        title=props.get("title") or f"M {magnitude} earthquake",
        geometry={"type": "Point", "coordinates": [float(coords[0]), float(coords[1])]},
        location_level="natural",
        uncertainty_km=float(cfg.raw["hazard_feeds"]["usgs"]["uncertainty_km"]),
        occurred_at=occurred,
        published_at=updated,
        updated_at=updated,
        url=props.get("url"),
        summary=f"Magnitude {magnitude} earthquake, {props.get('place') or 'location not given'}, depth {depth} km.",
        details={
            "magnitude": float(magnitude),
            "depth_km": depth,
            "place": props.get("place"),
            "pager_alert": props.get("alert"),
            "tsunami": bool(props.get("tsunami")),
            "review_status": props.get("status"),
            "felt": props.get("felt"),
        },
    )
