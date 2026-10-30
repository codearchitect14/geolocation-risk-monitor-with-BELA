"""Data quality checks for the place knowledge base: SQL assertions and pandera schemas."""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

import pandas as pd
import pandera.pandas as pa
import psycopg

from meridian.config import get_settings
from meridian.etl.hierarchy import find_cycles
from meridian.geo import taxonomy

log = logging.getLogger("meridian.etl.quality")

PLACE_SAMPLE_SCHEMA = pa.DataFrameSchema(
    {
        "id": pa.Column(int, unique=True),
        "name": pa.Column(str, pa.Check.str_length(min_value=1)),
        "name_normalized": pa.Column(str, pa.Check.str_length(min_value=1)),
        "type": pa.Column(str, pa.Check.isin(taxonomy.PLACE_TYPES)),
        "lat": pa.Column(float, pa.Check.in_range(-90, 90)),
        "lon": pa.Column(float, pa.Check.in_range(-180, 180)),
        "country_code": pa.Column(str, pa.Check.str_matches(r"^[A-Z]{2}$"), nullable=True),
        "uncertainty_km": pa.Column(float, pa.Check.gt(0)),
        "location_level": pa.Column(str, pa.Check.isin(taxonomy.LOCATION_LEVELS)),
    },
    strict=False,
)


def _scalar(cur: psycopg.Cursor[Any], query: str) -> int:
    cur.execute(query)
    row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _rows(cur: psycopg.Cursor[Any], query: str) -> list[tuple[Any, ...]]:
    cur.execute(query)
    return cur.fetchall()


def country_outliers(cur: psycopg.Cursor[Any], limit: int = 200) -> tuple[int, list[tuple[Any, ...]]]:
    """Places whose point lies more than 25 km outside the polygon of their stated country."""
    cur.execute("DROP TABLE IF EXISTS tmp_outliers")
    cur.execute(
        """CREATE TEMP TABLE tmp_outliers AS
           SELECT o.id, o.country_code, o.name, o.type, o.lat, o.lon, o.source FROM (
               SELECT p.id, p.country_code, p.name, p.type, p.lat, p.lon, p.source, p.centroid FROM places p
                WHERE p.type <> 'country' AND p.country_code IN (SELECT iso2 FROM ref_countries WHERE iso2 IS NOT NULL)
                  AND NOT EXISTS (SELECT 1 FROM ref_countries r WHERE r.iso2 = p.country_code
                                   AND ST_Within(p.centroid, r.geom))) o
            WHERE NOT EXISTS (SELECT 1 FROM ref_countries r WHERE r.iso2 = o.country_code
                               AND ST_DWithin(r.geom, o.centroid, 0.5)
                               AND ST_DWithin(r.geom::geography, o.centroid::geography, 25000))"""
    )
    total = _scalar(cur, "SELECT count(*) FROM tmp_outliers")
    sample = _rows(
        cur,
        f"SELECT id, country_code, name, type, lat, lon, source FROM tmp_outliers ORDER BY id LIMIT {limit}",  # noqa: S608
    )
    return total, sample


def run_checks(conn: psycopg.Connection[Any], write_outliers: bool = True) -> dict[str, Any]:
    result: dict[str, Any] = {}
    with conn.cursor() as cur:
        total = _scalar(cur, "SELECT count(*) FROM places")
        result["places_total"] = total
        result["by_source"] = dict(_rows(cur, "SELECT source, count(*) FROM places GROUP BY 1 ORDER BY 2 DESC"))
        result["by_type"] = dict(_rows(cur, "SELECT type, count(*) FROM places GROUP BY 1 ORDER BY 2 DESC"))

        failures: dict[str, int] = {
            "invalid_coordinates": _scalar(
                cur, "SELECT count(*) FROM places WHERE lat NOT BETWEEN -90 AND 90 OR lon NOT BETWEEN -180 AND 180"
            ),
            "centroid_differs_from_lat_lon": _scalar(
                cur,
                "SELECT count(*) FROM places WHERE abs(ST_Y(centroid) - lat) > 1e-9 OR abs(ST_X(centroid) - lon) > 1e-9",
            ),
            "unknown_country_code": _scalar(
                cur,
                "SELECT count(*) FROM places WHERE country_code IS NOT NULL AND country_code NOT IN (SELECT iso2 FROM ref_country_info)",
            ),
            "missing_type": _scalar(cur, "SELECT count(*) FROM places WHERE type IS NULL OR type = ''"),
            "missing_country": _scalar(cur, "SELECT count(*) FROM places WHERE country_code IS NULL"),
            "duplicate_qid": _scalar(cur, "SELECT count(qid) - count(DISTINCT qid) FROM places"),
            "duplicate_geonames_id": _scalar(
                cur, "SELECT count(geonames_id) - count(DISTINCT geonames_id) FROM places"
            ),
            "missing_uncertainty": _scalar(cur, "SELECT count(*) FROM places WHERE uncertainty_km IS NULL"),
            "missing_h3": _scalar(cur, "SELECT count(*) FROM places WHERE h3_cell IS NULL"),
            "missing_bbox": _scalar(cur, "SELECT count(*) FROM places WHERE bbox_west IS NULL"),
            "hierarchy_cycles": len(
                find_cycles(
                    {
                        int(c): int(p)
                        for c, p in _rows(
                            cur, "SELECT id, parent_place_id FROM places WHERE parent_place_id IS NOT NULL"
                        )
                    }
                )
            ),
            "hierarchy_country_mismatch": _scalar(
                cur, "SELECT count(*) FROM place_hierarchy_issues WHERE issue = 'country_mismatch'"
            ),
            "hierarchy_parent_not_higher": _scalar(
                cur, "SELECT count(*) FROM place_hierarchy_issues WHERE issue = 'parent_not_higher'"
            ),
            "polygon_places_without_polygon": _scalar(
                cur,
                """SELECT count(*) FROM places p JOIN place_uncertainty_rules r
                          ON r.place_type = p.type AND r.min_population = 0
                         WHERE r.polygon_based AND p.type IN ('country', 'admin1') AND NOT p.has_polygon""",
            ),
            "wrong_vector_dimension": _scalar(
                cur, "SELECT count(*) FROM place_embeddings WHERE vector_dims(embedding) <> 1024"
            ),
        }
        outliers, sample = country_outliers(cur)
        failures["outside_country_polygon_25km"] = outliers
        result["checks"] = failures
        result["outlier_sample_size"] = len(sample)

        # Hard requirements fail the run; the rest are reported as flags for review.
        hard = (
            "invalid_coordinates",
            "centroid_differs_from_lat_lon",
            "unknown_country_code",
            "missing_type",
            "duplicate_qid",
            "duplicate_geonames_id",
            "missing_uncertainty",
            "missing_h3",
            "missing_bbox",
            "hierarchy_cycles",
            "wrong_vector_dimension",
        )
        result["hard_failures"] = {k: v for k, v in failures.items() if k in hard and v}
        result["flags"] = {k: v for k, v in failures.items() if k not in hard and v}

        result["cross_links"] = {
            "geonames_places_with_qid": _scalar(
                cur, "SELECT count(*) FROM places WHERE geonames_id IS NOT NULL AND qid IS NOT NULL"
            ),
            "geonames_places_total": _scalar(cur, "SELECT count(*) FROM places WHERE geonames_id IS NOT NULL"),
            "wikidata_places_with_geonames_id": _scalar(
                cur, "SELECT count(*) FROM places WHERE qid IS NOT NULL AND geonames_id IS NOT NULL"
            ),
            "wikidata_places_total": _scalar(cur, "SELECT count(*) FROM places WHERE qid IS NOT NULL"),
            "merged_by_p1566": _scalar(cur, "SELECT count(*) FROM places WHERE merge_method = 'p1566'"),
            "merged_by_name_country_proximity": _scalar(
                cur, "SELECT count(*) FROM places WHERE merge_method = 'name_country_proximity'"
            ),
            "geonames_subset_total": _scalar(cur, "SELECT count(*) FROM places WHERE source IN ('geonames', 'merged')"),
            "geonames_subset_with_qid": _scalar(cur, "SELECT count(*) FROM places WHERE source = 'merged'"),
            "wikidata_without_geonames_link": _scalar(
                cur, "SELECT count(*) FROM places WHERE merge_method = 'wikidata_only'"
            ),
        }
        cross = result["cross_links"]
        cross["geonames_subset_qid_coverage"] = round(
            cross["geonames_subset_with_qid"] / max(cross["geonames_subset_total"], 1), 4
        )
        cross["geonames_qid_coverage"] = round(
            cross["geonames_places_with_qid"] / max(cross["geonames_places_total"], 1), 4
        )
        cross["wikidata_geonames_coverage"] = round(
            cross["wikidata_places_with_geonames_id"] / max(cross["wikidata_places_total"], 1), 4
        )
        result["cross_links_by_type"] = [
            {"type": t, "places": n, "with_qid": q, "with_geonames_id": g}
            for t, n, q, g in _rows(
                cur,
                """SELECT type, count(*), count(qid), count(geonames_id) FROM places
                                              GROUP BY type ORDER BY count(*) DESC""",
            )
        ]
        result["merge_review"] = dict(
            _rows(cur, "SELECT reason, count(*) FROM place_merge_review GROUP BY 1 ORDER BY 2 DESC")
        )

        aliases = _scalar(cur, "SELECT count(*) FROM place_aliases")
        with_alias = _scalar(cur, "SELECT count(DISTINCT place_id) FROM place_aliases")
        result["aliases"] = {
            "total": aliases,
            "places_with_alias": with_alias,
            "mean_per_place": round(aliases / max(total, 1), 2),
            "by_language": dict(
                _rows(
                    cur,
                    "SELECT coalesce(language, '(none)'), count(*) FROM place_aliases GROUP BY 1 ORDER BY 2 DESC LIMIT 20",
                )
            ),
            "by_type": dict(_rows(cur, "SELECT type, count(*) FROM place_aliases GROUP BY 1 ORDER BY 2 DESC")),
        }
        result["embeddings"] = {
            "rows": _scalar(cur, "SELECT count(*) FROM place_embeddings"),
            "places": _scalar(cur, "SELECT count(DISTINCT place_id) FROM place_embeddings"),
            "by_kind": dict(_rows(cur, "SELECT kind, count(*) FROM place_embeddings GROUP BY 1")),
        }
        result["uncertainty_km"] = {
            t: float(km)
            for t, km in _rows(
                cur, "SELECT type, round(avg(uncertainty_km)::numeric, 1) FROM places GROUP BY 1 ORDER BY 1"
            )
        }
        result["polygons"] = {
            "with_polygon": _scalar(cur, "SELECT count(*) FROM places WHERE has_polygon"),
            "country_level": _scalar(cur, "SELECT count(*) FROM places WHERE country_level"),
        }

        sample_frame = pd.DataFrame(
            _rows(
                cur,
                """SELECT id, name, name_normalized, type, lat, lon, country_code, uncertainty_km::float8,
                                 location_level FROM places ORDER BY random() LIMIT 20000""",
            ),
            columns=[
                "id",
                "name",
                "name_normalized",
                "type",
                "lat",
                "lon",
                "country_code",
                "uncertainty_km",
                "location_level",
            ],
        )
        try:
            PLACE_SAMPLE_SCHEMA.validate(sample_frame, lazy=True)
            result["pandera_sample"] = {"rows": len(sample_frame), "valid": True}
        except pa.errors.SchemaErrors as exc:
            result["pandera_sample"] = {
                "rows": len(sample_frame),
                "valid": False,
                "failure_cases": exc.failure_cases.head(20).to_dict("records"),
            }
    if write_outliers:
        out = get_settings().data_dir / "processed" / "place_outliers.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["id", "country_code", "name", "type", "lat", "lon", "source"])
            writer.writerows(sample)
        result["outlier_file"] = (
            str(Path(out).relative_to(get_settings().data_dir.parent))
            if out.is_relative_to(get_settings().data_dir.parent)
            else str(out)
        )
    return result
