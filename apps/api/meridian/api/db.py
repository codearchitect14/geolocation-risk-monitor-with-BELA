"""Database access for requests.

Tenant requests run on a dedicated connection whose transaction first switches to the restricted role `meridian_app` and
sets the request context with SET LOCAL. Row Level Security policies read that context. A commit ends the transaction and
with it the SET LOCAL values, so `Tx.commit` and `Tx.rollback` apply the context again before returning: statements never
run without it, and with no context the policies match no rows.

The system connection (owner role) is used only by the authentication code, which must read credentials before a tenant is
known, and by background jobs.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg_pool import ConnectionPool

from meridian.api.settings import get_api_settings
from meridian.config import get_settings

APP_ROLE = "meridian_app"
PLATFORM_ROLE = "meridian_platform"  # member of APP_ROLE with allow-all policies, for platform staff requests

_pools: dict[str, ConnectionPool[psycopg.Connection[Any]]] = {}
_pools_lock = threading.Lock()


def get_pool() -> ConnectionPool[psycopg.Connection[Any]]:
    """The process wide connection pool for the configured database (opened on first use).

    Connecting costs several milliseconds (SCRAM authentication and backend start), and every request needs two connections,
    one for authentication and one for its transaction, so connections are reused. A connection leaves the pool in a clean
    state: callers roll back before returning it, which also ends the SET LOCAL role and request context.
    """
    dsn = get_settings().psycopg_dsn
    pool = _pools.get(dsn)
    if pool is None:
        with _pools_lock:
            pool = _pools.get(dsn)
            if pool is None:
                cfg = get_api_settings()
                pool = ConnectionPool(
                    dsn,
                    min_size=cfg.db_pool_min,
                    max_size=cfg.db_pool_max,
                    timeout=cfg.db_pool_timeout_seconds,
                    max_idle=300,
                    check=ConnectionPool.check_connection,
                    open=True,
                    name="meridian-api",
                )
                _pools[dsn] = pool
    return pool


def close_pools() -> None:
    with _pools_lock:
        pools = list(_pools.values())
        _pools.clear()
    for pool in pools:
        pool.close()


def pool_stats() -> dict[str, int]:
    pool = _pools.get(get_settings().psycopg_dsn)
    return dict(pool.get_stats()) if pool is not None else {}


@dataclass(frozen=True)
class Context:
    tenant_id: str | None
    user_id: str | None
    role: str | None
    bypass: bool = False


class Tx:
    """A connection with the request context applied."""

    def __init__(self, conn: psycopg.Connection[Any], ctx: Context, pooled: bool = False) -> None:
        self.conn, self.ctx, self.pooled = conn, ctx, pooled
        self.apply()

    def apply(self) -> None:
        with self.conn.cursor() as cur:
            cur.execute(f"SET LOCAL ROLE {PLATFORM_ROLE if self.ctx.bypass else APP_ROLE}")  # noqa: S608 - constants
            cur.execute(
                """SELECT set_config('app.tenant_id', %s, true), set_config('app.user_id', %s, true),
                          set_config('app.role', %s, true), set_config('app.bypass', %s, true)""",
                (
                    self.ctx.tenant_id or "",
                    self.ctx.user_id or "",
                    self.ctx.role or "",
                    "on" if self.ctx.bypass else "off",
                ),
            )

    def commit(self) -> None:
        self.conn.commit()
        self.apply()

    def rollback(self) -> None:
        self.conn.rollback()
        self.apply()

    def cursor(self, **kwargs: Any) -> psycopg.Cursor[Any]:
        cur: psycopg.Cursor[Any] = self.conn.cursor(**kwargs)
        return cur

    def execute(self, query: str, params: Any = None) -> psycopg.Cursor[Any]:
        cursor: psycopg.Cursor[Any] = self.conn.execute(query, params)
        return cursor

    def one(self, query: str, params: Any = None) -> tuple[Any, ...] | None:
        return self.conn.execute(query, params).fetchone()

    def all(self, query: str, params: Any = None) -> list[tuple[Any, ...]]:
        return self.conn.execute(query, params).fetchall()

    def close(self) -> None:
        release(self.conn, self.pooled)


def release(conn: psycopg.Connection[Any], pooled: bool) -> None:
    """End the transaction (and with it the request context), then return the connection to the pool or close it."""
    try:
        if not conn.closed:
            conn.rollback()
    finally:
        if pooled:
            get_pool().putconn(conn)
        elif not conn.closed:
            conn.close()


def open_tx(ctx: Context) -> Tx:
    conn = get_pool().getconn()
    try:
        return Tx(conn, ctx, pooled=True)
    except BaseException:
        release(conn, True)
        raise


@contextmanager
def system_connection() -> Iterator[psycopg.Connection[Any]]:
    """Owner role connection. The caller commits explicitly."""
    conn = get_pool().getconn()
    try:
        yield conn
    finally:
        release(conn, True)
