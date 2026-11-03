"""Incident and portfolio reports as self-contained HTML (and CSV for portfolios). All values are escaped."""

from __future__ import annotations

import csv
import html
import io
from typing import Any

from meridian.api.db import Tx
from meridian.api.services.uploads import csv_safe
from meridian.notify import DISCLAIMER


def _page(title: str, body: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{html.escape(title)}</title><style>body{{font-family:system-ui,sans-serif;max-width:60rem;margin:2rem auto;padding:0 1rem}}"
        "table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:.4rem;text-align:left}</style></head><body>"
        f"<h1>{html.escape(title)}</h1>{body}<p><strong>Disclaimer.</strong> {html.escape(DISCLAIMER)}</p></body></html>"
    )


def incident_html(tx: Tx, event_id: str) -> str | None:
    event = tx.one(
        "SELECT title, type, subtype, severity, status, confirmation, first_seen_at, last_seen_at, summary, uncertainty_km FROM events WHERE id = %s",
        (event_id,),
    )
    if event is None:
        return None
    sources = tx.all(
        "SELECT source_kind, url, published_at, snippet FROM event_sources WHERE event_id = %s ORDER BY published_at NULLS LAST",
        (event_id,),
    )
    exposures = tx.all(
        """SELECT a.name, x.distance_km, x.level, x.score FROM exposures x JOIN assets a ON a.id = x.asset_id
            WHERE x.event_id = %s ORDER BY x.score DESC LIMIT 50""",
        (event_id,),
    )
    body = (
        f"<p>{html.escape(str(event[1]))}{' / ' + html.escape(str(event[2])) if event[2] else ''}; severity {event[3]}; status {html.escape(event[4])}; "
        f"{'confirmed by a second source' if event[5] == 'confirmed' else 'reported, not yet confirmed'}. First seen {event[6]:%Y-%m-%d %H:%M} UTC, "
        f"last update {event[7]:%Y-%m-%d %H:%M} UTC. Location uncertainty about {round(float(event[9] or 0))} km.</p><p>{html.escape(event[8] or '')}</p>"
        "<h2>Sources</h2><ul>"
        + "".join(
            f"<li>{html.escape(s[0])}: {html.escape(s[1] or 'no link')} {html.escape((s[3] or '')[:300])}</li>"
            for s in sources
        )
        + "</ul><h2>Exposed assets</h2><table><tr><th>Asset</th><th>Distance (km)</th><th>Level</th><th>Score</th></tr>"
        + "".join(
            f"<tr><td>{html.escape(r[0])}</td><td>{round(float(r[1]), 1)}</td><td>{html.escape(r[2])}</td><td>{round(float(r[3]), 2)}</td></tr>"
            for r in exposures
        )
        + "</table>"
    )
    return _page(f"Incident report: {event[0]}", body)


def portfolio_rows(tx: Tx) -> list[dict[str, Any]]:
    rows = tx.all(
        """SELECT a.name, a.criticality, a.country_code, COALESCE(max(x.score), 0), COALESCE((array_agg(x.level ORDER BY x.score DESC))[1], 'none'),
                  count(x.id)
             FROM assets a LEFT JOIN exposures x ON x.asset_id = a.id WHERE a.status = 'active' GROUP BY a.id ORDER BY 4 DESC, a.name LIMIT 5000"""
    )
    return [
        {
            "asset": r[0],
            "criticality": r[1],
            "country": r[2] or "",
            "highest_score": round(float(r[3]), 2),
            "highest_level": r[4],
            "events": r[5],
        }
        for r in rows
    ]


def portfolio_html(tx: Tx) -> str:
    rows = portfolio_rows(tx)
    body = (
        "<table><tr><th>Asset</th><th>Criticality</th><th>Country</th><th>Highest score</th><th>Level</th><th>Events</th></tr>"
        + "".join(
            f"<tr><td>{html.escape(r['asset'])}</td><td>{r['criticality']}</td><td>{html.escape(r['country'])}</td><td>{r['highest_score']}</td><td>{html.escape(r['highest_level'])}</td><td>{r['events']}</td></tr>"
            for r in rows
        )
        + "</table>"
    )
    return _page("Portfolio exposure report", body)


def portfolio_csv(tx: Tx) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["asset", "criticality", "country", "highest_score", "highest_level", "events"])
    for r in portfolio_rows(tx):
        writer.writerow(
            [csv_safe(r["asset"]), r["criticality"], r["country"], r["highest_score"], r["highest_level"], r["events"]]
        )
    return out.getvalue()
