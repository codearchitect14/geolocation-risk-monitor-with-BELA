"""Accepted corrections: a record on the event and, with the submitter's consent, a candidate for the next gold set round.

A correction is data derived from tenant use, so it only leaves the tenant (as an annotation candidate) when the submitter ticked
the consent box. Candidates are not added to the gold set automatically: annotators review them first (see data/annotation).
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import psycopg

from meridian.config import get_settings

CANDIDATE_FILE = ("annotation", "correction_candidates.jsonl")


def accept(conn: psycopg.Connection[Any], correction_id: str) -> dict[str, Any]:
    """Record an accepted correction on its event; returns {"candidate": bool}. Uses an owner connection."""
    row = conn.execute(
        "SELECT event_id, kind, details, consent_for_gold, tenant_id FROM correction_requests WHERE id = %s", (correction_id,)
    ).fetchone()
    if row is None:
        return {"candidate": False}
    event_id, kind, details, consent, tenant_id = row
    public_detail = {"correction_id": correction_id, "kind": kind}
    if kind == "duplicate" and details.get("duplicate_of"):
        public_detail["duplicate_of"] = details["duplicate_of"]
    conn.execute(
        "INSERT INTO event_updates (event_id, update_type, detail) VALUES (%s, 'correction_accepted', %s)",
        (event_id, json.dumps(public_detail)),
    )
    if not consent:
        return {"candidate": False}
    event = conn.execute(
        "SELECT title, type, subtype, location_level FROM events WHERE id = %s", (event_id,)
    ).fetchone()
    urls = [r[0] for r in conn.execute("SELECT url FROM event_sources WHERE event_id = %s AND url IS NOT NULL LIMIT 5", (event_id,))]
    record = {
        "correction_id": correction_id,
        "kind": kind,
        "event_id": str(event_id),
        "event": {"title": event[0], "type": event[1], "subtype": event[2], "location_level": event[3]} if event else None,
        "suggested_place": details.get("suggested_place"),
        "suggested_type": details.get("suggested_type"),
        "duplicate_of": details.get("duplicate_of"),
        "source_urls": urls,
        "accepted_at": dt.datetime.now(dt.UTC).isoformat(),
        "consent": True,
    }
    path = get_settings().data_dir.joinpath(*CANDIDATE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, default=str) + "\n")
    conn.execute("UPDATE correction_requests SET gold_exported_at = now() WHERE id = %s", (correction_id,))
    _ = tenant_id
    return {"candidate": True}
