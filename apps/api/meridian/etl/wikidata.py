"""Stage the Wikidata place subset produced by data/scripts/build_wikidata_subset.py."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd
import pandera.pandas as pa
import psycopg
import pyarrow.parquet as pq

from meridian.config import get_settings
from meridian.db import copy_rows, etl_step
from meridian.geo import taxonomy
from meridian.geo.names import normalize_name

log = logging.getLogger("meridian.etl.wikidata")

LANGUAGE_PRIORITY = ["en", "es", "fr", "de", "pt", "it", "nl", "ru", "tr", "pl", "id", "uk", "ar", "hi", "zh", "ja"]

STAGING_DDL = """
DROP TABLE IF EXISTS stg_wikidata, stg_wd_names;
CREATE UNLOGGED TABLE stg_wikidata (
    qid text PRIMARY KEY, name text NOT NULL, name_normalized text NOT NULL, place_type text NOT NULL,
    lat double precision NOT NULL, lon double precision NOT NULL, country_qid text,
    admin_parent_qids text[], population bigint, geonames_id bigint, website text,
    sitelinks integer, description text
);
CREATE UNLOGGED TABLE stg_wd_names (
    qid text NOT NULL, language text NOT NULL, text text NOT NULL, text_normalized text NOT NULL, kind text NOT NULL
);
"""

PLACES_SCHEMA = pa.DataFrameSchema(
    {
        "qid": pa.Column(str, pa.Check.str_matches(r"^Q\d+$"), unique=True),
        "place_type": pa.Column(str, pa.Check.isin(taxonomy.PLACE_TYPES)),
        "lat": pa.Column(float, pa.Check.in_range(-90, 90)),
        "lon": pa.Column(float, pa.Check.in_range(-180, 180)),
        "population": pa.Column("Int64", pa.Check.ge(0), nullable=True),
        "geonames_id": pa.Column(str, pa.Check.str_matches(r"^\d+$"), nullable=True),
    },
    strict=False,
)


def wikidata_dir() -> Path:
    return get_settings().data_dir / "raw" / "knowledge_base" / "wikidata"


def validate_places(table_path: Path) -> int:
    """Validate the places parquet against the expected schema. Returns the row count."""
    frame = pq.read_table(
        table_path, columns=["qid", "place_type", "lat", "lon", "population", "geonames_id"]
    ).to_pandas()
    frame["population"] = frame["population"].astype("Int64")
    PLACES_SCHEMA.validate(frame, lazy=True)
    return len(frame)


def pick_label(labels: dict[str, str]) -> str | None:
    for language in LANGUAGE_PRIORITY:
        if labels.get(language):
            return labels[language]
    return next(iter(labels.values()), None)


def load_names(path: Path) -> tuple[dict[str, dict[str, str]], list[tuple[str, str, str, str]]]:
    """Return per-QID label maps and alias/description rows."""
    labels: dict[str, dict[str, str]] = {}
    extras: list[tuple[str, str, str, str]] = []
    table = pq.read_table(path)
    for qid, lang, kind, text in zip(
        table["qid"].to_pylist(),
        table["lang"].to_pylist(),
        table["kind"].to_pylist(),
        table["text"].to_pylist(),
        strict=True,
    ):
        if kind == "label":
            labels.setdefault(qid, {})[lang] = text
        extras.append((qid, lang, text, kind))
    return labels, extras


def place_rows(path: Path, labels: dict[str, dict[str, str]], min_natural_sitelinks: int) -> Iterator[tuple[Any, ...]]:
    table = pq.ParquetFile(path)
    for batch in table.iter_batches(batch_size=50_000):
        for record in batch.to_pylist():
            name = pick_label(labels.get(record["qid"], {}))
            normalized = normalize_name(name or "")
            if not name or not normalized:
                continue
            if record["place_type"] in taxonomy.NATURAL_TYPES and (record["sitelinks"] or 0) < min_natural_sitelinks:
                continue
            geonames_id = record["geonames_id"]
            yield (
                record["qid"],
                name,
                normalized,
                record["place_type"],
                record["lat"],
                record["lon"],
                record["country_qid"],
                record["admin_parent_qids"] or [],
                record["population"],
                int(geonames_id) if geonames_id and geonames_id.isdigit() else None,
                record["website"],
                record["sitelinks"],
                record["description_en"],
            )


def load(conn: psycopg.Connection[Any], min_natural_sitelinks: int = 3) -> dict[str, int]:
    root = wikidata_dir()
    places_path, names_path = root / "places.parquet", root / "names.parquet"
    validated = validate_places(places_path)
    labels, extras = load_names(names_path)
    with conn.cursor() as cur:
        cur.execute(STAGING_DDL)
    count = copy_rows(
        conn,
        "stg_wikidata",
        [
            "qid",
            "name",
            "name_normalized",
            "place_type",
            "lat",
            "lon",
            "country_qid",
            "admin_parent_qids",
            "population",
            "geonames_id",
            "website",
            "sitelinks",
            "description",
        ],
        place_rows(places_path, labels, min_natural_sitelinks),
    )
    with conn.cursor() as cur:
        cur.execute("SELECT qid FROM stg_wikidata")
        kept = {row[0] for row in cur.fetchall()}
    name_rows = (
        (qid, lang, text, normalize_name(text) if kind != "description" else "", kind)
        for qid, lang, text, kind in extras
        if qid in kept
    )
    name_count = copy_rows(conn, "stg_wd_names", ["qid", "language", "text", "text_normalized", "kind"], name_rows)
    with conn.cursor() as cur:
        cur.execute("CREATE INDEX ON stg_wd_names (qid)")
        cur.execute("CREATE INDEX ON stg_wikidata (geonames_id) WHERE geonames_id IS NOT NULL")
        cur.execute("CREATE INDEX ON stg_wikidata (name_normalized)")
        cur.execute("ANALYZE stg_wikidata")
        cur.execute("ANALYZE stg_wd_names")
    return {"wikidata_validated": validated, "wikidata_places": count, "wikidata_names": name_count}


def stage_empty(conn: psycopg.Connection[Any]) -> None:
    """Empty staging tables, for builds without the Wikidata subset (the demo knowledge base)."""
    with etl_step(conn, "stage_wikidata") as stats:
        with conn.cursor() as cur:
            cur.execute(STAGING_DDL)
        stats["skipped"] = 1


def run(conn: psycopg.Connection[Any], **kwargs: Any) -> None:
    with etl_step(conn, "stage_wikidata") as stats:
        stats.update(load(conn, **kwargs))


_ = pd  # pandas is required by pandera's DataFrame validation
