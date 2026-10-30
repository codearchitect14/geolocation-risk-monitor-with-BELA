"""Pull recent ReliefWeb reports and disasters into data/raw/hazards/reliefweb (optional source).

Every request needs an approved appname (RELIEFWEB_APPNAME). Only title, link,
dates, country, disaster and source names are stored, plus a snippet of at most
300 characters. Locations are country level unless the API supplies coordinates.
The script exits cleanly when the appname is not configured.

Content belongs to the original publishers. Credit: ReliefWeb (UN OCHA).
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

import common

SOURCE_ID = "reliefweb"
API_URL = "https://api.reliefweb.int/v2"
SNIPPET_CHARS = 300
PAGE_SIZE = 100

log = common.get_logger("pull_reliefweb")

FIELDS = {
    "reports": [
        "title",
        "url",
        "date.created",
        "date.original",
        "country.iso3",
        "country.name",
        "disaster.name",
        "disaster.glide",
        "source.shortname",
        "format.name",
        "body",
    ],
    "disasters": [
        "name",
        "url",
        "date.event",
        "country.iso3",
        "country.name",
        "glide",
        "status",
        "type.name",
    ],
}


def snippet(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = " ".join(value.split())
    return text[:SNIPPET_CHARS]


def reduce_record(endpoint: str, item: dict[str, Any]) -> dict[str, Any]:
    fields = dict(item.get("fields") or {})
    if "body" in fields:
        fields["snippet"] = snippet(fields.pop("body"))
    return {"id": item.get("id"), "endpoint": endpoint, "fetched_at": common.iso_now(), "fields": fields}


def fetch(endpoint: str, appname: str, limit: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    limiter = common.RateLimiter(1.0)
    with common.make_client() as client:
        offset = 0
        while offset < limit:
            limiter.wait("reliefweb")
            body = {
                "offset": offset,
                "limit": min(PAGE_SIZE, limit - offset),
                "sort": ["date.created:desc"] if endpoint == "reports" else ["date.event:desc"],
                "fields": {"include": FIELDS[endpoint]},
            }
            response = common.request_with_retry(
                client, "POST", f"{API_URL}/{endpoint}", params={"appname": appname}, json=body, logger=log
            )
            response.raise_for_status()
            data = response.json().get("data", [])
            if not data:
                break
            records.extend(reduce_record(endpoint, item) for item in data)
            offset += len(data)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--endpoint", choices=sorted(FIELDS), action="append")
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args(argv)
    appname = os.environ.get("RELIEFWEB_APPNAME", "").strip()
    if not appname:
        log.info("RELIEFWEB_APPNAME not set, skipping optional ReliefWeb source")
        return 0
    state_path = common.raw_dir("hazards", "reliefweb") / "_state.json"
    state: dict[str, str] = common.read_json(state_path, {}) or {}
    written = 0
    try:
        for endpoint in args.endpoint or sorted(FIELDS):
            fresh = []
            for record in fetch(endpoint, appname, args.limit):
                key = f"{endpoint}:{record['id']}"
                if key not in state:
                    state[key] = record["fetched_at"]
                    fresh.append(record)
            if fresh:
                path = common.raw_dir("hazards", "reliefweb") / f"{common.iso_now()[:10]}_{endpoint}.jsonl"
                written += common.append_jsonl(path, fresh)
    except Exception as exc:
        log.error("reliefweb pull failed: %s", exc)
        common.write_status("reliefweb", False, {"error": str(exc)})
        return 1
    common.write_json(state_path, state)
    common.write_status("reliefweb", True, {"written": written})
    common.record_harvest(SOURCE_ID, {"written": written})
    return 0


if __name__ == "__main__":
    sys.exit(main())
