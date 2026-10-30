"""Build the place and facility subset of Wikidata as parquet files.

Input is the official JSON entity dump (one entity per line), read from a local file
(.json, .gz, .bz2) or streamed from dumps.wikimedia.org without storing it. A single
pass collects two things: subclass edges (P279) for every entity that has them, and
every entity with a coordinate location (P625) and at least one P31 value. After the
pass, the class hierarchy below the seed classes is expanded, and the candidates
whose P31 falls inside it are kept. Entities without coordinates cannot be placed,
so they are out of scope here; administrative regions are covered by Natural Earth
polygons in the next phase.

Outputs in data/raw/knowledge_base/wikidata/:
  places.parquet   one row per kept entity
  names.parquet    long table of labels, aliases, and descriptions in target languages
  class_map.json   class QID to place type, for audit

All class and property IDs were checked against wikidata.org. Credit: Wikidata (CC0).
"""

from __future__ import annotations

import argparse
import bz2
import contextlib
import gzip
import json
import sys
import time
from collections import deque
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

import common

try:
    import orjson

    def loads(data: bytes) -> Any:
        return orjson.loads(data)
except ImportError:  # pragma: no cover

    def loads(data: bytes) -> Any:
        return json.loads(data)


SOURCE_ID = "wikidata"
DUMP_URL = "https://dumps.wikimedia.org/wikidatawiki/entities/latest-all.json.bz2"
DEFAULT_LANGUAGES = ["en", "es", "fr", "de", "pt", "it", "ru", "ar", "zh", "ja", "tr", "nl", "pl", "uk", "id", "hi"]

# Properties: P31 instance of, P279 subclass of, P17 country, P131 located in administrative
# territorial entity, P625 coordinate location, P1082 population, P1566 GeoNames ID,
# P856 official website, P585 point in time.

# Seed classes in priority order. The first type whose class closure contains one of an
# entity's P31 values is the place type. Facilities come first so that a port in a city
# is typed as a port.
SEED_CLASSES: list[tuple[str, list[str]]] = [
    ("airport", ["Q1248784"]),
    ("seaport", ["Q15310171", "Q44782", "Q492425"]),
    ("railway_station", ["Q55488"]),
    ("power_station", ["Q159719"]),
    ("refinery", ["Q12353044"]),
    ("factory", ["Q83405"]),
    ("dam", ["Q12323"]),
    ("bridge", ["Q12280"]),
    ("tunnel", ["Q44377"]),
    ("border_crossing", ["Q55599109", "Q757292"]),
    ("military_base", ["Q245016"]),
    ("hospital", ["Q16917"]),
    ("stadium", ["Q483110"]),
    ("country", ["Q6256"]),
    ("city", ["Q515"]),
    ("town", ["Q3957"]),
    ("village", ["Q532"]),
    ("admin_region", ["Q56061"]),
    ("river", ["Q4022"]),
    ("lake", ["Q23397"]),
    ("island", ["Q23442"]),
    ("mountain", ["Q8502"]),
]

log = common.get_logger("build_wikidata_subset")


# ---------------------------------------------------------------------------
# Reading the dump
# ---------------------------------------------------------------------------


def split_lines(chunks: Iterable[bytes]) -> Iterator[bytes]:
    buffer = b""
    for chunk in chunks:
        buffer += chunk
        *lines, buffer = buffer.split(b"\n")
        yield from lines
    if buffer:
        yield buffer


def bz2_chunks(chunks: Iterable[bytes]) -> Iterator[bytes]:
    """Decompress a possibly multi-stream bz2 byte stream incrementally."""
    decompressor = bz2.BZ2Decompressor()
    for chunk in chunks:
        data = chunk
        while data:
            if decompressor.eof:
                decompressor = bz2.BZ2Decompressor()
            out = decompressor.decompress(data)
            if out:
                yield out
            data = decompressor.unused_data if decompressor.eof else b""


def file_lines(path: Path) -> Iterator[bytes]:
    with contextlib.ExitStack() as stack:
        handle: Any
        if path.suffix == ".bz2":
            handle = stack.enter_context(bz2.open(path, "rb"))
        elif path.suffix == ".gz":
            handle = stack.enter_context(gzip.open(path, "rb"))
        else:
            handle = stack.enter_context(path.open("rb"))
        yield from handle


def url_lines(url: str) -> Iterator[bytes]:
    with common.make_client(timeout=120.0) as client, client.stream("GET", url) as response:
        response.raise_for_status()
        chunks: Iterable[bytes] = response.iter_bytes(1 << 20)
        if url.endswith(".bz2"):
            chunks = bz2_chunks(chunks)
        yield from split_lines(chunks)


def entity_from_line(line: bytes) -> dict[str, Any] | None:
    line = line.strip()
    if line in (b"", b"[", b"]"):
        return None
    if line.endswith(b","):
        line = line[:-1]
    try:
        entity = loads(line)
    except ValueError:
        return None
    return entity if isinstance(entity, dict) else None


# ---------------------------------------------------------------------------
# Claim helpers
# ---------------------------------------------------------------------------


def _live_claims(entity: dict[str, Any], prop: str) -> list[dict[str, Any]]:
    claims = [c for c in entity.get("claims", {}).get(prop, []) if c.get("rank") != "deprecated"]
    preferred = [c for c in claims if c.get("rank") == "preferred"]
    return preferred or claims


def _value(claim: dict[str, Any]) -> Any:
    snak = claim.get("mainsnak", {})
    if snak.get("snaktype") != "value":
        return None
    return snak.get("datavalue", {}).get("value")


def item_ids(entity: dict[str, Any], prop: str) -> list[str]:
    result = []
    for claim in _live_claims(entity, prop):
        value = _value(claim)
        if isinstance(value, dict) and "id" in value:
            result.append(value["id"])
    return result


def coordinates(entity: dict[str, Any]) -> tuple[float, float] | None:
    for claim in _live_claims(entity, "P625"):
        value = _value(claim)
        if isinstance(value, dict):
            lat, lon = value.get("latitude"), value.get("longitude")
            if (
                isinstance(lat, int | float)
                and isinstance(lon, int | float)
                and -90 <= lat <= 90
                and -180 <= lon <= 180
            ):
                return float(lat), float(lon)
    return None


def population(entity: dict[str, Any]) -> int | None:
    best: tuple[str, int] | None = None
    for claim in _live_claims(entity, "P1082"):
        value = _value(claim)
        if not isinstance(value, dict):
            continue
        try:
            amount = int(float(value["amount"]))
        except (KeyError, ValueError):
            continue
        when = ""
        for qualifier in claim.get("qualifiers", {}).get("P585", []):
            time_value = qualifier.get("datavalue", {}).get("value", {})
            when = str(time_value.get("time", ""))
        if best is None or when > best[0]:
            best = (when, amount)
    return best[1] if best and best[1] >= 0 else None


def string_value(entity: dict[str, Any], prop: str) -> str | None:
    for claim in _live_claims(entity, prop):
        value = _value(claim)
        if isinstance(value, str) and value:
            return value
    return None


def names_for(entity: dict[str, Any], languages: set[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for lang, item in entity.get("labels", {}).items():
        if lang in languages:
            rows.append({"lang": lang, "kind": "label", "text": item["value"]})
    for lang, items in entity.get("aliases", {}).items():
        if lang in languages:
            rows.extend({"lang": lang, "kind": "alias", "text": i["value"]} for i in items)
    for lang, item in entity.get("descriptions", {}).items():
        if lang in languages:
            rows.append({"lang": lang, "kind": "description", "text": item["value"]})
    return rows


def candidate_from_entity(entity: dict[str, Any], languages: set[str]) -> dict[str, Any] | None:
    qid = entity.get("id")
    if not isinstance(qid, str) or not qid.startswith("Q"):
        return None
    coords = coordinates(entity)
    instance_of = item_ids(entity, "P31")
    if coords is None or not instance_of:
        return None
    countries = item_ids(entity, "P17")
    return {
        "qid": qid,
        "instance_of": instance_of,
        "lat": coords[0],
        "lon": coords[1],
        "country_qid": countries[0] if countries else None,
        "admin_parent_qids": item_ids(entity, "P131"),
        "population": population(entity),
        "geonames_id": string_value(entity, "P1566"),
        "website": string_value(entity, "P856"),
        "sitelinks": len(entity.get("sitelinks", {})),
        "names": names_for(entity, languages),
    }


# ---------------------------------------------------------------------------
# Class closure
# ---------------------------------------------------------------------------


def build_class_map(parents: dict[str, list[str]]) -> dict[str, str]:
    """Map every class at or below a seed class to its place type, respecting priority."""
    children: dict[str, list[str]] = {}
    for child, ups in parents.items():
        for parent in ups:
            children.setdefault(parent, []).append(child)
    class_map: dict[str, str] = {}
    for place_type, seeds in SEED_CLASSES:
        queue = deque(seeds)
        seen: set[str] = set()
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            class_map.setdefault(current, place_type)
            queue.extend(children.get(current, ()))
    return class_map


def place_type_for(instance_of: list[str], class_map: dict[str, str]) -> str | None:
    order = {name: i for i, (name, _) in enumerate(SEED_CLASSES)}
    types = {class_map[c] for c in instance_of if c in class_map}
    return min(types, key=lambda t: order[t]) if types else None


# ---------------------------------------------------------------------------
# Passes
# ---------------------------------------------------------------------------


def scan(lines: Iterable[bytes], work: Path, languages: set[str], limit: int | None) -> dict[str, int]:
    """Pass 1: write subclass edges and coordinate candidates to the work directory."""
    work.mkdir(parents=True, exist_ok=True)
    counts = {"lines": 0, "edges": 0, "candidates": 0}
    started = time.monotonic()
    with gzip.open(work / "candidates.jsonl.gz", "wb") as spool, gzip.open(work / "edges.jsonl.gz", "wb") as edges:
        for line in lines:
            counts["lines"] += 1
            if limit and counts["lines"] > limit:
                break
            if counts["lines"] % 500_000 == 0:
                rate = counts["lines"] / (time.monotonic() - started)
                log.info("scanned %d lines (%.0f/s): %s", counts["lines"], rate, counts)
            if b'"P625"' not in line and b'"P279"' not in line:
                continue
            entity = entity_from_line(line)
            if entity is None:
                continue
            parents = item_ids(entity, "P279")
            if parents and isinstance(entity.get("id"), str):
                edges.write(json.dumps({"id": entity["id"], "parents": parents}).encode() + b"\n")
                counts["edges"] += 1
            candidate = candidate_from_entity(entity, languages)
            if candidate:
                spool.write(json.dumps(candidate, ensure_ascii=False).encode() + b"\n")
                counts["candidates"] += 1
    return counts


def load_edges(work: Path) -> dict[str, list[str]]:
    parents: dict[str, list[str]] = {}
    with gzip.open(work / "edges.jsonl.gz", "rb") as handle:
        for line in handle:
            row = json.loads(line)
            parents[row["id"]] = row["parents"]
    return parents


PLACE_SCHEMA = pa.schema(
    [
        ("qid", pa.string()),
        ("place_type", pa.string()),
        ("instance_of", pa.list_(pa.string())),
        ("lat", pa.float64()),
        ("lon", pa.float64()),
        ("country_qid", pa.string()),
        ("admin_parent_qids", pa.list_(pa.string())),
        ("population", pa.int64()),
        ("geonames_id", pa.string()),
        ("website", pa.string()),
        ("sitelinks", pa.int32()),
        ("label_en", pa.string()),
        ("description_en", pa.string()),
    ]
)
NAME_SCHEMA = pa.schema(
    [
        ("qid", pa.string()),
        ("lang", pa.string()),
        ("kind", pa.string()),
        ("text", pa.string()),
    ]
)


def filter_candidates(work: Path, out_dir: Path, batch_size: int = 100_000) -> dict[str, Any]:
    """Pass 2: keep candidates inside the class closure and write parquet files."""
    class_map = build_class_map(load_edges(work))
    common.write_json(out_dir / "class_map.json", dict(sorted(class_map.items())))
    kept = 0
    by_type: dict[str, int] = {}
    place_rows: list[dict[str, Any]] = []
    name_rows: list[dict[str, Any]] = []

    with (
        pq.ParquetWriter(out_dir / "places.parquet.tmp", PLACE_SCHEMA, compression="zstd") as places,
        pq.ParquetWriter(out_dir / "names.parquet.tmp", NAME_SCHEMA, compression="zstd") as names,
        gzip.open(work / "candidates.jsonl.gz", "rb") as spool,
    ):

        def flush() -> None:
            if place_rows:
                places.write_table(pa.Table.from_pylist(place_rows, schema=PLACE_SCHEMA))
                names.write_table(pa.Table.from_pylist(name_rows, schema=NAME_SCHEMA))
                place_rows.clear()
                name_rows.clear()

        for line in spool:
            candidate = json.loads(line)
            place_type = place_type_for(candidate["instance_of"], class_map)
            if place_type is None:
                continue
            en_label = next((n["text"] for n in candidate["names"] if n["lang"] == "en" and n["kind"] == "label"), None)
            en_desc = next(
                (n["text"] for n in candidate["names"] if n["lang"] == "en" and n["kind"] == "description"), None
            )
            place_rows.append(
                {
                    **{
                        k: candidate[k]
                        for k in (
                            "qid",
                            "instance_of",
                            "lat",
                            "lon",
                            "country_qid",
                            "admin_parent_qids",
                            "population",
                            "geonames_id",
                            "website",
                            "sitelinks",
                        )
                    },
                    "place_type": place_type,
                    "label_en": en_label,
                    "description_en": en_desc,
                }
            )
            name_rows.extend({"qid": candidate["qid"], **n} for n in candidate["names"])
            kept += 1
            by_type[place_type] = by_type.get(place_type, 0) + 1
            if len(place_rows) >= batch_size:
                flush()
        flush()

    for name in ("places", "names"):
        (out_dir / f"{name}.parquet.tmp").replace(out_dir / f"{name}.parquet")
    return {"kept": kept, "by_type": dict(sorted(by_type.items()))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--dump", type=Path, help="local entity dump (.json, .gz, .bz2)")
    source.add_argument("--url", default=DUMP_URL, help="stream the dump from this URL")
    source.add_argument(
        "--filter-only", action="store_true", help="rerun the class filter on an existing work directory"
    )
    parser.add_argument("--languages", default=",".join(DEFAULT_LANGUAGES))
    parser.add_argument("--limit-lines", type=int, help="stop after N dump lines (smoke tests)")
    parser.add_argument("--cleanup", action="store_true", help="delete the work directory when done")
    parser.add_argument("--out", type=Path, help="output directory")
    args = parser.parse_args(argv)

    out_dir = args.out or common.raw_dir("knowledge_base", "wikidata")
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "_work"
    languages = {x.strip() for x in args.languages.split(",") if x.strip()}
    try:
        scan_counts: dict[str, int] = {}
        if not args.filter_only:
            lines = file_lines(args.dump) if args.dump else url_lines(args.url)
            scan_counts = scan(lines, work, languages, args.limit_lines)
            log.info("scan complete: %s", scan_counts)
        result = filter_candidates(work, out_dir)
    except Exception as exc:
        log.error("wikidata subset failed: %s", exc)
        common.write_status("wikidata", False, {"error": str(exc)})
        return 1
    log.info("kept %d places: %s", result["kept"], result["by_type"])
    artifacts = []
    for name in ("places.parquet", "names.parquet", "class_map.json"):
        path = out_dir / name
        artifacts.append(
            {
                "path": path.as_posix(),
                "url": args.url if not args.dump else None,
                "size": path.stat().st_size,
                "sha256": common.sha256_file(path),
            }
        )
    if out_dir.resolve() == common.raw_dir("knowledge_base", "wikidata").resolve():
        common.record_files(SOURCE_ID, artifacts)
    common.write_status("wikidata", True, {**scan_counts, **{"kept": result["kept"]}})
    if args.cleanup:
        for child in work.iterdir():
            child.unlink()
        work.rmdir()
    return 0


if __name__ == "__main__":
    sys.exit(main())
