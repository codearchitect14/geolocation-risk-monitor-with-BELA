"""Ingest hazard feed files and run the exposure and alert steps for each event."""

from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import psycopg

from meridian import notify
from meridian.events import alerts, exposure
from meridian.events.config import EventsConfig
from meridian.events.ingest import EventIngestor, Outcome
from meridian.events.normalizers import firms, nws, reliefweb, usgs
from meridian.events.types import NormalizedEvent


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def assets_near(conn: psycopg.Connection[Any], lat: float, lon: float, km: float) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT EXISTS (SELECT 1 FROM assets WHERE status = 'active'
                               AND ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s))""",
            (lon, lat, km * 1000.0),
        )
        row = cur.fetchone()
    return bool(row and row[0])


def nearest_place_label(conn: psycopg.Connection[Any], lat: float, lon: float) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT name, country_code, ST_Distance(centroid::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography) / 1000.0
                 FROM places WHERE type IN ('city', 'town', 'village')
                ORDER BY centroid <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326) LIMIT 1""",
            (lon, lat, lon, lat),
        )
        row = cur.fetchone()
    return f"{row[0]}, {row[1]} ({row[2]:.0f} km)" if row and row[1] else (str(row[0]) if row else None)


def process_event(
    conn: psycopg.Connection[Any], cfg: EventsConfig, event_id: str, now: dt.datetime
) -> alerts.AlertResult:
    exposure.compute_for_event(conn, cfg, event_id, now)
    return alerts.evaluate_alerts(conn, cfg, event_id, now)


class Run:
    """Counters for one ingestion run."""

    def __init__(self) -> None:
        self.actions: Counter[str] = Counter()
        self.skipped: Counter[str] = Counter()
        self.alerts = alerts.AlertResult()
        self.event_ids: set[str] = set()

    def add(self, outcome: Outcome, result: alerts.AlertResult | None) -> None:
        self.actions[outcome.action] += 1
        self.event_ids.add(outcome.event_id)
        if result is not None:
            self.alerts.merge(result)

    def summary(self) -> dict[str, Any]:
        return {
            "actions": dict(self.actions),
            "skipped": dict(self.skipped),
            "events_touched": len(self.event_ids),
            "alerts_created": self.alerts.created,
            "alerts_updated": self.alerts.updated,
            "alerts_suppressed_maintenance": self.alerts.suppressed_maintenance,
        }


def _ingest_many(
    conn: psycopg.Connection[Any],
    cfg: EventsConfig,
    records: Iterator[NormalizedEvent | tuple[str, None]],
    embedder: Any = None,
    now: dt.datetime | None = None,
    evaluate: bool = True,
    replay: bool = False,
) -> Run:
    run = Run()
    ingestor = EventIngestor(conn, cfg, embedder)
    for item in records:
        if isinstance(item, tuple):
            run.skipped[item[0]] += 1
            continue
        outcome = ingestor.ingest(item)
        result = None
        if evaluate and outcome.action in ("created", "revised", "merged", "superseded"):
            # Replay scores historical files as of each record's own time; live runs use the current time.
            as_of = (item.updated_at or item.published_at) if replay else (now or utcnow())
            result = process_event(conn, cfg, outcome.event_id, as_of)
        run.add(outcome, result)
        if result is not None and result.alert_ids:
            notify.enqueue_webhooks(conn, result.alert_ids)
        conn.commit()
        if result is not None and result.alert_ids:
            notify.publish_alerts(conn, result.alert_ids)
    return run


def read_jsonl(paths: list[Path]) -> Iterator[dict[str, Any]]:
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)


def ingest_usgs(
    conn: psycopg.Connection[Any],
    cfg: EventsConfig,
    paths: list[Path],
    now: dt.datetime | None = None,
    replay: bool = False,
) -> Run:
    rules = cfg.raw["hazard_feeds"]["usgs"]

    def records() -> Iterator[NormalizedEvent | tuple[str, None]]:
        for row in read_jsonl(paths):
            ne = usgs.normalize(row["feature"], cfg)
            if ne is None:
                yield ("invalid", None)
                continue
            magnitude = float(ne.details["magnitude"])
            if magnitude < float(rules["min_magnitude_near_assets"]):
                yield ("below_minimum_magnitude", None)
                continue
            if magnitude < float(rules["min_magnitude_worldwide"]):
                lat, lon = ne.centroid()
                if not assets_near(conn, lat, lon, float(rules["near_assets_km"])):
                    yield ("small_and_far_from_assets", None)
                    continue
            yield ne

    return _ingest_many(conn, cfg, records(), now=now, replay=replay)


def ingest_nws(
    conn: psycopg.Connection[Any],
    cfg: EventsConfig,
    paths: list[Path],
    resolver: Callable[[list[str]], dict[str, Any] | None],
    now: dt.datetime | None = None,
    replay: bool = False,
) -> Run:
    def records() -> Iterator[NormalizedEvent | tuple[str, None]]:
        for row in read_jsonl(paths):
            ne = nws.normalize(row["feature"], cfg, resolver)
            yield ne if ne is not None else ("ignored_or_no_geometry", None)

    return _ingest_many(conn, cfg, records(), now=now, replay=replay)


def ingest_firms(
    conn: psycopg.Connection[Any],
    cfg: EventsConfig,
    csv_text: str,
    now: dt.datetime | None = None,
    replay: bool = False,
) -> Run:
    rows = firms.parse_rows(csv_text)
    clusters = firms.cluster_events(rows, cfg, near_assets=lambda lat, lon, km: assets_near(conn, lat, lon, km))
    for ne in clusters:
        lat, lon = ne.details["centroid"]
        label = nearest_place_label(conn, lat, lon)
        if label:
            ne.title = f"Active fire near {label}"
    return _ingest_many(conn, cfg, iter(clusters), now=now, replay=replay)


def country_locator(conn: psycopg.Connection[Any]) -> Callable[[str], tuple[float, float, str] | None]:
    def locate(iso3: str) -> tuple[float, float, str] | None:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT p.lat, p.lon, p.name FROM places p JOIN ref_country_info c ON c.iso2 = p.country_code
                    WHERE p.type = 'country' AND c.iso3 = %s ORDER BY p.population DESC NULLS LAST LIMIT 1""",
                (iso3.upper(),),
            )
            row = cur.fetchone()
        return (row[0], row[1], row[2]) if row else None

    return locate


def ingest_reliefweb(
    conn: psycopg.Connection[Any],
    cfg: EventsConfig,
    paths: list[Path],
    now: dt.datetime | None = None,
    replay: bool = False,
) -> Run:
    locate = country_locator(conn)

    def records() -> Iterator[NormalizedEvent | tuple[str, None]]:
        for row in read_jsonl(paths):
            ne = reliefweb.normalize(row, cfg, locate)
            yield ne if ne is not None else ("not_a_disaster_or_no_country", None)

    return _ingest_many(conn, cfg, records(), now=now, replay=replay)
