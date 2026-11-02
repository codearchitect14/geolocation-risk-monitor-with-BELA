"""Shared fixtures for the event pipeline tests: a few places, a tenant with assets, and fakes for the services."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from typing import Any

import httpx
import psycopg

from meridian.geo.names import normalize_name
from meridian.linking.nel_client import NelClient, NelMention
from meridian.llm.client import LlmClient

NOW = dt.datetime(2026, 11, 2, 15, 0, tzinfo=dt.UTC)

PLACES = [
    # id, qid, name, type, country, admin1, population, lat, lon
    (1, "Q1", "Springfield", "city", "US", "Illinois", 116250, 39.80, -89.64),
    (2, "Q2", "Springfield", "city", "US", "Missouri", 167882, 37.22, -93.30),
    (3, "Q3", "Dayton", "city", "US", "Ohio", 137644, 39.76, -84.19),
    (5, "Q5", "Illinois", "admin1", "US", "Illinois", 12_800_000, 40.0, -89.0),
    (6, "Q6", "United States", "country", "US", None, 330_000_000, 39.8, -98.6),
]


def seed_places(conn: psycopg.Connection[Any]) -> None:
    with conn.cursor() as cur:
        cur.execute("TRUNCATE places, ref_country_info CASCADE")
        cur.execute("INSERT INTO ref_country_info (iso2, iso3, name) VALUES ('US', 'USA', 'United States')")
        for pid, qid, name, ptype, cc, admin1, pop, lat, lon in PLACES:
            level = "country" if ptype == "country" else "admin1" if ptype == "admin1" else "city"
            cur.execute(
                """INSERT INTO places (id, qid, name, name_normalized, type, country_code, admin1_name, population, lat, lon, centroid, geom,
                                       source, uncertainty_km, location_level, country_level)
                   OVERRIDING SYSTEM VALUE VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                       ST_SetSRID(ST_MakePoint(%s, %s), 4326), 'wikidata', %s, %s, %s)""",
                (
                    pid,
                    qid,
                    name,
                    normalize_name(name),
                    ptype,
                    cc,
                    admin1,
                    pop,
                    lat,
                    lon,
                    lon,
                    lat,
                    lon,
                    lat,
                    {"city": 25, "admin1": 100, "country": 300}[ptype],
                    level,
                    ptype == "country",
                ),
            )
    conn.commit()


def reset_events(conn: psycopg.Connection[Any]) -> None:
    with conn.cursor() as cur:
        cur.execute("TRUNCATE events, tenants, articles CASCADE")
    conn.commit()


def seed_tenant(
    conn: psycopg.Connection[Any], assets: list[tuple[str, float, float, int]], name: str = "Demo"
) -> tuple[str, dict[str, str]]:
    """Create a tenant and point assets (name, lat, lon, criticality). Returns the tenant id and asset ids by name."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO tenants (name, slug) VALUES (%s, %s) RETURNING id", (name, name.lower().replace(" ", "-"))
        )
        tenant = str(cur.fetchone()[0])  # type: ignore[index]
        ids: dict[str, str] = {}
        for asset_name, lat, lon, criticality in assets:
            cur.execute(
                """INSERT INTO assets (tenant_id, name, type, geom, criticality) VALUES (%s, %s, 'site', ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s)
                   RETURNING id""",
                (tenant, asset_name, lon, lat, criticality),
            )
            ids[asset_name] = str(cur.fetchone()[0])  # type: ignore[index]
    conn.commit()
    return tenant, ids


def fake_embedder(texts: list[str]) -> list[list[float]]:
    """Hashed bag of words, normalized: texts that share words have a high cosine."""
    out = []
    for text in texts:
        vector = [0.0] * 128
        for word in normalize_name(text).split():
            vector[int(hashlib.sha256(word.encode()).hexdigest(), 16) % 128] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        out.append([v / norm for v in vector])
    return out


class FakeNel(NelClient):
    """Returns the Springfield and Dayton mentions it finds in a passage, with the ambiguity BELA would report."""

    def __init__(self) -> None:
        pass

    def healthy(self) -> bool:
        return True

    def link(self, passages: list[tuple[str, str]], top_k: int = 10, batch: int = 32) -> dict[str, list[NelMention]]:
        out: dict[str, list[NelMention]] = {}
        for pid, text in passages:
            mentions = []
            for surface, candidates in (("Springfield", [("Q2", 0.55), ("Q1", 0.50)]), ("Dayton", [("Q3", 0.95)])):
                start = text.find(surface)
                while start >= 0:
                    ranked = list(candidates)
                    tail = text[start + len(surface) : start + len(surface) + 12]
                    if tail.startswith(", Illinois"):  # a qualifier is context a real encoder would use
                        ranked = [("Q1", 0.80), ("Q2", 0.20)]
                    elif tail.startswith(", Missouri"):
                        ranked = [("Q2", 0.80), ("Q1", 0.20)]
                    mentions.append(
                        NelMention(
                            start, start + len(surface), surface, ranked[0][0], 0.9, ranked[0][1], ranked, ranked
                        )
                    )
                    start = text.find(surface, start + len(surface))
            out[pid] = mentions
        return out


def llm_returning(**fields: Any) -> LlmClient:
    """A language model client that always answers with the given event label fields."""
    label = {
        "reason": "test",
        "event_type": "industrial_accident",
        "subtype": "fire",
        "severity": 3,
        "subject_is_named_private_person": False,
        **fields,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(label)}}], "usage": {"completion_tokens": 20}}
        )

    return LlmClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


def make_event(
    conn: psycopg.Connection[Any],
    *,
    lat: float,
    lon: float,
    type_: str = "industrial_accident",
    subtype: str | None = "fire",
    severity: int = 3,
    uncertainty: float = 25.0,
    level: str = "city",
    confidence: float = 0.8,
    reliability: float = 0.6,
    last_seen: dt.datetime = NOW,
    details: dict[str, Any] | None = None,
    geometry: dict[str, Any] | None = None,
    status: str = "new",
) -> str:
    """Insert an event directly with exactly the values a scoring test needs."""
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO events (type, subtype, severity, status, first_seen_at, last_seen_at, occurred_at, title, geom, uncertainty_km,
                                   location_level, location_confidence, reliability, details)
               VALUES (%s, %s, %s, %s, %s, %s, %s, 'Test event', ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), %s, %s, %s, %s, %s) RETURNING id""",
            (
                type_,
                subtype,
                severity,
                status,
                last_seen,
                last_seen,
                last_seen,
                json.dumps(geometry or {"type": "Point", "coordinates": [lon, lat]}),
                uncertainty,
                level,
                confidence,
                reliability,
                json.dumps(details or {}),
            ),
        )
        event_id = str(cur.fetchone()[0])  # type: ignore[index]
    conn.commit()
    return event_id
