"""Measure latency and capture query plans for the core spatial and lookup queries."""

from __future__ import annotations

import random
import statistics
import time
from dataclasses import dataclass
from typing import Any

import h3
import psycopg

# p95 latency targets in milliseconds, recorded in docs/adr/ADR-004.
TARGETS_MS = {
    "radius_50km": 50.0,
    "nearest_5": 20.0,
    "containment_admin1": 30.0,
    "polygon_places_in_bbox": 100.0,
    "name_exact": 10.0,
    "name_trigram": 100.0,
    "h3_cell_and_ring": 30.0,
    "vector_knn": 50.0,
}


@dataclass
class Query:
    name: str
    description: str
    sql: str
    params: Any


def build_queries(conn: psycopg.Connection[Any], rng: random.Random) -> list[tuple[Query, list[Any]]]:
    with conn.cursor() as cur:
        cur.execute("SELECT lat, lon, name_normalized FROM places ORDER BY random() LIMIT 200")
        samples = cur.fetchall()
        cur.execute("SELECT id FROM places WHERE type = 'admin1' AND has_polygon ORDER BY random() LIMIT 20")
        admin1_ids = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT embedding::text FROM place_embeddings ORDER BY random() LIMIT 1")
        vec_row = cur.fetchone()
    queries: list[tuple[Query, list[Any]]] = [
        (
            Query(
                "radius_50km",
                "Places within 50 km of a point (geography, expression GiST index)",
                "SELECT id, name FROM places WHERE ST_DWithin(centroid::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, 50000)",
                None,
            ),
            [(lon, lat) for lat, lon, _ in samples],
        ),
        (
            Query(
                "nearest_5",
                "Five nearest places to a point (KNN on the geometry GiST index)",
                "SELECT id, name FROM places ORDER BY centroid <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326) LIMIT 5",
                None,
            ),
            [(lon, lat) for lat, lon, _ in samples],
        ),
        (
            Query(
                "containment_admin1",
                "Admin-1 polygon containing a point",
                "SELECT name FROM ref_admin1 WHERE ST_Within(ST_SetSRID(ST_MakePoint(%s, %s), 4326), geom)",
                None,
            ),
            [(lon, lat) for lat, lon, _ in samples],
        ),
        (
            Query(
                "name_exact", "Exact normalized name lookup", "SELECT id FROM places WHERE name_normalized = %s", None
            ),
            [(name,) for _, _, name in samples],
        ),
        (
            Query(
                "name_trigram",
                "Fuzzy name lookup with pg_trgm (similarity >= 0.55)",
                "SELECT id, similarity(name_normalized, %s) FROM places WHERE name_normalized %% %s ORDER BY 2 DESC LIMIT 10",
                None,
            ),
            [(name, name) for _, _, name in samples],
        ),
        (
            Query(
                "h3_cell_and_ring",
                "Places in an H3 cell and its first ring (resolution 7)",
                "SELECT id FROM places WHERE h3_cell = ANY(%s)",
                None,
            ),
            [([h3.str_to_int(c) for c in h3.grid_disk(h3.latlng_to_cell(lat, lon, 7), 1)],) for lat, lon, _ in samples],
        ),
    ]
    if admin1_ids:
        queries.append(
            (
                Query(
                    "polygon_places_in_bbox",
                    "Places inside an admin-1 polygon (bbox prefilter then ST_Within)",
                    "SELECT count(*) FROM places p, ref_admin1 r WHERE r.ne_id = %s AND p.centroid && r.geom AND ST_Within(p.centroid, r.geom)",
                    None,
                ),
                [(rng.randint(1, 4000),) for _ in range(20)],
            )
        )
    if vec_row:
        queries.append(
            (
                Query(
                    "vector_knn",
                    "Ten nearest embeddings by cosine distance (HNSW, ef_search 100)",
                    "SELECT place_id FROM place_embeddings ORDER BY embedding <=> %s::vector LIMIT 10",
                    None,
                ),
                [(vec_row[0],)] * 20,
            )
        )
    return queries


def measure(conn: psycopg.Connection[Any], query: Query, params_list: list[Any]) -> dict[str, Any]:
    timings: list[float] = []
    with conn.cursor() as cur:
        cur.execute("SET hnsw.ef_search = 100")
        for params in params_list:  # warm up on the first, then time
            started = time.perf_counter()
            cur.execute(query.sql, params)
            cur.fetchall()
            timings.append((time.perf_counter() - started) * 1000)
        timings = timings[1:]
        timings.sort()
        cur.execute("EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON) " + query.sql, params_list[len(params_list) // 2])
        plan = "\n".join(r[0] for r in cur.fetchall())
    p95 = timings[int(0.95 * (len(timings) - 1))]
    target = TARGETS_MS.get(query.name)
    return {
        "name": query.name,
        "description": query.description,
        "runs": len(timings),
        "p50_ms": round(statistics.median(timings), 2),
        "p95_ms": round(p95, 2),
        "target_ms": target,
        "met": target is None or p95 <= target,
        "plan": plan,
    }


def run_all(conn: psycopg.Connection[Any], seed: int = 42) -> list[dict[str, Any]]:
    rng = random.Random(seed)  # noqa: S311
    results = []
    for query, params in build_queries(conn, rng):
        results.append(measure(conn, query, params))
        conn.rollback()
    return results


def render_markdown(results: list[dict[str, Any]], place_count: int) -> str:
    lines = [
        "# Spatial and lookup query plans",
        "",
        f"Measured on the development database with {place_count:,} places. Each query ran with up to 200",
        "different parameter sets (first run discarded as warm-up). Latency includes fetching all rows.",
        "",
        "| Query | p50 ms | p95 ms | Target p95 ms | Met |",
        "|---|---:|---:|---:|---|",
    ]
    for r in results:
        target = "" if r["target_ms"] is None else f"{r['target_ms']:.0f}"
        lines.append(f"| {r['name']} | {r['p50_ms']} | {r['p95_ms']} | {target} | {'yes' if r['met'] else 'no'} |")
    for r in results:
        lines += ["", f"## {r['name']}", "", r["description"], "", "```", r["plan"], "```"]
    return "\n".join(lines) + "\n"
