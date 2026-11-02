"""Database access for the linking pipeline: place lookup by QID and gazetteer candidate search."""

from __future__ import annotations

from typing import Any

import psycopg

from meridian.geo.search import search_places
from meridian.linking.types import PlaceRecord

PLACE_COLUMNS = """p.id, p.name, p.type, p.country_code, p.admin1_name, p.population, p.lat, p.lon, p.uncertainty_km,
                   p.qid, p.geonames_id, p.location_level, p.country_level"""


def _record(row: tuple[Any, ...]) -> PlaceRecord:
    return PlaceRecord(
        place_id=row[0],
        name=row[1],
        type=row[2],
        country_code=row[3],
        admin1_name=row[4],
        population=row[5],
        lat=row[6],
        lon=row[7],
        uncertainty_km=row[8],
        qid=row[9],
        geonames_id=row[10],
        location_level=row[11],
        country_level=bool(row[12]),
    )


def places_by_qid(conn: psycopg.Connection[Any], qids: list[str]) -> dict[str, PlaceRecord]:
    """Place records for QIDs. QIDs that are not places (or have no coordinates) are absent."""
    if not qids:
        return {}
    with conn.cursor() as cur:
        cur.execute(f"SELECT {PLACE_COLUMNS} FROM places p WHERE p.qid = ANY(%s)", (qids,))  # noqa: S608
        return {r.qid: r for r in map(_record, cur.fetchall()) if r.qid}


def places_by_id(conn: psycopg.Connection[Any], ids: list[int]) -> dict[int, PlaceRecord]:
    if not ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(f"SELECT {PLACE_COLUMNS} FROM places p WHERE p.id = ANY(%s)", (ids,))  # noqa: S608
        return {r.place_id: r for r in map(_record, cur.fetchall())}


def gazetteer_candidates(
    conn: psycopg.Connection[Any], surface: str, *, country_code: str | None = None, k: int = 20
) -> list[tuple[PlaceRecord, float]]:
    """Candidates for a surface form by exact, alias, and fuzzy name match, with a name similarity."""
    hits = search_places(conn, surface, k=k, country_code=country_code)
    records = places_by_id(conn, [h.place_id for h in hits])
    return [(records[h.place_id], h.similarity if not h.exact else 1.0) for h in hits if h.place_id in records]


def has_exact_name(conn: psycopg.Connection[Any], surfaces: list[str]) -> set[str]:
    """Which of the normalized surfaces match some place name or alias exactly (used for fallback spans)."""
    from meridian.geo.names import normalize_name

    keys = {normalize_name(s): s for s in surfaces if s}
    if not keys:
        return set()
    with conn.cursor() as cur:
        cur.execute(
            """SELECT name_normalized FROM places WHERE name_normalized = ANY(%(k)s)
               UNION SELECT alias_normalized FROM place_aliases WHERE alias_normalized = ANY(%(k)s)""",
            {"k": list(keys)},
        )
        found = {row[0] for row in cur.fetchall()}
    return {keys[k] for k in found}
