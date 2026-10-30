"""Download GDELT GKG 2.0 files and extract per-article location baselines.

Each 15-minute GKG file is downloaded, parsed, and reduced to one JSON line per
article with its V2Locations entries. The raw zip is deleted unless --keep-raw is
given, because a full day is several gigabytes. Output goes to
data/raw/news/gdelt_gkg/YYYYMMDD/<timestamp>.locations.jsonl.gz.

V2Locations (GKG 2.1 codebook, verified against a live file): blocks separated by
';', fields separated by '#':
  type, full name, country code (FIPS 10-4), ADM1 code, ADM2 code, latitude,
  longitude, feature id, character offset
Type codes: 1 country, 2 US state, 3 US city, 4 world city, 5 world state.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import io
import json
import re
import sys
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx

import common

SOURCE_ID = "gdelt_gkg"
BASE_URL = "https://data.gdeltproject.org/gdeltv2"
MASTER_LIST_URL = f"{BASE_URL}/masterfilelist.txt"
GKG_COLUMNS = 27
COL_RECORD_ID, COL_DATE, COL_COLLECTION, COL_DOMAIN, COL_URL = 0, 1, 2, 3, 4
COL_V2_LOCATIONS, COL_TRANSLATION = 10, 25
LOCATION_TYPES = {1: "country", 2: "us_state", 3: "us_city", 4: "world_city", 5: "world_state"}
FILE_PATTERN = re.compile(r"/(\d{14})\.gkg\.csv\.zip$")

log = common.get_logger("download_gkg")


def _number(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def parse_v2_locations(field: str) -> list[dict[str, Any]]:
    """Parse the V2EnhancedLocations field into a list of location dictionaries."""
    locations: list[dict[str, Any]] = []
    for block in field.split(";"):
        if not block:
            continue
        parts = block.split("#")
        if len(parts) < 8:
            continue
        parts += [""] * (9 - len(parts))
        try:
            type_code = int(parts[0])
        except ValueError:
            continue
        lat, lon = _number(parts[5]), _number(parts[6])
        if lat is not None and not -90 <= lat <= 90:
            lat = None
        if lon is not None and not -180 <= lon <= 180:
            lon = None
        offset = int(parts[8]) if parts[8].lstrip("-").isdigit() else None
        locations.append(
            {
                "type": LOCATION_TYPES.get(type_code, "unknown"),
                "type_code": type_code,
                "name": parts[1],
                "country_code": parts[2] or None,
                "adm1_code": parts[3] or None,
                "adm2_code": parts[4] or None,
                "lat": lat,
                "lon": lon,
                "feature_id": parts[7] or None,
                "offset": offset,
            }
        )
    return locations


def parse_translation_language(field: str) -> str | None:
    """Extract the source language code from V2.1TranslationInfo ('srclc:fra; eng:...')."""
    match = re.search(r"srclc:([a-z]{2,3})", field)
    return match.group(1) if match else None


def iter_gkg_records(lines: Iterator[str]) -> Iterator[dict[str, Any]]:
    """Yield article records that carry at least one location."""
    for line in lines:
        cols = line.rstrip("\n").rstrip("\r").split("\t")
        if len(cols) < GKG_COLUMNS:
            continue
        locations = parse_v2_locations(cols[COL_V2_LOCATIONS])
        url = cols[COL_URL]
        if not locations or not url.startswith(("http://", "https://")):
            continue
        yield {
            "gkg_id": cols[COL_RECORD_ID],
            "date": cols[COL_DATE],
            "domain": cols[COL_DOMAIN],
            "url": url,
            "source_language": parse_translation_language(cols[COL_TRANSLATION]),
            "translated": cols[COL_COLLECTION] == "1" and bool(cols[COL_TRANSLATION]),
            "locations": locations,
        }


def convert_zip(zip_bytes_path: Path, dest: Path) -> int:
    """Parse a downloaded GKG zip and write the gzipped location JSONL. Returns record count."""
    count = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    with zipfile.ZipFile(zip_bytes_path) as archive, archive.open(archive.namelist()[0]) as member:
        text = io.TextIOWrapper(member, encoding="utf-8", errors="replace", newline="")
        with gzip.open(tmp, "wt", encoding="utf-8") as out:
            for record in iter_gkg_records(iter(text)):
                out.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                count += 1
    tmp.replace(dest)
    return count


def stamps_for_day(day: dt.date, every: int) -> list[str]:
    """15-minute timestamps for a day, thinned to every Nth file."""
    base = dt.datetime.combine(day, dt.time.min)
    stamps = [(base + dt.timedelta(minutes=15 * i)).strftime("%Y%m%d%H%M%S") for i in range(96)]
    return stamps[::every]


def master_list_stamps(client: httpx.Client) -> set[str]:
    """Timestamps present in the GDELT master file list (used to skip missing slots)."""
    response = common.request_with_retry(client, "GET", MASTER_LIST_URL, logger=log, timeout=300)
    response.raise_for_status()
    found = set()
    for line in response.text.splitlines():
        match = FILE_PATTERN.search(line.strip())
        if match:
            found.add(match.group(1))
    return found


def process_stamp(client: httpx.Client, stamp: str, keep_raw: bool, limiter: common.RateLimiter) -> tuple[str, int]:
    day_dir = common.raw_dir("news", "gdelt_gkg", stamp[:8])
    dest = day_dir / f"{stamp}.locations.jsonl.gz"
    if dest.exists():
        return "skipped", 0
    url = f"{BASE_URL}/{stamp}.gkg.csv.zip"
    zip_path = day_dir / f"{stamp}.gkg.csv.zip"
    limiter.wait("gdelt-data")
    try:
        common.download_file(client, url, zip_path, logger=log)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return "missing", 0
        raise
    count = convert_zip(zip_path, dest)
    if not keep_raw:
        zip_path.unlink()
    return "converted", count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", type=common.parse_date, help="first day (default: yesterday)")
    parser.add_argument("--end", type=common.parse_date, help="last day inclusive (default: start)")
    parser.add_argument("--every", type=int, default=4, help="take every Nth 15-minute file")
    parser.add_argument("--keep-raw", action="store_true", help="keep the downloaded zip files")
    parser.add_argument("--file", type=Path, help="convert a local GKG zip instead of downloading")
    parser.add_argument("--out", type=Path, help="output path when using --file")
    args = parser.parse_args(argv)

    if args.file:
        out = args.out or args.file.with_suffix(".locations.jsonl.gz")
        print(f"{convert_zip(args.file, out)} articles with locations -> {out}")
        return 0

    start = args.start or (common.utcnow().date() - dt.timedelta(days=1))
    end = args.end or start
    limiter = common.RateLimiter(0.5)
    totals = {"converted": 0, "skipped": 0, "missing": 0, "articles": 0}
    try:
        with common.make_client(timeout=180.0) as client:
            for day in common.date_range(start, end):
                for stamp in stamps_for_day(day, args.every):
                    status, count = process_stamp(client, stamp, args.keep_raw, limiter)
                    totals[status] += 1
                    totals["articles"] += count
    except Exception as exc:
        log.error("gkg download failed: %s", exc)
        common.write_status("gdelt_gkg", False, {"error": str(exc), **totals})
        return 1
    log.info("gkg done: %s", totals)
    common.write_status("gdelt_gkg", True, totals)
    common.record_harvest(SOURCE_ID, totals)
    return 0


if __name__ == "__main__":
    sys.exit(main())
