"""Event lifecycle: new, developing, ongoing, resolved.

new         one source, first seen no more than developing_hours ago
developing  more than one source or update within developing_hours of first sight
ongoing     older than developing_hours and still reported inside its quiet period
resolved    nothing new for the quiet period of its type, or the feed said it ended (an NWS alert expired or was cancelled)
A new source for a resolved event reopens it.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import psycopg

from meridian.events.config import EventsConfig

STATUS_ORDER = ("new", "developing", "ongoing", "resolved")


def status_for(
    cfg: EventsConfig,
    event_type: str,
    first_seen: dt.datetime,
    last_seen: dt.datetime,
    expires_at: dt.datetime | None,
    independent_sources: int,
    updates: int,
    now: dt.datetime,
) -> str:
    quiet = dt.timedelta(hours=cfg.quiet_hours(event_type))
    if expires_at is not None and expires_at <= now and now - last_seen >= dt.timedelta(hours=1):
        return "resolved"
    if now - last_seen >= quiet:
        return "resolved"
    developing_window = dt.timedelta(hours=float(cfg.raw["status"]["developing_hours"]))
    if now - first_seen <= developing_window:
        return "developing" if independent_sources > 1 or updates > 0 else "new"
    return "ongoing"


def refresh_event_status(conn: psycopg.Connection[Any], cfg: EventsConfig, event_id: str, now: dt.datetime) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT e.type, e.first_seen_at, e.last_seen_at, e.expires_at, e.status,
                      (SELECT count(*) FROM event_updates u WHERE u.event_id = e.id AND u.update_type IN ('merged', 'revision', 'superseded')),
                      (SELECT count(DISTINCT CASE WHEN s.source_kind = 'news' THEN 'news:' || COALESCE(s.domain, s.id::text) ELSE s.source_kind END)
                         FROM event_sources s WHERE s.event_id = e.id)
                 FROM events e WHERE e.id = %s""",
            (event_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise KeyError(event_id)
        event_type, first_seen, last_seen, expires_at, current, updates, independent = row
        new_status = status_for(cfg, event_type, first_seen, last_seen, expires_at, int(independent), int(updates), now)
        if new_status != current:
            cur.execute("UPDATE events SET status = %s, updated_at = now() WHERE id = %s", (new_status, event_id))
            cur.execute(
                "INSERT INTO event_updates (event_id, update_type, detail) VALUES (%s, 'status', %s)",
                (event_id, f'{{"from": "{current}", "to": "{new_status}"}}'),
            )
    return str(new_status)


def refresh_all(conn: psycopg.Connection[Any], cfg: EventsConfig, now: dt.datetime) -> dict[str, int]:
    """Re-evaluate every event that is not resolved (run periodically)."""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM events WHERE status <> 'resolved'")
        ids = [str(r[0]) for r in cur.fetchall()]
    counts: dict[str, int] = {}
    for event_id in ids:
        status = refresh_event_status(conn, cfg, event_id, now)
        counts[status] = counts.get(status, 0) + 1
    return counts
