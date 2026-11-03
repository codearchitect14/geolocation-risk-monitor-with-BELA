"""Cursor (keyset) pagination. Cursors are opaque, signed-free position markers that carry no authority."""

from __future__ import annotations

import base64
import json
from typing import Any

from meridian.api.errors import ProblemError

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def encode_cursor(*values: Any) -> str:
    raw = json.dumps([str(v) for v in values], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str | None, parts: int) -> list[str] | None:
    if not cursor:
        return None
    try:
        values = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ProblemError(400, "The cursor is not valid.", code="invalid-cursor") from exc
    if not isinstance(values, list) or len(values) != parts or not all(isinstance(v, str) for v in values):
        raise ProblemError(400, "The cursor is not valid.", code="invalid-cursor")
    return values


def clamp_limit(limit: int | None) -> int:
    return max(1, min(DEFAULT_LIMIT if limit is None else limit, MAX_LIMIT))


def page(rows: list[Any], limit: int, cursor_of: Any) -> dict[str, Any]:
    """Split one extra fetched row off the page; the next cursor is built from the last returned row."""
    more = len(rows) > limit
    items = rows[:limit]
    return {"items": items, "next_cursor": cursor_of(items[-1]) if more and items else None}
