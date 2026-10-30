"""Merge staged GeoNames and Wikidata records into the unified places table.

Order of operations:
1. Insert every staged GeoNames record, with its alternate names.
2. Link Wikidata entities that carry a GeoNames ID (P1566). When several QIDs claim the same
   GeoNames ID the one with the most sitelinks wins and the rest go to the review list.
3. Match the remaining Wikidata entities to unlinked GeoNames places by normalized name
   (label or alias), country, compatible type family, and a distance threshold by type.
   Ambiguous matches and collisions are written to place_merge_review.
4. Insert what is still unmatched as Wikidata-only places, then add Wikidata labels and
   aliases.
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg

from meridian.db import etl_step
from meridian.geo import taxonomy

log = logging.getLogger("meridian.etl.merge")

# Maximum distance in km between two records of the same place, by type.
MATCH_THRESHOLD_KM: dict[str, float] = {
    **dict.fromkeys(taxonomy.FACILITY_TYPES, 3.0),
    "village": 5.0,
    "town": 10.0,
    "city": 25.0,
    "admin2": 50.0,
    "admin_region": 50.0,
    "admin1": 150.0,
    "country": 500.0,
    "river": 30.0,
    "lake": 30.0,
    "island": 30.0,
    "mountain": 30.0,
}
FAMILY: dict[str, str] = {
    **dict.fromkeys(taxonomy.FACILITY_TYPES, "facility"),
    **dict.fromkeys(taxonomy.SETTLEMENT_TYPES, "settlement"),
    **dict.fromkeys(taxonomy.ADMIN_TYPES, "admin"),
    **dict.fromkeys(taxonomy.NATURAL_TYPES, "natural"),
}
# Settlements and administrative units describe the same place from different angles: a
# Wikidata municipality is a GeoNames village, and a city can be its own second-order division.
# Only pairs from different groups are reported as type mismatches.
COMPATIBILITY_GROUP: dict[str, str] = {
    "facility": "facility",
    "settlement": "built_up",
    "admin": "built_up",
    "natural": "natural",
}
# A linked pair further apart than this multiple of the threshold is flagged for review.
LINK_DISTANCE_FACTOR = 2.0

REBUILD_GUARD_TABLES = ("mentions", "mention_candidates", "events", "exposures", "alerts", "assets")


def _fresh_tables(conn: psycopg.Connection[Any]) -> None:
    with conn.cursor() as cur:
        for table in REBUILD_GUARD_TABLES:
            cur.execute(f"SELECT EXISTS (SELECT 1 FROM {table})")  # noqa: S608
            row = cur.fetchone()
            if row and row[0]:
                raise RuntimeError(f"{table} holds data that references places; refusing to rebuild")
        cur.execute(
            "TRUNCATE place_embeddings, place_aliases, place_merge_review, place_hierarchy_issues, places "
            "RESTART IDENTITY CASCADE"
        )


def _helper_tables(conn: psycopg.Connection[Any]) -> None:
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS tmp_threshold, tmp_family, tmp_compat")
        cur.execute("CREATE TEMP TABLE tmp_threshold (type text PRIMARY KEY, km real NOT NULL)")
        cur.execute("CREATE TEMP TABLE tmp_family (type text PRIMARY KEY, family text NOT NULL)")
        cur.executemany("INSERT INTO tmp_threshold VALUES (%s, %s)", list(MATCH_THRESHOLD_KM.items()))
        cur.executemany("INSERT INTO tmp_family VALUES (%s, %s)", list(FAMILY.items()))
        cur.execute("CREATE TEMP TABLE tmp_compat (a text NOT NULL, b text NOT NULL, PRIMARY KEY (a, b))")
        cur.executemany(
            "INSERT INTO tmp_compat VALUES (%s, %s)",
            [
                (a, b)
                for a in FAMILY
                for b in FAMILY
                if COMPATIBILITY_GROUP[FAMILY[a]] == COMPATIBILITY_GROUP[FAMILY[b]]
            ],
        )
        cur.execute("DROP TABLE IF EXISTS tmp_country_qid")
        cur.execute(
            """CREATE TEMP TABLE tmp_country_qid AS
               SELECT DISTINCT ON (qid) qid, iso2 FROM (
                   SELECT wikidata_qid AS qid, iso2 FROM ref_countries
                    WHERE wikidata_qid IS NOT NULL AND iso2 IS NOT NULL
                   UNION ALL
                   SELECT w.qid, ci.iso2 FROM stg_wikidata w
                     JOIN ref_country_info ci ON ci.geonames_id = w.geonames_id
                    WHERE w.place_type = 'country'
               ) s ORDER BY qid, iso2"""
        )
        cur.execute("ALTER TABLE tmp_country_qid ADD PRIMARY KEY (qid)")


def _insert_geonames(conn: psycopg.Connection[Any]) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO places (geonames_id, name, name_normalized, type, country_code, admin1_code,
                                   admin2_code, population, lat, lon, centroid, geom, source)
               SELECT geonameid, name, name_normalized, place_type, country_code, admin1_code, admin2_code,
                      population, lat, lon, ST_SetSRID(ST_MakePoint(lon, lat), 4326),
                      ST_SetSRID(ST_MakePoint(lon, lat), 4326), 'geonames'
                 FROM stg_geonames"""
        )
        places = cur.rowcount
        cur.execute(
            """INSERT INTO place_aliases (place_id, alias, alias_normalized, language, type, source)
               SELECT p.id, a.alias, a.alias_normalized, a.language, a.kind, 'geonames'
                 FROM stg_geonames_alt a JOIN places p ON p.geonames_id = a.geonameid
                WHERE a.alias_normalized <> p.name_normalized
               ON CONFLICT DO NOTHING"""
        )
        aliases = cur.rowcount
        cur.execute("ANALYZE places")
    return {"places_geonames": places, "aliases_geonames": aliases}


def _link_by_geonames_id(conn: psycopg.Connection[Any]) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS tmp_link")
        cur.execute(
            """CREATE TEMP TABLE tmp_link AS
               SELECT DISTINCT ON (w.geonames_id) w.qid, w.geonames_id, p.id AS place_id
                 FROM stg_wikidata w JOIN places p ON p.geonames_id = w.geonames_id
                ORDER BY w.geonames_id, w.sitelinks DESC NULLS LAST, w.qid"""
        )
        cur.execute("ALTER TABLE tmp_link ADD PRIMARY KEY (qid)")
        cur.execute(
            """INSERT INTO place_merge_review (qid, geonames_id, place_id, reason, detail)
               SELECT w.qid, w.geonames_id, l.place_id, 'duplicate_geonames_link',
                      'another QID with more sitelinks claims the same GeoNames ID: ' || l.qid
                 FROM stg_wikidata w JOIN tmp_link l ON l.geonames_id = w.geonames_id
                WHERE w.qid <> l.qid"""
        )
        duplicates = cur.rowcount
        cur.execute(
            """INSERT INTO place_merge_review (qid, geonames_id, place_id, reason, distance_km, detail)
               SELECT w.qid, p.geonames_id, p.id, 'cross_link_distance',
                      ST_Distance(p.centroid::geography,
                                  ST_SetSRID(ST_MakePoint(w.lon, w.lat), 4326)::geography) / 1000.0,
                      'Wikidata and GeoNames coordinates disagree'
                 FROM tmp_link l JOIN stg_wikidata w ON w.qid = l.qid JOIN places p ON p.id = l.place_id
                 JOIN tmp_threshold t ON t.type = p.type
                WHERE ST_Distance(p.centroid::geography,
                                  ST_SetSRID(ST_MakePoint(w.lon, w.lat), 4326)::geography) / 1000.0
                      > t.km * %s""",
            (LINK_DISTANCE_FACTOR,),
        )
        far = cur.rowcount
        cur.execute(
            """INSERT INTO place_merge_review (qid, geonames_id, place_id, reason, detail)
               SELECT w.qid, p.geonames_id, p.id, 'type_mismatch', w.place_type || ' versus ' || p.type
                 FROM tmp_link l JOIN stg_wikidata w ON w.qid = l.qid JOIN places p ON p.id = l.place_id
                WHERE NOT EXISTS (SELECT 1 FROM tmp_compat c WHERE c.a = w.place_type AND c.b = p.type)"""
        )
        mismatched = cur.rowcount
        _apply_links(cur, "tmp_link", "p1566")
        cur.execute("SELECT count(*) FROM tmp_link")
        row = cur.fetchone()
    return {
        "linked_p1566": int(row[0]) if row else 0,
        "review_duplicate_links": duplicates,
        "review_far_links": far,
        "review_type_mismatch": mismatched,
    }


def _apply_links(cur: psycopg.Cursor[Any], link_table: str, method: str) -> None:
    cur.execute(
        f"""UPDATE places p
               SET qid = w.qid,
                   population = GREATEST(p.population, w.population),
                   sitelinks = w.sitelinks,
                   description = w.description,
                   website = w.website,
                   source = 'merged',
                   merge_method = %s
              FROM {link_table} l JOIN stg_wikidata w ON w.qid = l.qid
             WHERE p.id = l.place_id""",  # noqa: S608
        (method,),
    )


def _match_by_name(conn: psycopg.Connection[Any]) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS tmp_unlinked, tmp_cand, tmp_best, tmp_pick")
        cur.execute(
            """CREATE TEMP TABLE tmp_unlinked AS
               SELECT w.*, COALESCE(cq.iso2, own.iso2) AS country_code
                 FROM stg_wikidata w
                 LEFT JOIN tmp_country_qid cq ON cq.qid = w.country_qid
                 LEFT JOIN tmp_country_qid own ON own.qid = w.qid
                WHERE w.geonames_id IS NULL AND NOT EXISTS (SELECT 1 FROM tmp_link l WHERE l.qid = w.qid)"""
        )
        cur.execute(
            """CREATE TEMP TABLE tmp_cand AS
               SELECT DISTINCT ON (u.qid, p.id) u.qid, p.id AS place_id,
                      ST_Distance(p.centroid::geography,
                                  ST_SetSRID(ST_MakePoint(u.lon, u.lat), 4326)::geography) / 1000.0 AS km
                 FROM tmp_unlinked u
                 JOIN tmp_threshold t ON t.type = u.place_type
                 JOIN LATERAL (
                      SELECT id, centroid, type, country_code FROM places
                       WHERE qid IS NULL AND name_normalized = u.name_normalized
                      UNION ALL
                      SELECT p2.id, p2.centroid, p2.type, p2.country_code FROM place_aliases a
                        JOIN places p2 ON p2.id = a.place_id
                       WHERE a.alias_normalized = u.name_normalized AND p2.qid IS NULL
                 ) p ON true
                 JOIN tmp_compat cm ON cm.a = u.place_type AND cm.b = p.type
                WHERE (u.country_code IS NULL OR p.country_code IS NULL OR p.country_code = u.country_code)
                  AND ST_DWithin(p.centroid::geography,
                                 ST_SetSRID(ST_MakePoint(u.lon, u.lat), 4326)::geography, t.km * 1000.0)
                ORDER BY u.qid, p.id"""
        )
        cur.execute(
            """CREATE TEMP TABLE tmp_best AS
               SELECT DISTINCT ON (qid) qid, place_id, km, count(*) OVER (PARTITION BY qid) AS n,
                      nth_value(km, 2) OVER (PARTITION BY qid ORDER BY km
                          ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS second_km
                 FROM tmp_cand ORDER BY qid, km"""
        )
        cur.execute(
            """CREATE TEMP TABLE tmp_pick AS
               SELECT DISTINCT ON (place_id) qid, place_id, km FROM tmp_best ORDER BY place_id, km, qid"""
        )
        cur.execute("ALTER TABLE tmp_pick ADD PRIMARY KEY (qid)")
        cur.execute(
            """INSERT INTO place_merge_review (qid, place_id, reason, distance_km, detail)
               SELECT b.qid, b.place_id, 'ambiguous_match', b.km,
                      b.n || ' candidates, second nearest at ' || round(b.second_km::numeric, 1) || ' km'
                 FROM tmp_best b JOIN tmp_pick k ON k.qid = b.qid
                WHERE b.n > 1 AND b.second_km < b.km * 2 + 1"""
        )
        ambiguous = cur.rowcount
        cur.execute(
            """INSERT INTO place_merge_review (qid, place_id, reason, distance_km, detail)
               SELECT b.qid, b.place_id, 'match_collision', b.km, 'a closer entity claimed this place'
                 FROM tmp_best b WHERE NOT EXISTS (SELECT 1 FROM tmp_pick k WHERE k.qid = b.qid)"""
        )
        collisions = cur.rowcount
        _apply_links(cur, "tmp_pick", "name_country_proximity")
        cur.execute("SELECT count(*) FROM tmp_pick")
        row = cur.fetchone()
    return {
        "matched_by_name": int(row[0]) if row else 0,
        "review_ambiguous": ambiguous,
        "review_collisions": collisions,
    }


def _insert_wikidata_only(conn: psycopg.Connection[Any]) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO places (qid, geonames_id, name, name_normalized, type, country_code, population,
                                   lat, lon, centroid, geom, sitelinks, description, website, source, merge_method)
               SELECT w.qid,
                      CASE WHEN w.geonames_id IS NOT NULL AND w.rn = 1 THEN w.geonames_id END,
                      w.name, w.name_normalized,
                      CASE WHEN w.place_type IN ('city', 'town', 'village') AND w.population IS NOT NULL
                           THEN CASE WHEN w.population >= %s THEN 'city'
                                     WHEN w.population >= %s THEN 'town' ELSE 'village' END
                           ELSE w.place_type END,
                      COALESCE(cq.iso2, own.iso2), w.population, w.lat, w.lon,
                      ST_SetSRID(ST_MakePoint(w.lon, w.lat), 4326), ST_SetSRID(ST_MakePoint(w.lon, w.lat), 4326),
                      w.sitelinks, w.description, w.website, 'wikidata', 'wikidata_only'
                 FROM (SELECT s.*, row_number() OVER (PARTITION BY geonames_id
                                                      ORDER BY sitelinks DESC NULLS LAST, qid) AS rn
                         FROM stg_wikidata s) w
                 LEFT JOIN tmp_country_qid cq ON cq.qid = w.country_qid
                 LEFT JOIN tmp_country_qid own ON own.qid = w.qid
                WHERE NOT EXISTS (SELECT 1 FROM tmp_link l WHERE l.qid = w.qid)
                  AND NOT EXISTS (SELECT 1 FROM tmp_pick k WHERE k.qid = w.qid)""",
            (taxonomy.CITY_MIN_POPULATION, taxonomy.TOWN_MIN_POPULATION),
        )
        inserted = cur.rowcount
        cur.execute(
            """INSERT INTO place_aliases (place_id, alias, alias_normalized, language, type, source)
               SELECT DISTINCT p.id, n.text, n.text_normalized, n.language, n.kind, 'wikidata'
                 FROM stg_wd_names n JOIN places p ON p.qid = n.qid
                WHERE n.kind IN ('label', 'alias') AND n.text_normalized <> ''
                  AND n.text_normalized <> p.name_normalized
                  AND NOT EXISTS (SELECT 1 FROM place_aliases x
                                   WHERE x.place_id = p.id AND x.alias_normalized = n.text_normalized
                                     AND x.language IS NOT DISTINCT FROM n.language)
               ON CONFLICT DO NOTHING"""
        )
        aliases = cur.rowcount
        cur.execute("ANALYZE places")
        cur.execute("ANALYZE place_aliases")
    return {"places_wikidata_only": inserted, "aliases_wikidata": aliases}


def run(conn: psycopg.Connection[Any], force: bool = False) -> None:
    with etl_step(conn, "merge") as stats:
        if not force:
            _fresh_tables(conn)
        else:
            with conn.cursor() as cur:
                cur.execute(
                    "TRUNCATE place_embeddings, place_aliases, place_merge_review, place_hierarchy_issues, "
                    "places RESTART IDENTITY CASCADE"
                )
        _helper_tables(conn)
        stats.update(_insert_geonames(conn))
        stats.update(_link_by_geonames_id(conn))
        stats.update(_match_by_name(conn))
        stats.update(_insert_wikidata_only(conn))
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*), count(qid), count(geonames_id), count(*) FILTER (WHERE source = 'merged') FROM places"
            )
            row = cur.fetchone()
        if row:
            stats.update(places_total=row[0], with_qid=row[1], with_geonames_id=row[2], merged=row[3])
