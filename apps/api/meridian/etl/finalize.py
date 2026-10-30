"""Assign uncertainty radii, polygons, bounding boxes, and H3 cells to places."""

from __future__ import annotations

import logging
from typing import Any

import h3
import psycopg

from meridian.db import copy_rows, etl_step

log = logging.getLogger("meridian.etl.finalize")

H3_RESOLUTION = 7
CHUNK = 200_000


def assign_uncertainty(conn: psycopg.Connection[Any]) -> int:
    """Pick the rule with the highest min_population not above the place population."""
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE places p
                  SET uncertainty_km = r.uncertainty_km, location_level = r.location_level,
                      country_level = r.country_level
                 FROM place_uncertainty_rules r
                WHERE r.place_type = p.type
                  AND r.min_population = (SELECT max(x.min_population) FROM place_uncertainty_rules x
                                           WHERE x.place_type = p.type
                                             AND x.min_population <= COALESCE(p.population, 0))"""
        )
        return cur.rowcount


def attach_polygons(conn: psycopg.Connection[Any]) -> dict[str, int]:
    """Use Natural Earth polygons for countries and admin-1 regions."""
    with conn.cursor() as cur:
        cur.execute("UPDATE places SET geom = centroid, has_polygon = false WHERE has_polygon")
        cur.execute(
            """UPDATE places p SET geom = r.geom, has_polygon = true
                 FROM (SELECT DISTINCT ON (iso2) iso2, geom FROM ref_countries
                        WHERE iso2 IS NOT NULL ORDER BY iso2, ST_Area(geom) DESC) r
                WHERE p.type = 'country' AND p.country_code = r.iso2"""
        )
        countries = cur.rowcount
        cur.execute("DROP TABLE IF EXISTS tmp_admin1_used")
        cur.execute(
            """CREATE TEMP TABLE tmp_admin1_used AS
               SELECT r.ne_id, p.id AS place_id FROM places p JOIN ref_admin1 r
                 ON ((r.geonames_id IS NOT NULL AND p.geonames_id = r.geonames_id)
                     OR (r.wikidata_qid IS NOT NULL AND p.qid = r.wikidata_qid))
                WHERE p.type = 'admin1'"""
        )
        cur.execute(
            """UPDATE places p SET geom = r.geom, has_polygon = true
                 FROM tmp_admin1_used u JOIN ref_admin1 r ON r.ne_id = u.ne_id
                WHERE p.id = u.place_id"""
        )
        admin1 = cur.rowcount
        # Fallback: the unclaimed polygon of the same country that contains the place's point.
        cur.execute(
            """UPDATE places p SET geom = r.geom, has_polygon = true
                 FROM ref_admin1 r
                WHERE p.type = 'admin1' AND NOT p.has_polygon AND r.iso2 = p.country_code
                  AND NOT EXISTS (SELECT 1 FROM tmp_admin1_used u WHERE u.ne_id = r.ne_id)
                  AND ST_Within(p.centroid, r.geom)"""
        )
        admin1_by_point = cur.rowcount
    return {"polygon_countries": countries, "polygon_admin1": admin1, "polygon_admin1_by_point": admin1_by_point}


def assign_bboxes(conn: psycopg.Connection[Any]) -> None:
    """Bounding box of the polygon, or of the uncertainty circle for point places."""
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE places SET
                   bbox_west = ST_XMin(geom), bbox_south = ST_YMin(geom),
                   bbox_east = ST_XMax(geom), bbox_north = ST_YMax(geom)
                WHERE has_polygon"""
        )
        cur.execute(
            """UPDATE places SET
                   bbox_west = lon - COALESCE(uncertainty_km, 0) / (111.32 * GREATEST(cos(radians(lat)), 0.05)),
                   bbox_east = lon + COALESCE(uncertainty_km, 0) / (111.32 * GREATEST(cos(radians(lat)), 0.05)),
                   bbox_south = lat - COALESCE(uncertainty_km, 0) / 110.57,
                   bbox_north = lat + COALESCE(uncertainty_km, 0) / 110.57
                WHERE NOT has_polygon"""
        )


def assign_h3(conn: psycopg.Connection[Any]) -> int:
    """Compute the H3 cell of every place. Rows are read and written in chunks because a
    connection cannot fetch from a cursor while a COPY is in progress."""
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS tmp_h3")
        cur.execute("CREATE TEMP TABLE tmp_h3 (id bigint PRIMARY KEY, cell bigint NOT NULL)")
    total = 0
    with conn.cursor(name="h3_cursor") as reader:
        reader.execute("SELECT id, lat, lon FROM places")
        while True:
            chunk = reader.fetchmany(CHUNK)
            if not chunk:
                break
            rows = [(pid, h3.str_to_int(h3.latlng_to_cell(lat, lon, H3_RESOLUTION))) for pid, lat, lon in chunk]
            total += copy_rows(conn, "tmp_h3", ["id", "cell"], rows)
    with conn.cursor() as cur:
        cur.execute("UPDATE places p SET h3_cell = t.cell FROM tmp_h3 t WHERE p.id = t.id")
    return total


def run(conn: psycopg.Connection[Any]) -> None:
    with etl_step(conn, "finalize") as stats:
        stats["uncertainty_assigned"] = assign_uncertainty(conn)
        stats.update(attach_polygons(conn))
        assign_bboxes(conn)
        stats["h3_cells"] = assign_h3(conn)
        with conn.cursor() as cur:
            cur.execute("ANALYZE places")
