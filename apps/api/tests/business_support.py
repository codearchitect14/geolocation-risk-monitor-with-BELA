"""Synthetic business data for tests: generated once per session, loaded into the test database on demand."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import psycopg

from meridian.business import loader


def last_complete_month_end(today: dt.date | None = None) -> dt.date:
    today = today or dt.datetime.now(dt.UTC).date()
    first = today.replace(day=1)
    # The latest month that has ended: this month if today is its last day, otherwise the previous one.
    last_day = (first.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    return last_day if today == last_day else first - dt.timedelta(days=1)


def load_into(conn: psycopg.Connection[Any], directory: Path) -> dict[str, int]:
    return loader.load(conn, directory)
