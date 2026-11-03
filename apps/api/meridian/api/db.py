"""Database access for requests.

Tenant requests run on a dedicated connection whose transaction first switches to the restricted role `meridian_app` and
sets the request context with SET LOCAL. Row Level Security policies read that context. A commit ends the transaction and
with it the SET LOCAL values, so `Tx.commit` and `Tx.rollback` apply the context again before returning: statements never
run without it, and with no context the policies match no rows.

The system connection (owner role) is used only by the authentication code, which must read credentials before a tenant is
known, and by background jobs.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import psycopg

from meridian.db import connect

APP_ROLE = "meridian_app"


@dataclass(frozen=True)
class Context:
    tenant_id: str | None
    user_id: str | None
    role: str | None
    bypass: bool = False


class Tx:
    """A connection with the request context applied."""

    def __init__(self, conn: psycopg.Connection[Any], ctx: Context) -> None:
        self.conn, self.ctx = conn, ctx
        self.apply()

    def apply(self) -> None:
        with self.conn.cursor() as cur:
            cur.execute(f"SET LOCAL ROLE {APP_ROLE}")  # noqa: S608 - constant identifier
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
        if not self.conn.closed:
            try:
                self.conn.rollback()
            finally:
                self.conn.close()


def open_tx(ctx: Context) -> Tx:
    return Tx(connect(), ctx)


@contextmanager
def system_connection() -> Iterator[psycopg.Connection[Any]]:
    """Owner role connection. The caller commits explicitly."""
    conn = connect()
    try:
        yield conn
    finally:
        if not conn.closed:
            conn.rollback()
            conn.close()
