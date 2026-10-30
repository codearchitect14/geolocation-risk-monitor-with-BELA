"""Pull active National Weather Service alerts into data/raw/hazards/nws.

The NWS API requires a User-Agent that identifies the application. Set
NWS_USER_AGENT, or MS_CONTACT so one can be built. Alerts are stored once per
alert id, in one JSONL file per fetch day. Geometry may be missing; the UGC zone
codes are kept so zones can be resolved to polygons later.

Credit: National Weather Service.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path
from typing import Any

import httpx

import common

SOURCE_ID = "nws"
ALERTS_URL = "https://api.weather.gov/alerts/active"
STATE_RETENTION_DAYS = 10

log = common.get_logger("pull_nws")


def build_user_agent() -> str:
    explicit = os.environ.get("NWS_USER_AGENT", "").strip()
    if explicit:
        return explicit
    contact = os.environ.get("MS_CONTACT", "").strip()
    if not contact:
        raise SystemExit("NWS requires an identifying User-Agent. Set NWS_USER_AGENT or MS_CONTACT in .env.")
    return f"MeridianSignal-data/0.1 ({contact})"


def out_dir() -> Path:
    return common.raw_dir("hazards", "nws")


def valid_feature(feature: Any) -> bool:
    if not isinstance(feature, dict):
        return False
    props = feature.get("properties")
    return isinstance(props, dict) and isinstance(props.get("id"), str) and bool(props.get("event"))


def store_alerts(features: list[dict[str, Any]], state: dict[str, str], directory: Path) -> tuple[int, int]:
    """Append alerts not seen before. Returns (written, rejected)."""
    now = common.iso_now()
    records: list[dict[str, Any]] = []
    rejected = 0
    for feature in features:
        if not valid_feature(feature):
            rejected += 1
            continue
        alert_id = feature["properties"]["id"]
        if alert_id in state:
            continue
        state[alert_id] = now
        records.append({"fetched_at": now, "feature": feature})
    written = common.append_jsonl(directory / f"{now[:10]}.jsonl", records) if records else 0
    return written, rejected


def prune_state(state: dict[str, str]) -> None:
    cutoff = (common.utcnow() - dt.timedelta(days=STATE_RETENTION_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for key in [k for k, v in state.items() if v < cutoff]:
        del state[key]


def pull(client: httpx.Client, area: str | None) -> dict[str, Any]:
    directory = out_dir()
    state_path = directory / "_state.json"
    state: dict[str, str] = common.read_json(state_path, {}) or {}
    params = {"area": area} if area else None
    response = common.request_with_retry(client, "GET", ALERTS_URL, params=params, logger=log, retries=3, backoff=5.0)
    response.raise_for_status()
    features = response.json().get("features")
    if not isinstance(features, list):
        raise ValueError("unexpected NWS payload: no features list")
    written, rejected = store_alerts(features, state, directory)
    prune_state(state)
    common.write_json(state_path, state)
    with_geometry = sum(1 for f in features if f.get("geometry"))
    return {
        "received": len(features),
        "written": written,
        "rejected": rejected,
        "with_geometry": with_geometry,
        "bytes": len(response.content),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--area", help="two-letter state or marine area code")
    args = parser.parse_args(argv)
    agent = build_user_agent()
    try:
        with common.make_client(headers={"User-Agent": agent, "Accept": "application/geo+json"}) as client:
            stats = pull(client, args.area)
    except Exception as exc:
        log.error("nws pull failed: %s", exc)
        common.write_status("nws", False, {"error": str(exc)})
        return 1
    log.info("nws done: %s", stats)
    common.write_status("nws", True, stats)
    common.record_harvest(SOURCE_ID, stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
