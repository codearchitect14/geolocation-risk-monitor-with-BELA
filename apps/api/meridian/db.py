"""Database helpers shared by the ETL steps and, later, the API."""

from __future__ import annotations

import io
import json
import logging
import time
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg import sql

from meridian.config import get_settings

log = logging.getLogger("meridian.db")


def connect(autocommit: bool = False) -> psycopg.Connection[Any]:
    return psycopg.connect(get_settings().psycopg_dsn, autocommit=autocommit)


def copy_rows(
    conn: psycopg.Connection[Any],
    table: str,
    columns: Sequence[str],
    rows: Iterable[Sequence[Any]],
    batch: int = 50_000,
) -> int:
    """Stream rows into a table with COPY. Returns the number of rows written."""
    statement = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(*table.split(".")), sql.SQL(", ").join(sql.Identifier(c) for c in columns)
    )
    count = 0
    with conn.cursor() as cur, cur.copy(statement) as copy:
        for row in rows:
            copy.write_row(row)
            count += 1
            if count % batch == 0:
                log.info("copied %d rows into %s", count, table)
    return count


@contextmanager
def etl_step(conn: psycopg.Connection[Any], name: str) -> Iterator[dict[str, Any]]:
    """Record an ETL step in etl_runs. The body fills the yielded stats dictionary."""
    stats: dict[str, Any] = {}
    with conn.cursor() as cur:
        cur.execute("INSERT INTO etl_runs (step) VALUES (%s) RETURNING id", (name,))
        row = cur.fetchone()
        assert row is not None
        run_id = row[0]
    conn.commit()
    started = time.monotonic()
    try:
        yield stats
    except BaseException:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE etl_runs SET status = 'failed', finished_at = now(), stats = %s WHERE id = %s",
                (json.dumps(stats, default=str), run_id),
            )
        conn.commit()
        raise
    stats["seconds"] = round(time.monotonic() - started, 1)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE etl_runs SET status = 'ok', finished_at = now(), stats = %s WHERE id = %s",
            (json.dumps(stats, default=str), run_id),
        )
    conn.commit()
    log.info("step %s done: %s", name, stats)


def text_buffer(lines: Iterable[str]) -> io.StringIO:
    return io.StringIO("".join(lines))
