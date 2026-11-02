"""Database access for events and their sources. Everything here is idempotent per (source kind, source ref)."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import h3
import psycopg

from meridian.events.config import EventsConfig
from meridian.events.types import NormalizedEvent

FEED_KINDS = ("usgs", "nws", "firms", "reliefweb")


def find_event_by_source(conn: psycopg.Connection[Any], kind: str, ref: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT event_id FROM event_sources WHERE source_kind = %s AND source_ref = %s", (kind, ref))
        row = cur.fetchone()
    return str(row[0]) if row else None


def insert_event(conn: psycopg.Connection[Any], ne: NormalizedEvent, cfg: EventsConfig, config_version: str) -> str:
    lat, lon = ne.centroid()
    cell = h3.str_to_int(h3.latlng_to_cell(lat, lon, int(cfg.raw["clustering"]["h3_resolution"])))
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO events (type, subtype, severity, status, confirmation, first_seen_at, last_seen_at, occurred_at, title,
                                   summary, geom, uncertainty_km, location_place_id, location_level, location_confidence, h3_cell,
                                   language_set, reliability, expires_at, details, config_version)
               VALUES (%s, %s, %s, 'new', 'unconfirmed', %s, %s, %s, %s, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (
                ne.type,
                ne.subtype,
                ne.severity,
                ne.published_at,
                ne.published_at,
                ne.occurred_at,
                ne.title[:500],
                ne.summary,
                json.dumps(ne.geometry),
                ne.uncertainty_km,
                ne.location_place_id,
                ne.location_level,
                ne.location_confidence,
                cell,
                [ne.language] if ne.language else [],
                cfg.reliability(ne.source_kind),
                ne.expires_at,
                json.dumps(
                    {
                        "location_source": ne.source_kind,
                        **{
                            k: v
                            for k, v in ne.details.items()
                            if k in ("magnitude", "depth_km", "nws_event", "detections")
                        },
                    }
                ),
                config_version,
            ),
        )
        row = cur.fetchone()
    assert row is not None
    return str(row[0])


def add_source(conn: psycopg.Connection[Any], event_id: str, ne: NormalizedEvent, cfg: EventsConfig) -> bool:
    """Attach a source record. Returns False when this source record is already stored."""
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO event_sources (event_id, source_kind, url, published_at, source_ref, article_id, snippet, reliability, domain, details)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (source_kind, source_ref) DO NOTHING""",
            (
                event_id,
                ne.source_kind,
                ne.url,
                ne.published_at,
                ne.source_ref,
                ne.article_id,
                (ne.snippet or "")[:300] or None,
                cfg.reliability(ne.source_kind),
                ne.domain,
                json.dumps(
                    {
                        "severity": ne.severity,
                        "type": ne.type,
                        "subtype": ne.subtype,
                        "title": ne.title[:300],
                        "location_confidence": ne.location_confidence,
                        "uncertainty_km": ne.uncertainty_km,
                        "location_level": ne.location_level,
                    }
                ),
            ),
        )
        return cur.rowcount == 1


def record_update(conn: psycopg.Connection[Any], event_id: str, kind: str, detail: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO event_updates (event_id, update_type, detail) VALUES (%s, %s, %s)",
            (event_id, kind, json.dumps(detail, default=str)),
        )


def independent_source_count(sources: list[tuple[str, str | None]]) -> int:
    """Distinct feeds plus distinct news outlets."""
    feeds = {kind for kind, _ in sources if kind != "news"}
    outlets = {domain or f"unknown-{i}" for i, (kind, domain) in enumerate(sources) if kind == "news"}
    return len(feeds) + len(outlets)


def refresh_aggregates(
    conn: psycopg.Connection[Any], event_id: str, cfg: EventsConfig, now: dt.datetime | None = None
) -> dict[str, Any]:
    """Recompute severity, reliability, confirmation, and last_seen_at from the stored sources."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT source_kind, domain, published_at, (details->>'severity')::int, details->>'subtype'
                 FROM event_sources WHERE event_id = %s""",
            (event_id,),
        )
        sources = cur.fetchall()
    if not sources:
        return {}
    independent: list[str] = []
    seen_outlets: set[str] = set()
    for kind, domain, *_ in sources:
        if kind == "news":
            key = domain or str(len(seen_outlets))
            if key in seen_outlets:
                continue
            seen_outlets.add(key)
        elif kind in independent:
            continue
        independent.append(kind)
    reliability = cfg.combined_reliability(independent)
    confirmed = len(independent) >= int(cfg.raw["confirmation_min_sources"])
    severity = max(s[3] for s in sources if s[3] is not None)
    last_seen = max(s[2] for s in sources)
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE events SET severity = %s, reliability = %s, confirmation = %s,
                                 last_seen_at = GREATEST(last_seen_at, %s), updated_at = now() WHERE id = %s""",
            (severity, reliability, "confirmed" if confirmed else "unconfirmed", last_seen, event_id),
        )
    return {
        "severity": severity,
        "reliability": reliability,
        "confirmed": confirmed,
        "sources": len(sources),
        "independent": len(independent),
    }


def location_rank(is_feed: bool, location_confidence: float, uncertainty_km: float) -> tuple[int, float, float]:
    """Higher is better: hazard feed geometry first, then confidence, then a smaller uncertainty."""
    return (1 if is_feed else 0, location_confidence, -uncertainty_km)


def maybe_replace_location(
    conn: psycopg.Connection[Any], event_id: str, ne: NormalizedEvent, cfg: EventsConfig
) -> bool:
    """Adopt the new record's location when it is better than the one stored. Returns True when replaced."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT location_confidence, uncertainty_km, details->>'location_source' FROM events WHERE id = %s",
            (event_id,),
        )
        row = cur.fetchone()
    if row is None:
        return False
    current = location_rank(row[2] in FEED_KINDS, float(row[0] or 0), float(row[1] or 0))
    candidate = location_rank(ne.source_kind in FEED_KINDS, ne.location_confidence, ne.uncertainty_km)
    if candidate <= current:
        return False
    lat, lon = ne.centroid()
    cell = h3.str_to_int(h3.latlng_to_cell(lat, lon, int(cfg.raw["clustering"]["h3_resolution"])))
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE events SET geom = ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), uncertainty_km = %s, location_level = %s,
                                 location_confidence = %s, location_place_id = %s, h3_cell = %s,
                                 details = details || %s::jsonb WHERE id = %s""",
            (
                json.dumps(ne.geometry),
                ne.uncertainty_km,
                ne.location_level,
                ne.location_confidence,
                ne.location_place_id,
                cell,
                json.dumps({"location_source": ne.source_kind}),
                event_id,
            ),
        )
    return True


def add_language(conn: psycopg.Connection[Any], event_id: str, language: str | None) -> None:
    if not language:
        return
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE events SET language_set = (SELECT array_agg(DISTINCT l) FROM unnest(language_set || %s) l) WHERE id = %s",
            ([language], event_id),
        )
