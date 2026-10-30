"""Gazetteer search over the places table: exact, trigram, and optional vector candidates."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import psycopg

from meridian.geo.names import name_keys, normalize_name

CANDIDATE_LIMIT = 200
FUZZY_THRESHOLD = 0.55
LOG_POPULATION_CAP = math.log1p(30_000_000)

# Prior over place types for a bare name query: administrative and settlement matches are more
# likely than a facility or natural feature that shares the name.
TYPE_PRIOR: dict[str, float] = {
    "country": 1.0,
    "admin1": 0.9,
    "city": 1.0,
    "town": 0.85,
    "village": 0.7,
    "admin2": 0.7,
    "admin_region": 0.6,
    "island": 0.6,
    "airport": 0.55,
    "seaport": 0.55,
    "mountain": 0.45,
    "lake": 0.45,
    "river": 0.45,
}

CANDIDATE_SQL = """
WITH hits AS (
    SELECT p.id, 1.0::real AS sim, true AS exact FROM places p WHERE p.name_normalized = ANY(%(keys)s)
    UNION ALL
    SELECT a.place_id, 1.0::real, true FROM place_aliases a WHERE a.alias_normalized = ANY(%(keys)s)
    UNION ALL
    SELECT p.id, similarity(p.name_normalized, %(key)s), false FROM places p
     WHERE %(fuzzy)s AND p.name_normalized %% %(key)s
    UNION ALL
    SELECT a.place_id, similarity(a.alias_normalized, %(key)s), false FROM place_aliases a
     WHERE %(fuzzy)s AND a.alias_normalized %% %(key)s
), best AS (
    SELECT id, max(sim) AS sim, bool_or(exact) AS exact FROM hits GROUP BY id
    ORDER BY bool_or(exact) DESC, max(sim) DESC LIMIT %(limit)s
)
SELECT p.id, p.name, p.type, p.country_code, p.admin1_name, p.population, p.lat, p.lon,
       p.geonames_id, p.qid, p.uncertainty_km, b.sim, b.exact
  FROM best b JOIN places p ON p.id = b.id
"""


@dataclass(frozen=True)
class PlaceHit:
    place_id: int
    name: str
    type: str
    country_code: str | None
    admin1_name: str | None
    population: int | None
    lat: float
    lon: float
    geonames_id: int | None
    qid: str | None
    uncertainty_km: float | None
    similarity: float
    exact: bool
    score: float


def score(
    similarity: float, exact: bool, population: int | None, place_type: str, country_match: bool = False
) -> float:
    """Combine name evidence with a population and type prior. Weights were set on the
    1,000 name evaluation and are documented in docs/place_kb_report.md."""
    prior = math.log1p(population or 0) / LOG_POPULATION_CAP
    value = 0.45 * similarity + 0.10 * exact + 0.30 * prior + 0.15 * TYPE_PRIOR.get(place_type, 0.5)
    return value + (0.15 if country_match else 0.0)


def search_places(
    conn: psycopg.Connection[Any],
    query: str,
    *,
    k: int = 5,
    country_code: str | None = None,
    fuzzy: bool = True,
) -> list[PlaceHit]:
    keys = name_keys(query)
    if not keys:
        return []
    key = normalize_name(query)
    with conn.cursor() as cur:
        cur.execute("SET LOCAL pg_trgm.similarity_threshold = %s" % FUZZY_THRESHOLD)  # noqa: UP031
        cur.execute(CANDIDATE_SQL, {"keys": keys, "key": key, "fuzzy": fuzzy, "limit": CANDIDATE_LIMIT})
        rows = cur.fetchall()
    hits = [
        PlaceHit(
            place_id=row[0],
            name=row[1],
            type=row[2],
            country_code=row[3],
            admin1_name=row[4],
            population=row[5],
            lat=row[6],
            lon=row[7],
            geonames_id=row[8],
            qid=row[9],
            uncertainty_km=row[10],
            similarity=row[11],
            exact=row[12],
            score=score(row[11], row[12], row[5], row[2], country_code is not None and row[3] == country_code),
        )
        for row in rows
    ]
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:k]


VECTOR_SQL = """
SELECT place_id, min(embedding <=> %(vec)s::vector) AS distance
  FROM (SELECT place_id, embedding FROM place_embeddings
         ORDER BY embedding <=> %(vec)s::vector LIMIT %(limit)s) nearest
 GROUP BY place_id ORDER BY distance LIMIT %(k)s
"""


def search_by_embedding(
    conn: psycopg.Connection[Any], vector: Sequence[float], *, k: int = 5, ef_search: int = 100
) -> list[tuple[int, float]]:
    """Nearest places by cosine distance. Returns (place_id, similarity) pairs, best first.

    Several embedding rows can belong to one place (name, alias, description), so the closest
    rows are collapsed to one entry per place.
    """
    literal = "[" + ",".join(f"{float(v):.6g}" for v in vector) + "]"
    with conn.cursor() as cur:
        cur.execute("SET LOCAL hnsw.ef_search = %d" % ef_search)  # noqa: UP031
        cur.execute(VECTOR_SQL, {"vec": literal, "limit": k * 4, "k": k})
        return [(int(row[0]), 1.0 - float(row[1])) for row in cur.fetchall()]
