"""NASA FIRMS fire detections to fire events: cluster detections, then classify each cluster."""

from __future__ import annotations

import csv
import datetime as dt
import io
import math
from collections.abc import Callable
from typing import Any

import h3
import numpy as np
from shapely.geometry import MultiPoint, mapping
from sklearn.cluster import DBSCAN

from meridian.events.config import EventsConfig
from meridian.events.types import NormalizedEvent

EARTH_RADIUS_KM = 6371.0088


def parse_rows(text: str) -> list[dict[str, Any]]:
    rows = []
    for record in csv.DictReader(io.StringIO(text)):
        try:
            hhmm = (record.get("acq_time") or "0000").zfill(4)
            when = dt.datetime.strptime(f"{record['acq_date']} {hhmm}", "%Y-%m-%d %H%M").replace(tzinfo=dt.UTC)
            lat, lon = float(record["latitude"]), float(record["longitude"])
        except (KeyError, ValueError):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        rows.append(
            {
                "lat": lat,
                "lon": lon,
                "time": when,
                "frp": float(record.get("frp") or 0.0),
                "confidence": record.get("confidence"),
                "satellite": record.get("satellite"),
            }
        )
    return rows


def severity_for(detections: int, frp: float, cfg: EventsConfig) -> int:
    """The highest class whose detection count or total radiative power is reached."""
    severity = 1
    for row in cfg.raw["hazard_feeds"]["firms"]["classes"]:
        if row["min_detections"] > 0 and (detections >= row["min_detections"] or frp >= row["min_frp"]):
            severity = max(severity, int(row["severity"]))
    return severity


def cluster_events(
    rows: list[dict[str, Any]],
    cfg: EventsConfig,
    near_assets: Callable[[float, float, float], bool] | None = None,
) -> list[NormalizedEvent]:
    rules = cfg.raw["hazard_feeds"]["firms"]
    if not rows:
        return []
    newest = max(r["time"] for r in rows)
    window = [r for r in rows if newest - r["time"] <= dt.timedelta(hours=rules["window_hours"])]
    if len(window) < rules["dbscan_min_samples"]:
        return []
    coordinates = np.radians([[r["lat"], r["lon"]] for r in window])
    labels = DBSCAN(
        eps=rules["dbscan_eps_km"] / EARTH_RADIUS_KM, min_samples=rules["dbscan_min_samples"], metric="haversine"
    ).fit_predict(coordinates)
    events: list[NormalizedEvent] = []
    for label in sorted(set(labels) - {-1}):
        members = [r for r, lab in zip(window, labels, strict=True) if lab == label]
        lats, lons = [m["lat"] for m in members], [m["lon"] for m in members]
        lat, lon = float(np.mean(lats)), float(np.mean(lons))
        frp = sum(m["frp"] for m in members)
        severity = severity_for(len(members), frp, cfg)
        near = near_assets(lat, lon, float(rules["create_when_near_assets_km"])) if near_assets else False
        if not (near or len(members) >= rules["create_when_detections_at_least"]):
            continue
        hull = MultiPoint([(m["lon"], m["lat"]) for m in members]).convex_hull
        radius_km = max(haversine(lat, lon, m["lat"], m["lon"]) for m in members) + float(rules["uncertainty_extra_km"])
        geometry = dict(mapping(hull.buffer(0.01)))
        first, last = min(m["time"] for m in members), max(m["time"] for m in members)
        cell = h3.latlng_to_cell(lat, lon, 6)
        events.append(
            NormalizedEvent(
                source_kind="firms",
                source_ref=f"{cell}:{first:%Y%m%d}",
                type="natural_hazard",
                subtype="wildfire",
                severity=severity,
                title=f"Active fire detections near {lat:.2f}, {lon:.2f}",
                geometry=geometry,
                location_level="natural",
                uncertainty_km=round(radius_km, 1),
                occurred_at=first,
                published_at=last,
                updated_at=last,
                summary=f"{len(members)} satellite fire detections, total radiative power {frp:.0f} MW.",
                details={
                    "detections": len(members),
                    "frp_total_mw": round(frp, 1),
                    "centroid": [lat, lon],
                    "satellites": sorted({str(m["satellite"]) for m in members}),
                },
            )
        )
    return events


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))
