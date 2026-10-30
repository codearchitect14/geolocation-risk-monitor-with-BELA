"""Pull NASA FIRMS active fire detections into data/raw/hazards/firms.

Requires a free MAP_KEY in FIRMS_MAP_KEY. Live mode fetches the current UTC day for
each source; the file is replaced atomically because near real time data for a day
grows as satellite passes are processed. Backfill mode walks a date range in
windows of at most five days, using the DATE parameter.

Credit: NASA FIRMS.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import sys
from pathlib import Path
from typing import Any

import httpx

import common

SOURCE_ID = "firms"
BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
DEFAULT_SOURCES = ["VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT"]
MAX_DAY_RANGE = 5
REQUEST_INTERVAL_SECONDS = 2.0
REQUIRED_COLUMNS = {"latitude", "longitude", "acq_date", "acq_time"}

log = common.get_logger("pull_firms")


class FirmsError(RuntimeError):
    pass


def build_url(map_key: str, source: str, area: str, day_range: int, date: dt.date | None) -> str:
    if not 1 <= day_range <= MAX_DAY_RANGE:
        raise ValueError(f"day range must be between 1 and {MAX_DAY_RANGE}")
    url = f"{BASE_URL}/{map_key}/{source}/{area}/{day_range}"
    return f"{url}/{date.isoformat()}" if date else url


def validate_csv(text: str) -> int:
    """Return the number of data rows. Raise if the payload is an error message."""
    stripped = text.strip()
    if not stripped:
        return 0
    reader = csv.reader(io.StringIO(stripped))
    header = next(reader)
    if not REQUIRED_COLUMNS.issubset({h.strip() for h in header}):
        raise FirmsError(f"unexpected FIRMS response: {stripped[:120]!r}")
    index = {h: i for i, h in enumerate(header)}
    rows = 0
    for row in reader:
        try:
            lat, lon = float(row[index["latitude"]]), float(row[index["longitude"]])
        except (ValueError, IndexError):
            continue
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            rows += 1
    return rows


def fetch_window(
    client: httpx.Client,
    map_key: str,
    source: str,
    area: str,
    start: dt.date,
    day_range: int,
    directory: Path,
) -> dict[str, Any]:
    url = build_url(map_key, source, area, day_range, start)
    response = common.request_with_retry(client, "GET", url, logger=log, retries=3, backoff=10.0)
    if response.status_code != 200:
        raise FirmsError(f"{source} {start}: HTTP {response.status_code}")
    rows = validate_csv(response.text)
    name = f"{source}_{start.isoformat()}_{day_range}d.csv"
    target = directory / name
    new_hash = common.sha256_bytes(response.content)
    changed = not target.exists() or common.sha256_file(target) != new_hash
    if changed:
        common.atomic_write_bytes(target, response.content)
    return {"file": name, "rows": rows, "changed": changed, "bytes": len(response.content)}


def windows(start: dt.date, end: dt.date) -> list[tuple[dt.date, int]]:
    result = []
    current = start
    while current <= end:
        span = min(MAX_DAY_RANGE, (end - current).days + 1)
        result.append((current, span))
        current += dt.timedelta(days=span)
    return result


def run(sources: list[str], area: str, start: dt.date | None, end: dt.date | None, lookback: int) -> dict[str, Any]:
    map_key = common.env_required("FIRMS_MAP_KEY", "Request a free key from the NASA FIRMS 'Get MAP_KEY' form.")
    directory = common.raw_dir("hazards", "firms")
    limiter = common.RateLimiter(REQUEST_INTERVAL_SECONDS)
    today = common.utcnow().date()
    if start:
        plan = windows(start, end or today)
    else:
        plan = [(today - dt.timedelta(days=offset), 1) for offset in range(lookback - 1, -1, -1)]
    results: list[dict[str, Any]] = []
    with common.make_client(timeout=120.0) as client:
        for source in sources:
            for begin, span in plan:
                limiter.wait("firms")
                results.append(fetch_window(client, map_key, source, area, begin, span, directory))
    return {
        "requests": len(results),
        "rows": sum(r["rows"] for r in results),
        "files_changed": sum(1 for r in results if r["changed"]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", action="append", dest="sources", help="FIRMS source name")
    parser.add_argument("--area", default="world", help="'world' or west,south,east,north")
    parser.add_argument("--start", type=common.parse_date, help="backfill start date")
    parser.add_argument("--end", type=common.parse_date, help="backfill end date (inclusive)")
    parser.add_argument("--lookback-days", type=int, default=2, help="live mode: days to refresh")
    args = parser.parse_args(argv)
    try:
        stats = run(args.sources or DEFAULT_SOURCES, args.area, args.start, args.end, args.lookback_days)
    except Exception as exc:
        log.error("firms pull failed: %s", exc)
        common.write_status("firms", False, {"error": str(exc)})
        return 1
    log.info("firms done: %s", stats)
    common.write_status("firms", True, stats)
    common.record_harvest(SOURCE_ID, stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
