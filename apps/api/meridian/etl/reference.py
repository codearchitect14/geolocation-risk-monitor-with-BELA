"""Load reference data: country info, Natural Earth polygons, and uncertainty rules."""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any

import psycopg

from meridian.config import get_settings
from meridian.db import copy_rows, etl_step
from meridian.geo import taxonomy

log = logging.getLogger("meridian.etl.reference")


def _int(value: Any) -> int | None:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def load_country_info(conn: psycopg.Connection[Any], path: Path | None = None) -> int:
    """Load GeoNames countryInfo.txt into ref_country_info."""
    source = path or get_settings().data_dir / "raw" / "gazetteer" / "geonames" / "countryInfo.txt"
    rows = []
    with source.open(encoding="utf-8") as handle:
        for record in csv.reader((line for line in handle if not line.startswith("#")), delimiter="\t"):
            if len(record) < 17 or len(record[0]) != 2:
                continue
            rows.append(
                (
                    record[0],
                    record[1],
                    record[4],
                    record[5] or None,
                    record[8] or None,
                    _int(record[16]),
                    record[15] or None,
                    _int(record[7]),
                )
            )
    with conn.cursor() as cur:
        cur.execute("TRUNCATE ref_country_info")
    copy_rows(
        conn,
        "ref_country_info",
        ["iso2", "iso3", "name", "capital", "continent", "geonames_id", "languages", "population"],
        rows,
    )
    return len(rows)


def _features(path: Path) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))["features"]
    return features


def _prop(props: dict[str, Any], *names: str) -> Any:
    lowered = {k.lower(): v for k, v in props.items()}
    for name in names:
        if lowered.get(name.lower()) not in (None, "", -99, "-99", -1, 0):
            return lowered[name.lower()]
    return None


def _geometry_json(feature: dict[str, Any]) -> str:
    return json.dumps(feature["geometry"])


def load_boundaries(conn: psycopg.Connection[Any], root: Path | None = None) -> dict[str, int]:
    """Load Natural Earth country and admin-1 polygons."""
    base = root or get_settings().data_dir / "raw" / "boundaries" / "natural_earth"
    countries = _features(base / "ne_10m_admin_0_countries" / "ne_10m_admin_0_countries.geojson")
    admin1 = _features(base / "ne_10m_admin_1_states_provinces" / "ne_10m_admin_1_states_provinces.geojson")
    with conn.cursor() as cur:
        cur.execute("TRUNCATE ref_countries, ref_admin1 RESTART IDENTITY")
        for feature in countries:
            props = feature["properties"]
            iso2 = _prop(props, "ISO_A2_EH", "ISO_A2")
            cur.execute(
                """INSERT INTO ref_countries (iso2, adm0_a3, name, wikidata_qid, geom)
                   VALUES (%s, %s, %s, %s, ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)))""",
                (
                    iso2 if isinstance(iso2, str) and len(iso2) == 2 else None,
                    _prop(props, "ADM0_A3") or "",
                    _prop(props, "NAME") or "",
                    _prop(props, "WIKIDATAID"),
                    _geometry_json(feature),
                ),
            )
        for feature in admin1:
            props = feature["properties"]
            iso2 = _prop(props, "iso_a2")
            cur.execute(
                """INSERT INTO ref_admin1 (iso2, adm1_code, iso_3166_2, name, geonames_id, wikidata_qid, geom)
                   VALUES (%s, %s, %s, %s, %s, %s, ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)))""",
                (
                    iso2 if isinstance(iso2, str) and len(iso2) == 2 else None,
                    _prop(props, "adm1_code"),
                    _prop(props, "iso_3166_2"),
                    _prop(props, "name") or "",
                    _int(_prop(props, "gn_id")),
                    _prop(props, "wikidataid"),
                    _geometry_json(feature),
                ),
            )
        cur.execute("ANALYZE ref_countries")
        cur.execute("ANALYZE ref_admin1")
    return {"countries": len(countries), "admin1": len(admin1)}


def seed_uncertainty_rules(conn: psycopg.Connection[Any]) -> int:
    """Insert default uncertainty rules. Existing rows are left alone so edits persist."""
    with conn.cursor() as cur:
        for rule in taxonomy.DEFAULT_UNCERTAINTY_RULES:
            cur.execute(
                """INSERT INTO place_uncertainty_rules
                   (place_type, min_population, uncertainty_km, location_level, polygon_based, country_level)
                   VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                rule,
            )
        cur.execute("SELECT count(*) FROM place_uncertainty_rules")
        row = cur.fetchone()
    return int(row[0]) if row else 0


def run(conn: psycopg.Connection[Any]) -> None:
    with etl_step(conn, "reference") as stats:
        stats["countries_info"] = load_country_info(conn)
        stats.update(load_boundaries(conn))
        stats["uncertainty_rules"] = seed_uncertainty_rules(conn)
