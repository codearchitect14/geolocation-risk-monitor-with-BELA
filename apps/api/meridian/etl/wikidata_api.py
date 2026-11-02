"""Add missing Wikidata places on demand through the Wikidata API.

The place table is built from a dump pass. A partial pass leaves out entities that BELA links to. This module
fetches such entities by QID (50 per request, one request at a time, with a contact User-Agent), keeps those
inside the place class hierarchy, and merges them like the dump pass does. Every looked-up QID is recorded in
wikidata_entity_cache so non-places and failures are not requested again.

A full dump pass (data/scripts/build_wikidata_subset.py) makes this unnecessary for coverage; it remains useful for
entities created after the dump.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

import httpx
import psycopg

from meridian.config import REPO_ROOT, get_settings
from meridian.db import copy_rows
from meridian.etl import merge, wikidata
from meridian.geo.names import normalize_name

sys.path.insert(0, str(REPO_ROOT / "data" / "scripts"))
import build_wikidata_subset as dump_parser  # noqa: E402

log = logging.getLogger("meridian.etl.wikidata_api")

API_URL = "https://www.wikidata.org/w/api.php"
BATCH = 50
PAUSE_SECONDS = 1.0
LANGUAGES = "|".join(dump_parser.DEFAULT_LANGUAGES)


def load_class_map() -> dict[str, str]:
    path = get_settings().data_dir / "raw" / "knowledge_base" / "wikidata" / "class_map.json"
    classes: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
    return classes


def missing_qids(conn: psycopg.Connection[Any], qids: list[str]) -> list[str]:
    """QIDs that are neither places nor already looked up."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT q FROM unnest(%s::text[]) AS q
                WHERE NOT EXISTS (SELECT 1 FROM places p WHERE p.qid = q)
                  AND NOT EXISTS (SELECT 1 FROM wikidata_entity_cache c WHERE c.qid = q)""",
            (qids,),
        )
        return [r[0] for r in cur.fetchall()]


def fetch_batch(client: httpx.Client, qids: list[str]) -> dict[str, Any]:
    params = {
        "action": "wbgetentities",
        "ids": "|".join(qids),
        "format": "json",
        "props": "labels|descriptions|aliases|claims|sitelinks",
        "languages": LANGUAGES,
        "sitefilter": "enwiki",
    }
    for attempt in range(5):
        response = client.get(API_URL, params=params)
        if response.status_code in (429, 503):
            time.sleep(float(response.headers.get("Retry-After", 5 * (attempt + 1))))
            continue
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            raise RuntimeError(f"Wikidata API error: {json.dumps(body['error'])[:200]}")
        entities: dict[str, Any] = body.get("entities", {})
        return entities
    raise RuntimeError("Wikidata API kept refusing the request")


def stage_entities(
    conn: psycopg.Connection[Any], entities: dict[str, Any], class_map: dict[str, str], min_natural_sitelinks: int = 3
) -> dict[str, str]:
    """Write place entities to the staging tables. Returns the cache status per QID."""
    languages = set(dump_parser.DEFAULT_LANGUAGES)
    status: dict[str, str] = {}
    place_rows: list[tuple[Any, ...]] = []
    name_rows: list[tuple[Any, ...]] = []
    for qid, entity in entities.items():
        if "missing" in entity:
            status[qid] = "missing"
            continue
        candidate = dump_parser.candidate_from_entity(entity, languages)
        if candidate is None:
            status[qid] = "no_coordinates" if dump_parser.item_ids(entity, "P31") else "not_a_place"
            continue
        place_type = dump_parser.place_type_for(candidate["instance_of"], class_map)
        if place_type is None:
            status[qid] = "not_a_place"
            continue
        labels = {n["lang"]: n["text"] for n in candidate["names"] if n["kind"] == "label"}
        name = wikidata.pick_label(labels)
        if not name or not normalize_name(name):
            status[qid] = "missing"
            continue
        if (
            place_type in ("river", "lake", "island", "mountain")
            and (candidate["sitelinks"] or 0) < min_natural_sitelinks
        ):
            status[qid] = "not_a_place"
            continue
        description = next(
            (n["text"] for n in candidate["names"] if n["lang"] == "en" and n["kind"] == "description"), None
        )
        geonames_id = candidate["geonames_id"]
        place_rows.append(
            (
                qid,
                name,
                normalize_name(name),
                place_type,
                candidate["lat"],
                candidate["lon"],
                candidate["country_qid"],
                candidate["admin_parent_qids"] or [],
                candidate["population"],
                int(geonames_id) if geonames_id and geonames_id.isdigit() else None,
                candidate["website"],
                candidate["sitelinks"],
                description,
            )
        )
        name_rows += [
            (qid, n["lang"], n["text"], normalize_name(n["text"]) if n["kind"] != "description" else "", n["kind"])
            for n in candidate["names"]
        ]
        status[qid] = place_type
    if place_rows:
        copy_rows(
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
            place_rows,
        )
        copy_rows(conn, "stg_wd_names", ["qid", "language", "text", "text_normalized", "kind"], name_rows)
    return status


def record_status(conn: psycopg.Connection[Any], status: dict[str, str]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO wikidata_entity_cache (qid, status, place_type) VALUES (%s, %s, %s)
               ON CONFLICT (qid) DO UPDATE SET status = EXCLUDED.status, place_type = EXCLUDED.place_type, fetched_at = now()""",
            [
                (
                    q,
                    "place" if s not in ("missing", "not_a_place", "no_coordinates") else s,
                    s if s not in ("missing", "not_a_place", "no_coordinates") else None,
                )
                for q, s in status.items()
            ],
        )


def enrich(conn: psycopg.Connection[Any], qids: list[str], contact: str, limit: int | None = None) -> dict[str, Any]:
    """Fetch, stage, and merge the places among qids. Hierarchy, uncertainty, and H3 are refreshed by the caller."""
    todo = missing_qids(conn, sorted(set(qids)))[: limit or None]
    class_map = load_class_map()
    with conn.cursor() as cur:
        cur.execute(wikidata.STAGING_DDL)
    conn.commit()
    counts: dict[str, int] = {}
    client = httpx.Client(timeout=60, headers={"User-Agent": f"MeridianSignal-data/0.1 ({contact})"})
    started = time.monotonic()
    for offset in range(0, len(todo), BATCH):
        part = todo[offset : offset + BATCH]
        status = stage_entities(conn, fetch_batch(client, part), class_map)
        for qid in part:
            status.setdefault(qid, "missing")
        record_status(conn, status)
        conn.commit()
        for value in status.values():
            key = "place" if value not in ("missing", "not_a_place", "no_coordinates") else value
            counts[key] = counts.get(key, 0) + 1
        if (offset // BATCH) % 20 == 0:
            log.info("fetched %d of %d QIDs (%.1fs)", offset + len(part), len(todo), time.monotonic() - started)
        time.sleep(PAUSE_SECONDS)
    merged: dict[str, Any] = {}
    if counts.get("place"):
        merged = merge.incremental(conn)
        conn.commit()
    return {"requested": len(todo), **counts, **{f"merge_{k}": v for k, v in merged.items()}}
