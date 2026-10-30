"""Build the administrative hierarchy (place, admin-2, admin-1, country) and validate it.

Parent resolution, in order:
1. GeoNames codes: a place's admin-2 code, then its admin-1 code.
2. Wikidata located-in (P131) when the parent entity is one of our places.
3. Containment in a Natural Earth admin-1 polygon.
4. The country named by the place's country code, then containment in a country polygon.

Afterwards cycles and inconsistent parents are detected and written to place_hierarchy_issues.
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg

from meridian.db import etl_step

log = logging.getLogger("meridian.etl.hierarchy")

# Higher rank is higher in the hierarchy. A parent must not rank below its child. Settlements and
# municipalities share a rank because the sources use them interchangeably.
RANK: dict[str, int] = {
    "country": 6,
    "admin1": 5,
    "admin2": 4,
    "admin_region": 3,
    "city": 3,
    "town": 3,
    "village": 3,
}
DEFAULT_RANK = 2


def _assign_parents(conn: psycopg.Connection[Any]) -> dict[str, int]:
    stats: dict[str, int] = {}
    with conn.cursor() as cur:
        cur.execute("UPDATE places SET parent_place_id = NULL")
        # 1. GeoNames codes
        cur.execute(
            """UPDATE places c SET parent_place_id = p.id
                 FROM places p
                WHERE c.type NOT IN ('country', 'admin1') AND c.type <> 'admin2'
                  AND p.type = 'admin2' AND p.country_code = c.country_code
                  AND p.admin1_code = c.admin1_code AND p.admin2_code = c.admin2_code
                  AND c.admin1_code IS NOT NULL AND c.admin2_code IS NOT NULL"""
        )
        stats["parent_admin2"] = cur.rowcount
        cur.execute(
            """UPDATE places c SET parent_place_id = p.id
                 FROM places p
                WHERE c.parent_place_id IS NULL AND c.type NOT IN ('country', 'admin1')
                  AND p.type = 'admin1' AND p.country_code = c.country_code
                  AND p.admin1_code = c.admin1_code AND c.admin1_code IS NOT NULL
                  AND (c.type <> 'admin2' OR c.admin2_code IS NOT NULL)"""
        )
        stats["parent_admin1"] = cur.rowcount
        # 2. Wikidata P131
        cur.execute(
            """UPDATE places c SET parent_place_id = sub.parent_id
                 FROM (SELECT DISTINCT ON (w.qid) w.qid, p.id AS parent_id
                         FROM stg_wikidata w
                         CROSS JOIN LATERAL unnest(w.admin_parent_qids) WITH ORDINALITY AS u(pq, ord)
                         JOIN places p ON p.qid = u.pq AND p.qid <> w.qid
                        ORDER BY w.qid, u.ord) sub
                WHERE c.qid = sub.qid AND c.parent_place_id IS NULL AND c.type <> 'country'"""
        )
        stats["parent_p131"] = cur.rowcount
        # 3. Spatial containment
        cur.execute(
            """UPDATE places c SET parent_place_id = p.id
                 FROM ref_admin1 r JOIN places p ON p.type = 'admin1'
                      AND ((r.geonames_id IS NOT NULL AND p.geonames_id = r.geonames_id)
                           OR (r.wikidata_qid IS NOT NULL AND p.qid = r.wikidata_qid))
                WHERE c.parent_place_id IS NULL AND c.type NOT IN ('country', 'admin1')
                  AND ST_Within(c.centroid, r.geom)"""
        )
        stats["parent_admin1_polygon"] = cur.rowcount
        cur.execute(
            """UPDATE places c SET parent_place_id = p.id
                 FROM places p
                WHERE c.parent_place_id IS NULL AND c.type <> 'country'
                  AND p.type = 'country' AND p.country_code = c.country_code"""
        )
        stats["parent_country_by_code"] = cur.rowcount
        cur.execute(
            """UPDATE places c SET parent_place_id = p.id
                 FROM ref_countries r JOIN places p ON p.type = 'country' AND p.country_code = r.iso2
                WHERE c.parent_place_id IS NULL AND c.type <> 'country' AND r.iso2 IS NOT NULL
                  AND ST_Within(c.centroid, r.geom)"""
        )
        stats["parent_country_polygon"] = cur.rowcount
        # Fill a missing country code from the parent chain when the parent is a country.
        cur.execute(
            """UPDATE places c SET country_code = p.country_code
                 FROM places p WHERE c.parent_place_id = p.id AND c.country_code IS NULL
                  AND p.country_code IS NOT NULL"""
        )
        stats["country_from_parent"] = cur.rowcount
    return stats


def _ancestor_join(depth: int) -> str:
    """FROM clause fragment that walks depth + 1 parent links from a child alias c."""
    joins = "places p0"
    for i in range(1, depth + 1):
        joins += f" JOIN places p{i} ON p{i}.id = p{i - 1}.parent_place_id"
    return joins


def _fill_names(conn: psycopg.Connection[Any]) -> None:
    """Set admin1_name and admin2_name from the ancestor chain (up to three levels)."""
    with conn.cursor() as cur:
        cur.execute("UPDATE places SET admin1_name = NULL, admin2_name = NULL")
        for column, ancestor_type, depths in (("admin1_name", "admin1", 3), ("admin2_name", "admin2", 2)):
            for depth in range(depths):
                cur.execute(
                    f"""UPDATE places c SET {column} = p{depth}.name
                          FROM {_ancestor_join(depth)}
                         WHERE c.parent_place_id = p0.id AND p{depth}.type = '{ancestor_type}'
                           AND c.{column} IS NULL"""  # noqa: S608
                )
        cur.execute("UPDATE places SET admin1_name = name WHERE type = 'admin1'")
        cur.execute("UPDATE places SET admin2_name = name WHERE type = 'admin2'")


def find_cycles(edges: dict[int, int]) -> list[list[int]]:
    """Return the cycles in a child to parent mapping. Each node is visited once."""
    state: dict[int, int] = {}  # 1 on the current walk, 2 finished
    cycles: list[list[int]] = []
    for start in edges:
        if state.get(start):
            continue
        path: list[int] = []
        node: int | None = start
        while node is not None and state.get(node) is None:
            state[node] = 1
            path.append(node)
            node = edges.get(node)
        if node is not None and state.get(node) == 1:
            cycles.append(path[path.index(node) :])
        for visited in path:
            state[visited] = 2
    return cycles


def _validate(conn: psycopg.Connection[Any]) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("TRUNCATE place_hierarchy_issues")
        cur.execute("SELECT id, parent_place_id FROM places WHERE parent_place_id IS NOT NULL")
        edges = {int(child): int(parent) for child, parent in cur.fetchall()}
        cycles = find_cycles(edges)
        for cycle in cycles:
            breaker = cycle[0]
            cur.execute(
                "INSERT INTO place_hierarchy_issues (place_id, parent_id, issue, detail) VALUES (%s, %s, 'cycle', %s)",
                (breaker, edges[breaker], "cycle through " + " > ".join(map(str, cycle))),
            )
            cur.execute("UPDATE places SET parent_place_id = NULL WHERE id = %s", (breaker,))
        cur.execute(
            """INSERT INTO place_hierarchy_issues (place_id, parent_id, issue, detail)
               SELECT c.id, p.id, 'country_mismatch', c.country_code || ' child under ' || p.country_code || ' parent'
                 FROM places c JOIN places p ON p.id = c.parent_place_id
                WHERE c.country_code IS NOT NULL AND p.country_code IS NOT NULL
                  AND c.country_code <> p.country_code"""
        )
        mismatched = cur.rowcount
        rank_case = (
            "CASE {t} " + " ".join(f"WHEN '{k}' THEN {v}" for k, v in RANK.items()) + f" ELSE {DEFAULT_RANK} END"
        )
        cur.execute(
            f"""INSERT INTO place_hierarchy_issues (place_id, parent_id, issue, detail)
                SELECT c.id, p.id, 'parent_not_higher', c.type || ' under ' || p.type
                  FROM places c JOIN places p ON p.id = c.parent_place_id
                 WHERE {rank_case.format(t="p.type")} < {rank_case.format(t="c.type")}"""  # noqa: S608
        )
        inverted = cur.rowcount
        cur.execute("SELECT count(*) FROM places WHERE parent_place_id IS NULL AND type <> 'country'")
        row = cur.fetchone()
    return {
        "cycles": len(cycles),
        "issue_country_mismatch": mismatched,
        "issue_parent_not_higher": inverted,
        "orphans": int(row[0]) if row else 0,
    }


def run(conn: psycopg.Connection[Any]) -> None:
    with etl_step(conn, "hierarchy") as stats:
        stats.update(_assign_parents(conn))
        _fill_names(conn)
        stats.update(_validate(conn))
        with conn.cursor() as cur:
            cur.execute("ANALYZE places")
