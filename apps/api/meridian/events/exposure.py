"""Exposure of tenant assets to events.

  proximity = 1                                    when the asset is inside the event's uncertainty region
            = exp(-(distance_km - uncertainty_km) / lambda_type)   otherwise
  exposure  = type_weight * severity_weight * proximity * location_confidence * source_reliability
              * recency_decay * criticality_factor            (clamped to 1)

Distance is measured with PostGIS geography functions, so polygon assets and polygon events (zero distance when they
intersect) and polyline assets (distance to the nearest point of the route) are handled by the database. Country-level
events are never matched against site assets. Every component is stored with the exposure so it can be shown.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from dataclasses import dataclass
from typing import Any

import psycopg

from meridian.events.config import EventsConfig


@dataclass
class EventRow:
    id: str
    type: str
    subtype: str | None
    severity: int
    geometry: str  # GeoJSON text
    uncertainty_km: float
    location_level: str | None
    location_confidence: float
    reliability: float
    last_seen_at: dt.datetime
    status: str
    magnitude: float | None


@dataclass
class Exposure:
    tenant_id: str
    event_id: str
    asset_id: str
    distance_km: float
    within_uncertainty: bool
    score: float
    level: str
    components: dict[str, Any]


def load_event(conn: psycopg.Connection[Any], event_id: str) -> EventRow:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, type, subtype, severity, ST_AsGeoJSON(geom), COALESCE(uncertainty_km, 0), location_level,
                      COALESCE(location_confidence, 0.5), COALESCE(reliability, 0.5), last_seen_at, status,
                      (details->>'magnitude')::float
                 FROM events WHERE id = %s""",
            (event_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise KeyError(event_id)
    return EventRow(
        str(row[0]),
        row[1],
        row[2],
        row[3],
        row[4],
        float(row[5]),
        row[6],
        float(row[7]),
        float(row[8]),
        row[9],
        row[10],
        row[11],
    )


def proximity(distance_km: float, uncertainty_km: float, inside: bool, lambda_km: float) -> tuple[float, bool]:
    """Proximity term and whether the asset lies within the uncertainty region."""
    if inside or distance_km <= uncertainty_km:
        return 1.0, True
    return math.exp(-(distance_km - uncertainty_km) / lambda_km), False


def recency_decay(last_seen: dt.datetime, now: dt.datetime, half_life_hours: float) -> float:
    age_hours = max((now - last_seen).total_seconds() / 3600.0, 0.0)
    return float(0.5 ** (age_hours / half_life_hours))


def score_pair(
    cfg: EventsConfig, event: EventRow, criticality: int, distance_km: float, inside: bool, now: dt.datetime
) -> tuple[float, str, bool, dict[str, Any]]:
    exposure = cfg.raw["exposure"]
    lam = cfg.lambda_km(event.type, event.subtype, event.magnitude)
    prox, within = proximity(distance_km, event.uncertainty_km, inside, lam)
    half_life = cfg.half_life_hours(event.type, event.subtype)
    components = {
        "type_weight": float(exposure["type_weight"].get(event.type, exposure["type_weight"]["other"])),
        "severity_weight": float(exposure["severity_weight"][event.severity]),
        "proximity": prox,
        "location_confidence": event.location_confidence,
        "source_reliability": event.reliability,
        "recency_decay": recency_decay(event.last_seen_at, now, half_life),
        "criticality_factor": float(exposure["criticality_factor"][criticality]),
        "lambda_km": lam,
        "half_life_hours": half_life,
        "uncertainty_km": event.uncertainty_km,
    }
    raw = 1.0
    for name in (
        "type_weight",
        "severity_weight",
        "proximity",
        "location_confidence",
        "source_reliability",
        "recency_decay",
        "criticality_factor",
    ):
        raw *= components[name]
    components["raw_score"] = raw
    components["clamped"] = raw > 1.0
    score = min(raw, 1.0)
    return score, cfg.level_for(score), within, components


def matchable(event: EventRow) -> bool:
    """Country-level events and resolved events are not matched against site assets."""
    return event.location_level != "country" and event.status != "resolved"


def compute_for_event(
    conn: psycopg.Connection[Any], cfg: EventsConfig, event_id: str, now: dt.datetime, tenant_id: str | None = None
) -> list[Exposure]:
    event = load_event(conn, event_id)
    if not matchable(event):
        return []
    exposure = cfg.raw["exposure"]
    lam = cfg.lambda_km(event.type, event.subtype, event.magnitude)
    radius_m = (event.uncertainty_km + exposure["search_lambda_multiples"] * lam) * 1000.0
    with conn.cursor() as cur:
        cur.execute(
            """WITH ev AS (SELECT ST_SetSRID(ST_GeomFromGeoJSON(%(g)s), 4326) AS geom)
               SELECT a.id, a.tenant_id, a.criticality, ST_Distance(a.geom::geography, ev.geom::geography) / 1000.0,
                      ST_Intersects(a.geom, ev.geom)
                 FROM assets a, ev
                WHERE a.status = 'active' AND (%(t)s::uuid IS NULL OR a.tenant_id = %(t)s::uuid)
                  AND ST_DWithin(a.geom::geography, ev.geom::geography, %(r)s)""",
            {"g": event.geometry, "r": radius_m, "t": tenant_id},
        )
        rows = cur.fetchall()
    results: list[Exposure] = []
    minimum = float(exposure["min_store_score"])
    with conn.cursor() as cur:
        for asset_id, tenant, criticality, distance_km, inside in rows:
            score, level, within, components = score_pair(
                cfg, event, criticality, float(distance_km), bool(inside), now
            )
            if score < minimum:
                cur.execute("DELETE FROM exposures WHERE event_id = %s AND asset_id = %s", (event.id, asset_id))
                continue
            cur.execute(
                """INSERT INTO exposures (tenant_id, event_id, asset_id, distance_km, within_uncertainty, score, level, components,
                                          config_version, computed_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (event_id, asset_id) DO UPDATE SET distance_km = EXCLUDED.distance_km,
                       within_uncertainty = EXCLUDED.within_uncertainty, score = EXCLUDED.score, level = EXCLUDED.level,
                       components = EXCLUDED.components, config_version = EXCLUDED.config_version, computed_at = EXCLUDED.computed_at""",
                (
                    tenant,
                    event.id,
                    asset_id,
                    distance_km,
                    within,
                    score,
                    level,
                    json.dumps(components),
                    cfg.version,
                    now,
                ),
            )
            results.append(
                Exposure(str(tenant), event.id, str(asset_id), float(distance_km), within, score, level, components)
            )
        # exposures of assets that moved out of range
        in_range = [r[0] for r in rows]
        cur.execute("DELETE FROM exposures WHERE event_id = %s AND NOT (asset_id = ANY(%s))", (event.id, in_range))
    return results
