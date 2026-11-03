"""Incident and portfolio reports and briefing documents.

Each document is self-contained HTML (all values escaped) that is also rendered to PDF. A report carries its id, the time it was
generated, the source links with times, the score components of every affected asset, and the disclaimer. The static map is drawn
from stored geometry (see maps.py). Reports contain tenant asset names and distances; coordinates are not printed.
"""

from __future__ import annotations

import csv
import datetime as dt
import html
import io
from typing import Any

from meridian.api.db import Tx
from meridian.api.services import maps
from meridian.api.services.uploads import csv_safe
from meridian.notify import DISCLAIMER

STYLE = """
@page { size: A4; margin: 18mm 15mm 20mm; @bottom-left { content: element(footer); font: 8pt sans-serif; color: #52606d }
        @bottom-right { content: "Page " counter(page) " of " counter(pages); font: 8pt sans-serif; color: #52606d } }
body { font-family: Helvetica, Arial, sans-serif; font-size: 10pt; color: #1f2933; line-height: 1.45; max-width: 60rem; margin: 0 auto; }
h1 { font-size: 18pt; margin: 0 0 4pt } h2 { font-size: 12pt; margin: 16pt 0 4pt; border-bottom: 1px solid #cbd2d9; padding-bottom: 2pt }
.meta { color: #52606d; font-size: 9pt; margin-bottom: 10pt } table { border-collapse: collapse; width: 100%; margin: 4pt 0 }
td, th { border: 1px solid #cbd2d9; padding: 3pt 5pt; text-align: left; vertical-align: top; font-size: 9pt } th { background: #f0f4f8 }
.disclaimer { margin-top: 18pt; padding: 6pt 8pt; border: 1px solid #cbd2d9; background: #f7f9fa; font-size: 9pt }
.running { position: running(footer) }   .map { width: 100%; max-height: 82mm; object-fit: contain; border: 1px solid #cbd2d9; margin: 6pt 0 } .small { font-size: 8pt; color: #52606d } tr { break-inside: avoid }
"""


def _stamp(report_id: str, now: dt.datetime) -> str:
    return f"Report ID {html.escape(report_id)}. Generated {now:%Y-%m-%d %H:%M} UTC."


def _page(title: str, report_id: str, now: dt.datetime, body: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{html.escape(title)}</title><style>{STYLE}</style></head><body><div class=\"running\">Report {html.escape(report_id[:8])}</div>"
        f'<h1>{html.escape(title)}</h1><p class="meta">{_stamp(report_id, now)}</p>{body}'
        f'<p class="disclaimer"><strong>Disclaimer.</strong> {html.escape(DISCLAIMER)}</p></body></html>'
    )


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _components(components: dict[str, Any] | None) -> str:
    items = []
    for key, value in (components or {}).items():
        shown = round(value, 3) if isinstance(value, float) else value
        items.append(f"{_e(key.replace('_', ' '))}: {_e(shown)}")
    return "; ".join(items)


def incident_html(tx: Tx, event_id: str, report_id: str, now: dt.datetime) -> str | None:
    event = tx.one(
        """SELECT title, type, subtype, severity, status, confirmation, first_seen_at, last_seen_at, summary, uncertainty_km,
                  location_level, ST_X(ST_Centroid(geom)), ST_Y(ST_Centroid(geom)),
                  CASE WHEN geom IS NOT NULL AND uncertainty_km > 0
                       THEN ST_AsGeoJSON(ST_Buffer(ST_Centroid(geom)::geography, uncertainty_km * 1000, 24)::geometry, 5)::json END,
                  location_place_id
             FROM events WHERE id = %s""",
        (event_id,),
    )
    if event is None:
        return None
    place = tx.one("SELECT name, admin1_name, country_code FROM places WHERE id = %s", (event[14],)) if event[14] else None
    sources = tx.all(
        "SELECT source_kind, url, published_at, snippet, reliability FROM event_sources WHERE event_id = %s ORDER BY published_at NULLS LAST",
        (event_id,),
    )
    exposures = tx.all(
        """SELECT a.name, ST_X(ST_PointOnSurface(a.geom)), ST_Y(ST_PointOnSurface(a.geom)), x.distance_km, x.within_uncertainty,
                  x.level, x.score, x.components
             FROM exposures x JOIN assets a ON a.id = x.asset_id WHERE x.event_id = %s ORDER BY x.score DESC LIMIT 50""",
        (event_id,),
    )
    spec = maps.MapSpec(
        markers=[maps.Marker(r[1], r[2], r[5], str(i)) for i, r in enumerate(exposures[:15], start=1)],
        event_point=(event[11], event[12]) if event[11] is not None else None,
        circle=event[13],
        title="Incident location and affected assets",
    )
    image = maps.map_data_uri(tx, spec)
    where = ", ".join(x for x in (place[0], place[1], place[2]) if x) if place else "not resolved to a named place"
    confirmation = "confirmed by a second source" if event[5] == "confirmed" else "reported, not yet confirmed"
    body = (
        f"<h2>Summary</h2><p>{_e(event[1]).replace('_', ' ')}{' / ' + _e(event[2]).replace('_', ' ') if event[2] else ''}; severity {event[3]} of 4; "
        f"status {_e(event[4])}; {confirmation}. First seen {event[6]:%Y-%m-%d %H:%M} UTC, last update {event[7]:%Y-%m-%d %H:%M} UTC.</p>"
        f"<p>{_e(event[8])}</p>"
        f"<h2>Location and uncertainty</h2><p>Reported location: {_e(where)}; resolved at {_e(event[10] or 'unknown')} level. "
        f"The dashed circle shows an uncertainty of about {round(float(event[9] or 0))} km around the best position.</p>"
        f'<img class="map" src="{image}" alt="Map of the incident location with the uncertainty circle and numbered affected assets">'
        "<h2>Sources</h2><table><tr><th>Type</th><th>Published (UTC)</th><th>Link</th><th>Excerpt</th></tr>"
        + "".join(
            f"<tr><td>{_e(s[0])}</td><td>{s[2]:%Y-%m-%d %H:%M}</td><td>{_e(s[1] or 'no link')}</td><td>{_e((s[3] or '')[:300])}</td></tr>"
            if s[2]
            else f"<tr><td>{_e(s[0])}</td><td></td><td>{_e(s[1] or 'no link')}</td><td>{_e((s[3] or '')[:300])}</td></tr>"
            for s in sources
        )
        + "</table><h2>Affected assets</h2>"
        + (
            "<table><tr><th>#</th><th>Asset</th><th>Distance (km)</th><th>Inside uncertainty</th><th>Level</th><th>Score</th><th>Score components</th></tr>"
            + "".join(
                f"<tr><td>{i}</td><td>{_e(r[0])}</td><td>{round(float(r[3]), 1)}</td><td>{'yes' if r[4] else 'no'}</td><td>{_e(r[5])}</td>"
                f"<td>{round(float(r[6]), 2)}</td><td>{_components(r[7])}</td></tr>"
                for i, r in enumerate(exposures, start=1)
            )
            + "</table>"
            if exposures
            else "<p>No assets of this organisation are currently exposed.</p>"
        )
        + '<p class="small">The score combines event type and severity, location confidence, source reliability, recency, and '
        "distance relative to the location uncertainty; the components are listed for every asset.</p>"
    )
    return _page(f"Incident report: {event[0]}", report_id, now, body)


def portfolio_rows(tx: Tx) -> list[dict[str, Any]]:
    rows = tx.all(
        """SELECT a.name, a.criticality, a.country_code, COALESCE(max(x.score), 0), COALESCE((array_agg(x.level ORDER BY x.score DESC))[1], 'none'),
                  count(x.id), ST_X(ST_PointOnSurface(a.geom)), ST_Y(ST_PointOnSurface(a.geom))
             FROM assets a LEFT JOIN exposures x ON x.asset_id = a.id WHERE a.status = 'active'
            GROUP BY a.id ORDER BY 4 DESC, a.name LIMIT 5000"""
    )
    return [
        {
            "asset": r[0],
            "criticality": r[1],
            "country": r[2] or "",
            "highest_score": round(float(r[3]), 2),
            "highest_level": r[4],
            "events": r[5],
            "lon": r[6],
            "lat": r[7],
        }
        for r in rows
    ]


def portfolio_html(tx: Tx, report_id: str, now: dt.datetime) -> str:
    rows = portfolio_rows(tx)
    counts = dict.fromkeys(("critical", "high", "medium", "low", "none"), 0)
    for r in rows:
        counts[r["highest_level"]] += 1
    open_alerts = tx.all(
        """SELECT a.level, e.title, s.name FROM alerts a JOIN events e ON e.id = a.event_id LEFT JOIN assets s ON s.id = a.asset_id
            WHERE a.status IN ('new', 'acknowledged', 'monitoring', 'escalated')
            ORDER BY array_position(ARRAY['critical','high','medium','low'], a.level), a.last_score DESC NULLS LAST LIMIT 20"""
    )
    image = maps.map_data_uri(
        tx,
        maps.MapSpec(
            markers=[maps.Marker(r["lon"], r["lat"], r["highest_level"]) for r in rows[:2000]],
            title="Asset portfolio coloured by highest exposure level",
        ),
    )
    body = (
        "<h2>Summary</h2><p>"
        + f"{len(rows)} active assets. Highest exposure level: "
        + ", ".join(f"{counts[k]} {k}" for k in ("critical", "high", "medium", "low"))
        + f"; {counts['none']} with no current exposure.</p>"
        f'<img class="map" src="{image}" alt="Map of the asset portfolio coloured by highest exposure level">'
        '<p class="small">Marker colours: red critical, orange high, amber medium, green low, grey none.</p>'
        "<h2>Open alerts</h2>"
        + (
            "<table><tr><th>Level</th><th>Event</th><th>Asset</th></tr>"
            + "".join(f"<tr><td>{_e(a[0])}</td><td>{_e(a[1])}</td><td>{_e(a[2] or 'watch zone')}</td></tr>" for a in open_alerts)
            + "</table>"
            if open_alerts
            else "<p>There are no open alerts.</p>"
        )
        + "<h2>Assets by exposure</h2><table><tr><th>Asset</th><th>Criticality</th><th>Country</th><th>Highest score</th><th>Level</th><th>Events</th></tr>"
        + "".join(
            f"<tr><td>{_e(r['asset'])}</td><td>{r['criticality']}</td><td>{_e(r['country'])}</td><td>{r['highest_score']}</td><td>{_e(r['highest_level'])}</td><td>{r['events']}</td></tr>"
            for r in rows[:300]
        )
        + "</table>"
        + (f'<p class="small">Showing the 300 most exposed of {len(rows)} assets; the CSV export lists all.</p>' if len(rows) > 300 else "")
    )
    return _page("Portfolio exposure report", report_id, now, body)


def portfolio_csv(tx: Tx) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["asset", "criticality", "country", "highest_score", "highest_level", "events"])
    for r in portfolio_rows(tx):
        writer.writerow(
            [csv_safe(r["asset"]), r["criticality"], r["country"], r["highest_score"], r["highest_level"], r["events"]]
        )
    return out.getvalue()


def _narrative_html(text: str) -> str:
    """Paragraphs and bullet lists; the disclaimer is printed once in the footer block."""
    out: list[str] = []
    bullets: list[str] = []
    for line in (ln.strip() for ln in text.split("\n")):
        if line.startswith("- "):
            bullets.append(f"<li>{_e(line[2:])}</li>")
            continue
        if bullets:
            out.append("<ul>" + "".join(bullets) + "</ul>")
            bullets = []
        if line:
            out.append(f"<p>{_e(line)}</p>")
    if bullets:
        out.append("<ul>" + "".join(bullets) + "</ul>")
    return "".join(out)


def briefing_html(briefing: dict[str, Any]) -> str:
    """A briefing as a document. The narrative is shown as written; the evidence tables repeat the stored facts."""
    ev = briefing["evidence"]
    now = briefing["created_at"]
    narrative = _narrative_html((briefing["narrative"] or "").replace(DISCLAIMER, ""))
    outlook = ev.get("hazard_outlook") or []
    groups = ev.get("asset_groups_affected") or []
    body = (
        f"<p class=\"meta\">Period {_e(str(ev.get('period_start', ''))[:16])} to {_e(str(ev.get('period_end', ''))[:16])} UTC. {_e(briefing['kind']).capitalize()} briefing.</p>"
        f"<h2>Overview</h2>{narrative}"
        "<h2>New and resolved events</h2><p>"
        f"{ev.get('new_events_count', 0)} new events affected this organisation in the period; {ev.get('resolved_events_count', 0)} events were resolved.</p>"
        + (
            "<table><tr><th>Event</th><th>Type</th><th>Severity</th></tr>"
            + "".join(f"<tr><td>{_e(n['title'])}</td><td>{_e(n['type'])}</td><td>{n['severity']}</td></tr>" for n in ev["new_events"][:15])
            + "</table>"
            if ev.get("new_events")
            else ""
        )
        + "<h2>Asset groups affected</h2>"
        + (
            "<table><tr><th>Group</th><th>Alerts</th></tr>"
            + "".join(f"<tr><td>{_e(g['name'])}</td><td>{g['alerts']}</td></tr>" for g in groups)
            + "</table>"
            if groups
            else "<p>No asset group had an alert in this period.</p>"
        )
        + "<h2>Hazard outlook</h2>"
        + (
            "<p>Active weather service alerts that affect assets:</p><table><tr><th>Alert</th><th>Severity</th><th>Assets affected</th><th>Expires (UTC)</th></tr>"
            + "".join(
                f"<tr><td>{_e(h['title'])}</td><td>{h['severity']}</td><td>{h['assets']}</td><td>{_e((h.get('expires_at') or '')[:16])}</td></tr>"
                for h in outlook
            )
            + "</table>"
            if outlook
            else "<p>No active weather service alerts affect assets.</p>"
        )
    )
    return _page(f"{briefing['kind'].capitalize()} briefing", str(briefing["id"]), now, body)
