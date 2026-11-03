"""Alert lifecycle: allowed status changes and automatic escalation of alerts nobody has acknowledged."""

from __future__ import annotations

import json
from typing import Any

import psycopg

from meridian import notify
from meridian.api.errors import ProblemError

STATUSES = ("new", "acknowledged", "monitoring", "escalated", "dismissed", "resolved")
OPEN = ("new", "acknowledged", "monitoring", "escalated")
TRANSITIONS: dict[str, frozenset[str]] = {
    "new": frozenset({"acknowledged", "monitoring", "escalated", "dismissed", "resolved"}),
    "acknowledged": frozenset({"monitoring", "escalated", "dismissed", "resolved"}),
    "monitoring": frozenset({"acknowledged", "escalated", "dismissed", "resolved"}),
    "escalated": frozenset({"acknowledged", "monitoring", "dismissed", "resolved"}),
    "dismissed": frozenset({"new"}),
    "resolved": frozenset({"new"}),
}


def check_transition(old: str, new: str) -> None:
    if new != old and new not in TRANSITIONS[old]:
        raise ProblemError(
            409,
            f"An alert that is {old} cannot become {new}.",
            code="invalid-transition",
            extra={"allowed": sorted(TRANSITIONS[old])},
        )


def escalate_due(conn: psycopg.Connection[Any]) -> list[str]:
    """Escalate alerts still in status new after the escalation time of the rule that raised them.

    Returns the ids that were escalated. Each change is recorded in alert_events as an automatic status change.
    """
    rows = conn.execute(
        """SELECT a.id, a.tenant_id, (r.escalation->>'after_minutes')::int
             FROM alerts a JOIN alert_rules r ON r.id = a.rule_id
            WHERE a.status = 'new' AND r.enabled AND r.escalation ? 'after_minutes'
              AND a.created_at <= now() - make_interval(mins => (r.escalation->>'after_minutes')::int)
            FOR UPDATE OF a SKIP LOCKED"""
    ).fetchall()
    ids: list[str] = []
    for alert_id, tenant_id, minutes in rows:
        conn.execute(
            "UPDATE alerts SET status = 'escalated', escalated_at = now(), updated_at = now() WHERE id = %s", (alert_id,)
        )
        conn.execute(
            "INSERT INTO alert_events (alert_id, tenant_id, kind, detail) VALUES (%s, %s, 'status_change', %s)",
            (alert_id, tenant_id, json.dumps({"from": "new", "to": "escalated", "automatic": True, "after_minutes": minutes})),
        )
        notify.enqueue_webhooks(conn, [str(alert_id)], kind="alert.escalated")
        ids.append(str(alert_id))
    conn.commit()
    for alert_id in ids:
        notify.announce_status(conn, alert_id, "alert.escalated")
    return ids
