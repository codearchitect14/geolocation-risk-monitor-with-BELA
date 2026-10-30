"""Pull USGS earthquake data into data/raw/hazards/usgs.

Live mode reads a summary feed (default all_day) and appends only new or revised
events to one JSONL file per UTC day of the event time. History mode uses the
catalog query API in windows that stay below its result limit.

Credit: U.S. Geological Survey (public domain).
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Any

import httpx

import common

SOURCE_ID = "usgs"
FEED_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/{feed}.geojson"
QUERY_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
FEEDS = {
    "all_hour",
    "all_day",
    "all_week",
    "all_month",
    "2.5_day",
    "2.5_week",
    "2.5_month",
    "4.5_day",
    "4.5_week",
    "4.5_month",
}
QUERY_LIMIT = 20000

log = common.get_logger("pull_usgs")


def out_dir() -> Path:
    return common.raw_dir("hazards", "usgs")


def event_day(feature: dict[str, Any]) -> str:
    millis = feature.get("properties", {}).get("time")
    if not isinstance(millis, int | float):
        return "unknown"
    return dt.datetime.fromtimestamp(millis / 1000, dt.UTC).strftime("%Y-%m-%d")


def valid_feature(feature: Any) -> bool:
    """Schema and range checks applied to every record before it is stored."""
    if not isinstance(feature, dict) or not isinstance(feature.get("id"), str):
        return False
    coords = (feature.get("geometry") or {}).get("coordinates")
    if not isinstance(coords, list) or len(coords) < 2:
        return False
    lon, lat = coords[0], coords[1]
    if not all(isinstance(v, int | float) for v in (lon, lat)):
        return False
    return bool(-180 <= lon <= 180 and -90 <= lat <= 90)


def store_features(features: list[dict[str, Any]], state: dict[str, Any], directory: Path) -> tuple[int, int]:
    """Append unseen or revised features. Returns (written, rejected)."""
    by_day: dict[str, list[dict[str, Any]]] = {}
    rejected = 0
    for feature in features:
        if not valid_feature(feature):
            rejected += 1
            continue
        updated = feature.get("properties", {}).get("updated")
        if state.get(feature["id"]) == updated:
            continue
        state[feature["id"]] = updated
        record = {"fetched_at": common.iso_now(), "feature": feature}
        by_day.setdefault(event_day(feature), []).append(record)
    written = sum(common.append_jsonl(directory / f"{day}.jsonl", records) for day, records in by_day.items())
    return written, rejected


def prune_state(state: dict[str, Any], keep: set[str]) -> None:
    if len(state) > 200_000:
        for key in [k for k in state if k not in keep][: len(state) - 100_000]:
            del state[key]


def pull_live(client: httpx.Client, feed: str) -> dict[str, Any]:
    directory = out_dir()
    state_path = directory / "_state.json"
    state = common.read_json(state_path, {}) or {}
    response = common.request_with_retry(client, "GET", FEED_URL.format(feed=feed), logger=log)
    response.raise_for_status()
    payload = response.json()
    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError("unexpected USGS payload: no features list")
    written, rejected = store_features(features, state, directory)
    prune_state(state, {f.get("id", "") for f in features})
    common.write_json(state_path, state)
    return {
        "feed": feed,
        "received": len(features),
        "written": written,
        "rejected": rejected,
        "bytes": len(response.content),
    }


def split_windows(start: dt.date, end: dt.date, days: int) -> list[tuple[dt.date, dt.date]]:
    windows = []
    current = start
    while current <= end:
        stop = min(current + dt.timedelta(days=days), end + dt.timedelta(days=1))
        windows.append((current, stop))
        current = stop
    return windows


def pull_history(
    client: httpx.Client, start: dt.date, end: dt.date, min_magnitude: float, window_days: int
) -> dict[str, Any]:
    directory = out_dir()
    state_path = directory / "_state.json"
    state = common.read_json(state_path, {}) or {}
    total_written = total_rejected = total_received = 0
    pending = split_windows(start, end, window_days)
    while pending:
        begin, stop = pending.pop(0)
        params = {
            "format": "geojson",
            "starttime": begin.isoformat(),
            "endtime": stop.isoformat(),
            "minmagnitude": str(min_magnitude),
            "orderby": "time-asc",
            "limit": str(QUERY_LIMIT),
        }
        response = common.request_with_retry(client, "GET", QUERY_URL, params=params, logger=log)
        if response.status_code == 400 and "exceeds search limit" in response.text.lower():
            half = max((stop - begin).days // 2, 1)
            if (stop - begin).days <= 1:
                raise RuntimeError(f"window {begin} exceeds the result limit at one day")
            middle = begin + dt.timedelta(days=half)
            pending[:0] = [(begin, middle), (middle, stop)]
            continue
        response.raise_for_status()
        features = response.json().get("features", [])
        written, rejected = store_features(features, state, directory)
        total_received += len(features)
        total_written += written
        total_rejected += rejected
        common.write_json(state_path, state)
        log.info("history %s to %s: %d events", begin, stop, len(features))
    return {"mode": "history", "received": total_received, "written": total_written, "rejected": total_rejected}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--feed", default="all_day", choices=sorted(FEEDS))
    parser.add_argument("--start", type=common.parse_date, help="history start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=common.parse_date, help="history end date (inclusive)")
    parser.add_argument("--min-magnitude", type=float, default=2.5)
    parser.add_argument("--window-days", type=int, default=7)
    args = parser.parse_args(argv)

    try:
        with common.make_client() as client:
            if args.start:
                end = args.end or common.utcnow().date()
                stats = pull_history(client, args.start, end, args.min_magnitude, args.window_days)
            else:
                stats = pull_live(client, args.feed)
    except Exception as exc:
        log.error("usgs pull failed: %s", exc)
        common.write_status("usgs", False, {"error": str(exc)})
        return 1
    log.info("usgs done: %s", stats)
    common.write_status("usgs", True, stats)
    common.record_harvest(SOURCE_ID, stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
