"""Accelerated replay of recorded hazard feed records.

The records (earthquakes from the public domain USGS feed) are re-timed so that the newest one happened just now. The oldest part is
loaded at once as history; the rest is played with the real gaps between records divided by a speed factor (capped per record),
so incidents, exposures, and alerts appear on screen while a demonstration runs. Everything goes through the normal ingestion,
exposure, and alert code. Replayed incidents say so in their summary, because the times are not the original times.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import psycopg

from meridian.events import service
from meridian.events.config import EventsConfig
from meridian.events.normalizers import usgs
from meridian.events.types import NormalizedEvent

NOTE = "Replay of a recorded feed record, re-timed for demonstration. "


def load(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line)["feature"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return sorted(rows, key=lambda f: f["properties"]["time"])


def retime(features: list[dict[str, Any]], anchor: dt.datetime) -> list[dict[str, Any]]:
    """Shift every record by the same amount so that the newest one is at `anchor` minus one minute."""
    newest = max(f["properties"].get("updated") or f["properties"]["time"] for f in features)
    shift_ms = int((anchor - dt.timedelta(minutes=1)).timestamp() * 1000) - newest
    shifted = copy.deepcopy(features)
    for feature in shifted:
        props = feature["properties"]
        props["time"] += shift_ms
        if props.get("updated"):
            props["updated"] += shift_ms
    return shifted


def run(
    conn: psycopg.Connection[Any],
    cfg: EventsConfig,
    path: Path,
    *,
    speed: float = 3600.0,
    max_wait: float = 2.0,
    preload: float = 0.7,
    limit: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    features = load(path)[-limit:] if limit else load(path)
    if not features:
        return {"records": 0}
    anchor = now or dt.datetime.now(dt.UTC)
    features = retime(features, anchor)
    history = int(len(features) * preload)
    played: list[float] = []

    def records() -> Iterator[NormalizedEvent | tuple[str, None]]:
        previous: float | None = None
        for index, feature in enumerate(features):
            ne = usgs.normalize(feature, cfg)
            if ne is None:
                yield ("invalid", None)
                continue
            ne.summary = NOTE + (ne.summary or "")
            at = ne.occurred_at.timestamp() if ne.occurred_at else 0.0
            if index >= history and previous is not None:
                wait = min(max_wait, max(0.0, (at - previous) / speed))
                played.append(wait)
                sleep(wait)
            previous = at
            yield ne

    run_result = service._ingest_many(conn, cfg, records(), now=None)
    summary = run_result.summary()
    summary.update(records=len(features), loaded_as_history=history, played_live=len(features) - history)
    summary["seconds_waited"] = round(sum(played), 1)
    return summary
