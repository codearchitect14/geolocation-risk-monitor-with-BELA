"""Turn normalized records into events: create, revise, supersede, or merge with an existing event.

Order of checks for a record:
1. the same source record is already stored: a revision (USGS updates a magnitude, for example)
2. it supersedes records already stored (an NWS update of an earlier alert): it joins that event
3. an existing event matches by type, subtype, time window, distance, and (for news) title similarity: it is merged
4. otherwise a new event is created
"""

from __future__ import annotations

import datetime as dt
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import psycopg

from meridian.events import status, store
from meridian.events.config import EventsConfig
from meridian.events.types import NormalizedEvent

Embedder = Callable[[list[str]], list[list[float]]]
FEEDS = {"usgs", "nws", "firms", "reliefweb"}
NO_SELF_MERGE = {"usgs", "firms", "reliefweb"}  # two records of these feeds are always distinct incidents


@dataclass
class Outcome:
    action: str  # created, revised, superseded, merged, cancelled, duplicate
    event_id: str
    detail: dict[str, Any]


@dataclass
class Candidate:
    event_id: str
    type: str
    subtype: str | None
    distance_km: float
    uncertainty_km: float
    first_seen_at: dt.datetime
    last_seen_at: dt.datetime
    occurred_at: dt.datetime | None
    title: str
    source_kinds: list[str]
    same_cell: bool


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def compatible(cfg: EventsConfig, a_type: str, a_sub: str | None, b_type: str, b_sub: str | None) -> bool:
    clustering = cfg.raw["clustering"]
    if (
        a_type != b_type
        and [a_type, b_type] not in clustering["compatible_types"]
        and [b_type, a_type] not in clustering["compatible_types"]
    ):
        return False
    if a_sub and b_sub and a_sub != b_sub:
        groups = clustering["subtype_groups"]
        return any(a_sub in g and b_sub in g for g in groups)
    return True


def allowed_distance_km(cfg: EventsConfig, event_type: str, uncertainty_a: float, uncertainty_b: float) -> float:
    clustering = cfg.raw["clustering"]
    floor = float(clustering["min_distance_km"].get(event_type, clustering["min_distance_km"]["other"]))
    return min(max(uncertainty_a + uncertainty_b, floor), float(clustering["max_distance_km"]))


class EventIngestor:
    def __init__(self, conn: psycopg.Connection[Any], cfg: EventsConfig, embedder: Embedder | None = None) -> None:
        self.conn = conn
        self.cfg = cfg
        self.embedder = embedder

    # -- candidate search -------------------------------------------------------------------------------------
    def candidates(self, ne: NormalizedEvent) -> list[Candidate]:
        window = dt.timedelta(hours=max(self.cfg.window_hours(ne.type), 1))
        reference = ne.occurred_at or ne.published_at
        max_km = float(self.cfg.raw["clustering"]["max_distance_km"])
        lat, lon = ne.centroid()
        import h3

        cell = h3.latlng_to_cell(lat, lon, int(self.cfg.raw["clustering"]["h3_resolution"]))
        ring = {h3.str_to_int(c) for c in h3.grid_disk(cell, int(self.cfg.raw["clustering"]["h3_ring"]))}
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT e.id, e.type, e.subtype, ST_Distance(e.geom::geography, ST_SetSRID(ST_GeomFromGeoJSON(%(g)s), 4326)::geography) / 1000.0,
                          e.uncertainty_km, e.first_seen_at, e.last_seen_at, e.occurred_at, e.title, e.h3_cell,
                          COALESCE((SELECT array_agg(DISTINCT s.source_kind) FROM event_sources s WHERE s.event_id = e.id), '{}')
                     FROM events e
                    WHERE e.geom IS NOT NULL
                      AND ST_DWithin(e.geom::geography, ST_SetSRID(ST_GeomFromGeoJSON(%(g)s), 4326)::geography, %(m)s)
                      AND COALESCE(e.occurred_at, e.first_seen_at) BETWEEN %(t0)s AND %(t1)s
                    ORDER BY 4 LIMIT 50""",
                {
                    "g": json.dumps(ne.geometry),
                    "m": max_km * 1000.0,
                    "t0": reference - window,
                    "t1": reference + window,
                },
            )
            rows = cur.fetchall()
        return [
            Candidate(
                str(r[0]), r[1], r[2], float(r[3]), float(r[4] or 0), r[5], r[6], r[7], r[8], list(r[10]), r[9] in ring
            )
            for r in rows
        ]

    def find_match(self, ne: NormalizedEvent) -> tuple[str, dict[str, Any]] | None:
        eligible: list[Candidate] = []
        for c in self.candidates(ne):
            if not compatible(self.cfg, ne.type, ne.subtype, c.type, c.subtype):
                continue
            if ne.source_kind in NO_SELF_MERGE and ne.source_kind in c.source_kinds:
                continue
            if c.distance_km > allowed_distance_km(self.cfg, ne.type, ne.uncertainty_km, c.uncertainty_km):
                continue
            eligible.append(c)
        if not eligible:
            return None
        news_vs_news = [c for c in eligible if ne.source_kind == "news" and set(c.source_kinds) == {"news"}]
        similarity: dict[str, float] = {}
        if news_vs_news and self.embedder is not None:
            vectors = self.embedder([ne.title] + [c.title for c in news_vs_news])
            similarity = {c.event_id: cosine(vectors[0], v) for c, v in zip(news_vs_news, vectors[1:], strict=True)}
        threshold = float(self.cfg.raw["clustering"]["title_similarity_min"])
        best: tuple[tuple[float, float, float], Candidate, float] | None = None
        for c in eligible:
            sim = similarity.get(c.event_id)
            if c in news_vs_news and (self.embedder is None or sim is None or sim < threshold):
                continue  # two news reports need similar titles as well as place and time
            rank = (1.0 if c.same_cell else 0.0, sim or 0.0, -c.distance_km)
            if best is None or rank > best[0]:
                best = (rank, c, sim or 0.0)
        if best is None:
            return None
        return best[1].event_id, {"distance_km": round(best[1].distance_km, 2), "title_similarity": round(best[2], 3)}

    # -- main entry ---------------------------------------------------------------------------------------------
    def ingest(self, ne: NormalizedEvent) -> Outcome:
        cfg = self.cfg
        existing = store.find_event_by_source(self.conn, ne.source_kind, ne.source_ref)
        if existing:
            return self._revise(existing, ne)
        for ref in ne.supersedes:
            joined = store.find_event_by_source(self.conn, ne.source_kind, ref)
            if joined:
                return self._attach(joined, ne, "superseded", {"supersedes": ref})
        match = self.find_match(ne)
        if match:
            return self._attach(match[0], ne, "merged", match[1])
        event_id = store.insert_event(self.conn, ne, cfg, cfg.version)
        store.add_source(self.conn, event_id, ne, cfg)
        store.refresh_aggregates(self.conn, event_id, cfg)
        store.record_update(self.conn, event_id, "created", {"source": ne.source_kind, "ref": ne.source_ref})
        status.refresh_event_status(self.conn, cfg, event_id, ne.published_at)
        return Outcome("created", event_id, {})

    def _attach(self, event_id: str, ne: NormalizedEvent, action: str, detail: dict[str, Any]) -> Outcome:
        cfg = self.cfg
        inserted = store.add_source(self.conn, event_id, ne, cfg)
        if not inserted:
            return Outcome("duplicate", event_id, {})
        before = self._snapshot(event_id)
        aggregates = store.refresh_aggregates(self.conn, event_id, cfg)
        moved = store.maybe_replace_location(self.conn, event_id, ne, cfg)
        store.add_language(self.conn, event_id, ne.language)
        if ne.details.get("cancelled"):
            with self.conn.cursor() as cur:
                cur.execute("UPDATE events SET status = 'resolved', updated_at = now() WHERE id = %s", (event_id,))
            store.record_update(self.conn, event_id, "cancelled", {"source": ne.source_kind, "ref": ne.source_ref})
            return Outcome("cancelled", event_id, detail)
        after = self._snapshot(event_id)
        status.refresh_event_status(self.conn, cfg, event_id, ne.published_at)
        store.record_update(
            self.conn,
            event_id,
            action,
            {
                **detail,
                "source": ne.source_kind,
                "ref": ne.source_ref,
                "location_replaced": moved,
                "aggregates": aggregates,
            },
        )
        return Outcome(
            action,
            event_id,
            {
                **detail,
                "severity_before": before["severity"],
                "severity_after": after["severity"],
                "location_replaced": moved,
                "confirmation": after["confirmation"],
            },
        )

    def _snapshot(self, event_id: str) -> dict[str, Any]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT severity, confirmation, location_confidence FROM events WHERE id = %s", (event_id,))
            row = cur.fetchone()
        assert row is not None
        return {"severity": row[0], "confirmation": row[1], "location_confidence": row[2]}

    def _revise(self, event_id: str, ne: NormalizedEvent) -> Outcome:
        """The same source record again: update it only when it is a newer revision."""
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT published_at, details FROM event_sources WHERE source_kind = %s AND source_ref = %s",
                (ne.source_kind, ne.source_ref),
            )
            stored = cur.fetchone()
        assert stored is not None
        stored_details = stored[1] or {}
        changed = stored_details.get("severity") != ne.severity or (ne.updated_at and ne.updated_at > stored[0])
        if not changed:
            return Outcome("duplicate", event_id, {})
        with self.conn.cursor() as cur:
            cur.execute(
                """UPDATE event_sources SET published_at = %s, details = details || %s::jsonb
                    WHERE source_kind = %s AND source_ref = %s""",
                (
                    ne.updated_at or ne.published_at,
                    json.dumps({"severity": ne.severity, "title": ne.title[:300]}),
                    ne.source_kind,
                    ne.source_ref,
                ),
            )
        before = self._snapshot(event_id)
        store.refresh_aggregates(self.conn, event_id, self.cfg)
        if ne.source_kind in FEEDS:
            self._adopt_feed_location(event_id, ne)
        after = self._snapshot(event_id)
        status.refresh_event_status(self.conn, self.cfg, event_id, ne.updated_at or ne.published_at)
        store.record_update(
            self.conn,
            event_id,
            "revision",
            {
                "source": ne.source_kind,
                "ref": ne.source_ref,
                "severity_before": before["severity"],
                "severity_after": after["severity"],
            },
        )
        return Outcome(
            "revised", event_id, {"severity_before": before["severity"], "severity_after": after["severity"]}
        )

    def _adopt_feed_location(self, event_id: str, ne: NormalizedEvent) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """UPDATE events SET geom = ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), summary = COALESCE(%s, summary),
                                     title = %s, details = details || %s::jsonb WHERE id = %s""",
                (
                    json.dumps(ne.geometry),
                    ne.summary,
                    ne.title[:500],
                    json.dumps(
                        {
                            k: v
                            for k, v in ne.details.items()
                            if k in ("magnitude", "depth_km", "nws_event", "detections")
                        }
                    ),
                    event_id,
                ),
            )
