"""Stage GeoNames records and alternate names.

allCountries.txt columns: geonameid, name, asciiname, alternatenames, latitude, longitude,
feature class, feature code, country code, cc2, admin1, admin2, admin3, admin4, population,
elevation, dem, timezone, modification date.

alternateNamesV2.txt columns: alternateNameId, geonameid, isolanguage, alternate name,
isPreferredName, isShortName, isColloquial, isHistoric, from, to.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import psycopg

from meridian.config import get_settings
from meridian.db import copy_rows, etl_step
from meridian.geo import taxonomy
from meridian.geo.names import normalize_name

log = logging.getLogger("meridian.etl.geonames")

DEFAULT_LANGUAGES = frozenset(
    {"en", "es", "fr", "de", "pt", "it", "ru", "ar", "zh", "ja", "tr", "nl", "pl", "uk", "id", "hi"}
)

STAGING_DDL = """
DROP TABLE IF EXISTS stg_geonames, stg_geonames_alt;
CREATE UNLOGGED TABLE stg_geonames (
    geonameid bigint PRIMARY KEY, name text NOT NULL, name_normalized text NOT NULL,
    lat double precision NOT NULL, lon double precision NOT NULL,
    feature_class char(1) NOT NULL, feature_code text NOT NULL, place_type text NOT NULL,
    country_code char(2), admin1_code text, admin2_code text, population bigint
);
CREATE UNLOGGED TABLE stg_geonames_alt (
    geonameid bigint NOT NULL, language text, alias text NOT NULL, alias_normalized text NOT NULL,
    kind text NOT NULL
);
"""


def geonames_dir() -> Path:
    return get_settings().data_dir / "raw" / "gazetteer" / "geonames"


def parse_places(
    lines: Iterable[str], min_population: int, include_minor_facilities: bool = False
) -> Iterator[tuple[Any, ...]]:
    """Yield staging rows for records inside the project scope."""
    for line in lines:
        cols = line.rstrip("\n").split("\t")
        if len(cols) < 15:
            continue
        try:
            population = int(cols[14] or 0)
            lat, lon = float(cols[4]), float(cols[5])
        except ValueError:
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        place_type = taxonomy.geonames_type(cols[6], cols[7], population)
        if place_type is None:
            continue
        if place_type in taxonomy.MINOR_FACILITY_TYPES and not include_minor_facilities:
            continue
        if place_type in taxonomy.SETTLEMENT_TYPES and population < min_population:
            continue
        name = cols[1].strip()
        normalized = normalize_name(name)
        if not name or not normalized:
            continue
        yield (
            int(cols[0]),
            name,
            normalized,
            lat,
            lon,
            cols[6],
            cols[7],
            place_type,
            cols[8] or None,
            cols[10] or None,
            cols[11] or None,
            population or None,
        )


def parse_alternates(lines: Iterable[str], wanted: set[int], languages: frozenset[str]) -> Iterator[tuple[Any, ...]]:
    for line in lines:
        cols = line.rstrip("\n").split("\t")
        if len(cols) < 8:
            continue
        try:
            geonameid = int(cols[1])
        except ValueError:
            continue
        if geonameid not in wanted:
            continue
        language, alias = cols[2], cols[3].strip()
        if not alias:
            continue
        if language in taxonomy.ALIAS_CODE_LANGUAGES:
            kind, language_value = taxonomy.ALIAS_CODE_LANGUAGES[language], None
        elif language == "" or language in languages:
            language_value = language or None
            kind = (
                "historic"
                if cols[7] == "1"
                else "preferred"
                if cols[4] == "1"
                else "short"
                if cols[5] == "1"
                else "alias"
            )
        else:
            continue
        normalized = normalize_name(alias)
        if normalized:
            yield (geonameid, language_value, alias, normalized, kind)


def load(
    conn: psycopg.Connection[Any],
    min_population: int = 1000,
    languages: frozenset[str] = DEFAULT_LANGUAGES,
    places_file: str = "allCountries.txt",
    include_minor_facilities: bool = False,
) -> dict[str, int]:
    root = geonames_dir()
    with conn.cursor() as cur:
        cur.execute(STAGING_DDL)
    with (root / places_file).open(encoding="utf-8") as handle:
        count = copy_rows(
            conn,
            "stg_geonames",
            [
                "geonameid",
                "name",
                "name_normalized",
                "lat",
                "lon",
                "feature_class",
                "feature_code",
                "place_type",
                "country_code",
                "admin1_code",
                "admin2_code",
                "population",
            ],
            parse_places(handle, min_population, include_minor_facilities),
        )
    with conn.cursor() as cur:
        cur.execute("SELECT geonameid FROM stg_geonames")
        wanted = {int(row[0]) for row in cur.fetchall()}
    alternates = root / "alternateNamesV2.txt"
    alt_count = 0
    if alternates.exists():
        with alternates.open(encoding="utf-8") as handle:
            alt_count = copy_rows(
                conn,
                "stg_geonames_alt",
                ["geonameid", "language", "alias", "alias_normalized", "kind"],
                parse_alternates(handle, wanted, languages),
            )
    with conn.cursor() as cur:
        cur.execute("CREATE INDEX ON stg_geonames_alt (geonameid)")
        cur.execute("ANALYZE stg_geonames")
        cur.execute("ANALYZE stg_geonames_alt")
    return {"geonames_places": count, "geonames_aliases": alt_count}


def run(conn: psycopg.Connection[Any], **kwargs: Any) -> None:
    with etl_step(conn, "stage_geonames") as stats:
        stats.update(load(conn, **kwargs))
