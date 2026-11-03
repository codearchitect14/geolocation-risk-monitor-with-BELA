"""Append-only audit trail. The hash chain is computed by the database; this module only inserts."""

from __future__ import annotations

import json
import re
from typing import Any

import psycopg

_SENSITIVE = re.compile(
    r"pass|secret|token|code|coord|geom|location|wkt|key|authorization|cookie|(^|_)(lat|lon|lng|latitude|longitude)(_|$)",
    re.I,
)
_ALLOWED_EXACT = {"latitude_redacted"}


def sanitize(value: Any, depth: int = 0) -> Any:
    """Remove passwords, tokens, secrets, and coordinates from audit details."""
    if depth > 4:
        return "[truncated]"
    if isinstance(value, dict):
        return {
            str(k): (
                "[redacted]" if _SENSITIVE.search(str(k)) and str(k) not in _ALLOWED_EXACT else sanitize(v, depth + 1)
            )
            for k, v in list(value.items())[:50]
        }
    if isinstance(value, list):
        return [sanitize(v, depth + 1) for v in value[:50]]
    if isinstance(value, str):
        return value[:300]
    return value


def record(
    conn: psycopg.Connection[Any],
    action: str,
    *,
    tenant_id: str | None = None,
    actor_user_id: str | None = None,
    actor_type: str = "user",
    object_type: str | None = None,
    object_id: str | None = None,
    ip: str | None = None,
    request_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO audit_log (tenant_id, actor_user_id, actor_type, action, object_type, object_id, ip, request_id, detail)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                tenant_id,
                actor_user_id,
                actor_type,
                action,
                object_type,
                object_id,
                ip,
                request_id,
                json.dumps(sanitize(detail or {})),
            ),
        )


def verify(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute("SELECT checked, first_bad_id FROM audit_verify()")
        row = cur.fetchone()
    assert row is not None
    return {"entries_checked": row[0], "intact": row[1] is None, "first_bad_id": row[1]}
