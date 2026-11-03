"""Shared parts of the analytics endpoints: periods, granularity, comparison, caching, CSV, and conditional responses.

Every analytics endpoint takes from, to, granularity, compare, filters, and format. Results are cached for a short time per scope
(a tenant id, or the platform) so that one tenant's numbers are never served to another; a cache entry also carries the metric
refresh time, so a refresh makes older entries unreachable.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Request, Response
from fastapi.encoders import jsonable_encoder

from meridian.api.errors import ProblemError
from meridian.api.services.uploads import csv_safe

GRANULARITIES = ("day", "week", "month")
COMPARISONS = ("none", "previous_period", "previous_year")
CACHE_SECONDS = 60
MAX_SPAN_DAYS = 366 * 5


@dataclass(frozen=True)
class Period:
    start: dt.date
    end: dt.date  # inclusive
    granularity: str

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def parse_period(
    start: dt.date | None, end: dt.date | None, granularity: str, default_days: int = 30, today: dt.date | None = None
) -> Period:
    today = today or dt.datetime.now(dt.UTC).date()
    end = end or today
    start = start or end - dt.timedelta(days=default_days - 1)
    if start > end:
        raise ProblemError(422, "from must not be after to.", code="invalid-period")
    if (end - start).days > MAX_SPAN_DAYS:
        raise ProblemError(422, "The period is longer than five years.", code="invalid-period")
    if granularity not in GRANULARITIES:
        raise ProblemError(422, "granularity must be day, week, or month.", code="invalid-granularity")
    return Period(start, end, granularity)


def comparison_period(period: Period, compare: str) -> Period | None:
    if compare == "none":
        return None
    if compare == "previous_period":
        return Period(period.start - dt.timedelta(days=period.days), period.start - dt.timedelta(days=1), period.granularity)
    if compare == "previous_year":
        def back(d: dt.date) -> dt.date:
            try:
                return d.replace(year=d.year - 1)
            except ValueError:  # 29 February
                return d.replace(year=d.year - 1, day=28)

        return Period(back(period.start), back(period.end), period.granularity)
    raise ProblemError(422, "compare must be none, previous_period, or previous_year.", code="invalid-compare")


def bucket(granularity: str, column: str) -> str:
    """SQL for the start date of the bucket that contains a date column. The column name is a fixed identifier from the caller."""
    if granularity not in GRANULARITIES:
        raise ProblemError(422, "granularity must be day, week, or month.", code="invalid-granularity")
    return f"date_trunc('{granularity}', {column})::date"


def change(current: float | None, previous: float | None) -> dict[str, float | None]:
    if current is None or previous is None:
        return {"value": current, "previous": previous, "change": None, "change_pct": None}
    delta = current - previous
    return {
        "value": current,
        "previous": previous,
        "change": round(delta, 4),
        "change_pct": round(delta / previous * 100, 2) if previous else None,
    }


# -- cache --------------------------------------------------------------------------------------------------------------
class TTLCache:
    def __init__(self, ttl: float = CACHE_SECONDS, size: int = 512) -> None:
        self.ttl, self.size = ttl, size
        self._lock = threading.Lock()
        self._items: dict[tuple[Any, ...], tuple[float, Any]] = {}

    def get_or_compute(self, key: tuple[Any, ...], producer: Callable[[], Any]) -> Any:
        now = time.monotonic()
        with self._lock:
            hit = self._items.get(key)
            if hit and now - hit[0] < self.ttl:
                return hit[1]
        value = producer()
        with self._lock:
            if len(self._items) >= self.size:
                self._items = {k: v for k, v in self._items.items() if now - v[0] < self.ttl}
                if len(self._items) >= self.size:
                    self._items.clear()
            self._items[key] = (now, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


CACHE = TTLCache()


# -- responses ------------------------------------------------------------------------------------------------------------
def csv_response(columns: list[str], rows: list[list[Any]], filename: str) -> Response:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([csv_safe(c) if isinstance(c, str) else ("" if c is None else c) for c in row])
    return Response(
        out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}.csv"', "Cache-Control": "private, no-store"},
    )


def json_response(request: Request, payload: dict[str, Any]) -> Response:
    """JSON with an ETag so that clients can revalidate cheaply; analytics are private to the signed in scope."""
    body = json.dumps(jsonable_encoder(payload), separators=(",", ":"), sort_keys=True).encode()
    tag = '"' + hashlib.sha256(body).hexdigest()[:24] + '"'
    headers = {"ETag": tag, "Cache-Control": f"private, max-age={CACHE_SECONDS}", "Vary": "Cookie, Authorization"}
    if request.headers.get("if-none-match") == tag:
        return Response(status_code=304, headers=headers)
    return Response(body, media_type="application/json", headers=headers)


def respond(
    request: Request, payload: dict[str, Any], fmt: str, columns: list[str], rows: list[list[Any]], filename: str
) -> Response:
    if fmt == "csv":
        return csv_response(columns, rows, filename)
    return json_response(request, payload)
