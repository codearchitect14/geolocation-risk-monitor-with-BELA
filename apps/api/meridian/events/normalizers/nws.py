"""National Weather Service CAP alerts to normalized events.

Many alerts carry no geometry, only zone URLs. A ZoneResolver turns zones into one polygon (cached in nws_zone_cache).
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from typing import Any

import httpx
import psycopg
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from meridian.events.config import EventsConfig
from meridian.events.types import NormalizedEvent, parse_time

log = logging.getLogger("meridian.events.nws")
ZONE_FORECAST_TYPES = ("marine", "offshore", "coastal", "forecast/offshore")
GeometryResolver = Callable[[list[str]], dict[str, Any] | None]


def classify_event(name: str, cfg: EventsConfig) -> tuple[str, str] | None:
    for row in cfg.raw["hazard_feeds"]["nws"]["event_types"]:
        if name.startswith(row["match"]):
            return str(row["type"]), str(row["subtype"])
    return None


def severity_for(properties: dict[str, Any], subtype: str, cfg: EventsConfig) -> int:
    rules = cfg.raw["hazard_feeds"]["nws"]
    severity = int(rules["severity"].get(properties.get("severity") or "Unknown", 1))
    if properties.get("certainty") in rules["uncertain_certainty"]:
        severity -= 1
    name = properties.get("event") or ""
    if name.endswith(("Watch", "Outlook")):
        severity -= int(rules["watch_lowers_by"])
    severity = min(severity, int(rules["severity_caps"].get(subtype, 4)))
    return max(1, min(severity, 4))


def normalize(
    feature: dict[str, Any], cfg: EventsConfig, resolve_geometry: GeometryResolver | None = None
) -> NormalizedEvent | None:
    props = feature.get("properties") or {}
    rules = cfg.raw["hazard_feeds"]["nws"]
    name = props.get("event") or ""
    if props.get("status") != "Actual" or name in rules["ignore_events"]:
        return None
    mapped = classify_event(name, cfg)
    if mapped is None:
        return None
    event_type, subtype = mapped

    geometry = feature.get("geometry")
    zones = list(props.get("affectedZones") or [])
    level = "admin2"
    if not geometry and resolve_geometry is not None and zones:
        geometry = resolve_geometry(zones)
        if any(f"/zones/{t}/" in z for z in zones for t in ZONE_FORECAST_TYPES):
            level = "natural"
    if not geometry:
        return None

    alert_id = str(props.get("id") or feature.get("id"))
    ref = alert_id.rsplit("/", 1)[-1]
    references = [str(r.get("identifier")) for r in props.get("references") or [] if r.get("identifier")]
    sent = parse_time(props.get("sent")) or parse_time(props.get("effective"))
    if sent is None:
        return None
    return NormalizedEvent(
        source_kind="nws",
        source_ref=ref,
        type=event_type,
        subtype=subtype,
        severity=severity_for(props, subtype, cfg),
        title=props.get("headline") or f"{name} for {props.get('areaDesc')}",
        geometry=geometry,
        location_level=level,
        uncertainty_km=float(rules["uncertainty_km"]),
        occurred_at=parse_time(props.get("onset")) or parse_time(props.get("effective")) or sent,
        published_at=sent,
        updated_at=sent,
        expires_at=parse_time(props.get("ends")) or parse_time(props.get("expires")),
        url=props.get("web") or alert_id,
        language="en",
        summary=(props.get("description") or "")[:280] or None,
        supersedes=references,
        details={
            "nws_event": name,
            "nws_severity": props.get("severity"),
            "certainty": props.get("certainty"),
            "urgency": props.get("urgency"),
            "area": props.get("areaDesc"),
            "message_type": props.get("messageType"),
            "cancelled": props.get("messageType") == "Cancel",
            "sender": props.get("senderName"),
        },
    )


class ZoneResolver:
    """Zone URLs to one simplified polygon, fetched from api.weather.gov and cached in the database."""

    def __init__(self, conn: psycopg.Connection[Any], client: httpx.Client | None = None, pause: float = 0.5) -> None:
        self.conn = conn
        agent = (
            os.environ.get("NWS_USER_AGENT")
            or f"MeridianSignal-data/0.1 ({os.environ.get('MS_CONTACT', 'local development run')})"
        )
        self.client = client or httpx.Client(
            timeout=30, headers={"User-Agent": agent, "Accept": "application/geo+json"}
        )
        self.pause = pause
        self.fetched = 0

    def _cached(self, url: str) -> tuple[str, str | None] | None:
        with self.conn.cursor() as cur:
            cur.execute("SELECT status, ST_AsGeoJSON(geom) FROM nws_zone_cache WHERE zone_url = %s", (url,))
            row = cur.fetchone()
        return (row[0], row[1]) if row else None

    def _fetch(self, url: str) -> None:
        status, geom = "error", None
        try:
            for attempt in range(3):
                response = self.client.get(url)
                if response.status_code in (429, 503):
                    time.sleep(2 * (attempt + 1))
                    continue
                if response.status_code == 404:
                    status = "missing"
                elif response.status_code == 200 and response.json().get("geometry"):
                    shapely_geom = shape(response.json()["geometry"]).simplify(0.01)
                    status, geom = "ok", shapely_geom.wkt
                break
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("zone fetch failed %s: %s", url, exc)
        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO nws_zone_cache (zone_url, status, geom) VALUES (%s, %s, ST_GeomFromText(%s, 4326))
                   ON CONFLICT (zone_url) DO UPDATE SET status = EXCLUDED.status, geom = EXCLUDED.geom, fetched_at = now()""",
                (url, status, geom),
            )
        self.fetched += 1
        time.sleep(self.pause)

    def __call__(self, zones: list[str]) -> dict[str, Any] | None:
        import json

        shapes = []
        for url in zones:
            cached = self._cached(url)
            if cached is None:
                self._fetch(url)
                cached = self._cached(url)
            if cached and cached[0] == "ok" and cached[1]:
                shapes.append(shape(json.loads(cached[1])))
        if not shapes:
            return None
        union = unary_union(shapes)
        if union.geom_type not in ("Polygon", "MultiPolygon"):
            union = union.convex_hull
        return dict(mapping(union))
