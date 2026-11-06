"""Phase 6: alert lifecycle, escalation, notifications, incident detail, briefings, reports, and corrections."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import psycopg
import pytest

from meridian import notify
from meridian.api import worker
from meridian.api.services import briefings, lifecycle, maps, render, reports
from meridian.api.services.mailer import CaptureMailer
from tests.api_support import World, login

API = "/api/v1"
needs_pdf = pytest.mark.skipif(render.html_to_pdf("<p>x</p>") is None, reason="WeasyPrint libraries are not installed")


# -- lifecycle ----------------------------------------------------------------------------------------------------------------
def patch(client: Any, alert: str, **body: Any) -> Any:
    return client.patch(f"{API}/alerts/{alert}", json=body)


def test_status_transitions_follow_the_lifecycle(client: Any, world: World, conn: psycopg.Connection[Any]) -> None:
    login(client, world, "analyst")
    alert = world.alerts["A"]
    assert patch(client, alert, status="acknowledged").json()["status"] == "acknowledged"
    stamp = conn.execute("SELECT acknowledged_at FROM alerts WHERE id = %s", (alert,)).fetchone()
    assert stamp is not None and stamp[0] is not None
    refused = patch(client, alert, status="new")
    assert refused.status_code == 409 and refused.json()["type"].endswith("invalid-transition")
    assert "monitoring" in refused.json()["allowed"] and "new" not in refused.json()["allowed"]
    assert patch(client, alert, status="monitoring").json()["status"] == "monitoring"
    assert patch(client, alert, status="escalated").json()["status"] == "escalated"
    assert patch(client, alert, status="dismissed").status_code == 422  # reason is mandatory
    assert patch(client, alert, status="dismissed", dismissal_reason="  ").status_code == 422
    done = patch(client, alert, status="dismissed", dismissal_reason="Known maintenance")
    assert done.json()["status"] == "dismissed" and done.json()["dismissal_reason"] == "Known maintenance"
    assert patch(client, alert, status="acknowledged").status_code == 409  # a closed alert reopens as new only
    reopened = patch(client, alert, status="new")
    assert reopened.json()["status"] == "new" and reopened.json()["dismissal_reason"] is None
    assert patch(client, alert, status="resolved").json()["status"] == "resolved"
    history = client.get(f"{API}/alerts/{alert}").json()["history"]
    changes = [h["detail"] for h in history if h["kind"] == "status_change"]
    assert [c["to"] for c in changes] == ["acknowledged", "monitoring", "escalated", "dismissed", "new", "resolved"]
    assert changes[3]["reason"] == "Known maintenance" and all(h["actor_id"] for h in history if h["kind"] == "status_change")
    assert patch(client, alert, status="resolved").status_code == 200  # no change is not an error


def test_assignment_comments_and_filters(client: Any, world: World) -> None:
    login(client, world, "manager")
    alert = world.alerts["A"]
    mine = patch(client, alert, assignee_id=world.users["analyst"])
    assert mine.json()["assignee_id"] == world.users["analyst"]
    assert patch(client, alert, assignee_id=world.users["b_manager"]).status_code == 422  # another tenant's user
    login(client, world, "analyst")
    assert [a["id"] for a in client.get(f"{API}/alerts", params={"mine": "true"}).json()["items"]] == [alert]
    assert client.post(f"{API}/alerts/{alert}/comments", json={"text": "Calling the site now"}).status_code == 201
    login(client, world, "manager")
    assert client.get(f"{API}/alerts", params={"mine": "true"}).json()["items"] == []
    assert len(client.get(f"{API}/alerts", params={"assignee_id": world.users["analyst"]}).json()["items"]) == 1
    kinds = [h["kind"] for h in client.get(f"{API}/alerts/{alert}").json()["history"]]
    assert kinds.count("assignment") == 1 and kinds.count("comment") == 1
    assert patch(client, alert, assignee_id=None).json()["assignee_id"] is None


def test_status_changes_reach_the_live_stream(client: Any, world: World) -> None:
    login(client, world, "analyst")
    subscription = notify.Subscription(f"alerts:{world.tenants['A']}")
    other = notify.Subscription(f"alerts:{world.tenants['B']}")
    try:
        patch(client, world.alerts["A"], status="acknowledged")
        message = subscription.get(timeout=2)
        assert other.get(timeout=0.2) is None
    finally:
        subscription.close()
        other.close()
    assert message is not None
    payload = json.loads(message)
    assert payload["kind"] == "alert.updated" and payload["alert"]["status"] == "acknowledged"
    assert "latitude" not in message


def test_unacknowledged_alerts_escalate_on_schedule(world: World, conn: psycopg.Connection[Any]) -> None:
    conn.execute("UPDATE alert_rules SET escalation = '{\"after_minutes\": 30}' WHERE id = %s", (world.rules["A"],))
    conn.execute("UPDATE alerts SET rule_id = %s, created_at = now() - interval '2 hours' WHERE id = %s", (world.rules["A"], world.alerts["A"]))
    conn.execute("UPDATE alerts SET rule_id = %s, created_at = now() - interval '2 hours' WHERE id = %s", (world.rules["B"], world.alerts["B"]))
    conn.execute("UPDATE webhooks SET min_level = 'low' WHERE id = %s", (world.hooks["A"],))
    conn.commit()
    assert lifecycle.escalate_due(conn) == [world.alerts["A"]]  # B's rule has no escalation time
    row = conn.execute("SELECT status, escalated_at FROM alerts WHERE id = %s", (world.alerts["A"],)).fetchone()
    assert row is not None and row[0] == "escalated" and row[1] is not None
    event = conn.execute(
        "SELECT detail FROM alert_events WHERE alert_id = %s AND kind = 'status_change'", (world.alerts["A"],)
    ).fetchone()
    assert event is not None and event[0] == {"from": "new", "to": "escalated", "automatic": True, "after_minutes": 30}
    delivery = conn.execute("SELECT kind FROM webhook_deliveries WHERE alert_id = %s", (world.alerts["A"],)).fetchone()
    assert delivery == ("alert.escalated",)
    assert lifecycle.escalate_due(conn) == []  # only alerts still new, and only once
    # An acknowledged alert is left alone even when it is old.
    conn.execute("UPDATE alerts SET status = 'acknowledged' WHERE id = %s", (world.alerts["B"],))
    conn.execute("UPDATE alert_rules SET escalation = '{\"after_minutes\": 5}' WHERE id = %s", (world.rules["B"],))
    conn.commit()
    assert lifecycle.escalate_due(conn) == []
    assert worker.run_once()["escalated"] == 0


# -- notifications ------------------------------------------------------------------------------------------------------------
def new_alert_history(conn: psycopg.Connection[Any], world: World, key: str = "A", quiet: bool = False) -> None:
    conn.execute("DELETE FROM alert_events WHERE alert_id = %s", (world.alerts[key],))
    conn.execute(
        "INSERT INTO alert_events (alert_id, tenant_id, kind, detail) VALUES (%s, %s, 'created', %s)",
        (world.alerts[key], world.tenants[key], json.dumps({"quiet_hours": quiet})),
    )
    conn.commit()


def test_new_alerts_are_emailed_to_the_right_people_without_coordinates(world: World, conn: psycopg.Connection[Any]) -> None:
    new_alert_history(conn, world)
    conn.execute("UPDATE users SET notify_email = false WHERE id = %s", (world.users["manager"],))
    conn.commit()
    mailer = CaptureMailer()
    sent = notify.email_new_alerts(conn, [world.alerts["A"], world.alerts["B"]], mailer)
    recipients = sorted(to for to, _, _ in mailer.sent)
    assert sent == 2 and recipients == ["admin@example.org", "analyst@example.org"]  # not the viewer, not opted out, not tenant B
    _, subject, body = mailer.sent[0]
    assert subject == "1 new alert" and "A near" in body and "Fire near A" in body and "1.2 km" in body
    assert "/app/alerts/" in body and "not official warnings" in body
    assert "39.8" not in body and "-89.6" not in body  # no coordinates in mail
    logged = conn.execute("SELECT detail FROM alert_events WHERE alert_id = %s AND kind = 'notification'", (world.alerts["A"],)).fetchone()
    assert logged == ({"channel": "email", "recipients": 2},)
    assert conn.execute("SELECT count(*) FROM alert_events WHERE alert_id = %s AND kind = 'notification'", (world.alerts["B"],)).fetchone() == (0,)


def test_quiet_hours_and_updates_do_not_send_email(world: World, conn: psycopg.Connection[Any]) -> None:
    mailer = CaptureMailer()
    new_alert_history(conn, world, quiet=True)
    assert notify.email_new_alerts(conn, [world.alerts["A"]], mailer) == 0
    conn.execute("DELETE FROM alert_events WHERE alert_id = %s", (world.alerts["A"],))
    conn.execute(
        "INSERT INTO alert_events (alert_id, tenant_id, kind, detail) VALUES (%s, %s, 'update', '{}')", (world.alerts["A"], world.tenants["A"])
    )
    conn.commit()
    assert notify.email_new_alerts(conn, [world.alerts["A"]], mailer) == 0 and mailer.sent == []


def test_email_preference_is_a_personal_setting(client: Any, world: World, conn: psycopg.Connection[Any]) -> None:
    login(client, world, "analyst")
    assert client.get(f"{API}/auth/me").json()["notifications"] == {"email": True}
    assert client.patch(f"{API}/auth/me/notifications", json={"email": False}).json() == {"notifications": {"email": False}}
    assert client.get(f"{API}/auth/me").json()["notifications"] == {"email": False}
    row = conn.execute("SELECT notify_email FROM users WHERE id = %s", (world.users["analyst"],)).fetchone()
    assert row == (False,)
    assert client.patch(f"{API}/auth/me/notifications", json={"email": "maybe"}).status_code == 422


# -- incident detail ----------------------------------------------------------------------------------------------------------
def test_incident_detail_has_location_places_timeline_and_history(client: Any, world: World, conn: psycopg.Connection[Any]) -> None:
    event = world.events["A"]
    article = conn.execute(
        "INSERT INTO articles (url, url_hash, title) VALUES ('https://news.example/A', '\\x01', 'Fire') RETURNING id"
    ).fetchone()
    assert article is not None
    conn.execute("UPDATE event_sources SET article_id = %s WHERE event_id = %s", (article[0], event))
    conn.execute(
        "INSERT INTO mentions (article_id, span_start, span_end, surface, place_id, route) VALUES (%s, 0, 11, 'Springfield', 1, 'accept')",
        (article[0],),
    )
    conn.execute("UPDATE events SET location_place_id = 1 WHERE id = %s", (event,))
    conn.execute("INSERT INTO event_updates (event_id, update_type, detail) VALUES (%s, 'severity_changed', '{\"to\": 3}')", (event,))
    # An older fire of the same type nearby, a newer one, a different type, and one that is too far away.
    for title, kind, days, lon in (
        ("Old fire nearby", "industrial_accident", 40, -89.5),
        ("Newer fire", "industrial_accident", -2, -89.5),
        ("Old flood", "natural_hazard", 40, -89.5),
        ("Old fire far away", "industrial_accident", 40, -80.0),
    ):
        conn.execute(
            """INSERT INTO events (type, severity, status, first_seen_at, last_seen_at, title, geom, uncertainty_km)
               VALUES (%s, 2, 'resolved', now() - make_interval(days => %s), now() - make_interval(days => %s), %s,
                       ST_SetSRID(ST_MakePoint(%s, 39.80), 4326), 5)""",
            (kind, days, days, title, lon),
        )
    conn.commit()
    login(client, world, "viewer")
    detail = client.get(f"{API}/events/{event}").json()
    location = detail["location"]
    assert location["place"]["name"] == "Springfield" and location["uncertainty_km"] == 25
    ring = location["uncertainty_circle"]["coordinates"][0]
    assert ring[0] == ring[-1] and len(ring) > 20
    assert [p["name"] for p in detail["linked_places"]] == ["Springfield"] and detail["linked_places"][0]["is_event_location"]
    kinds = [t["kind"] for t in detail["timeline"]]
    assert kinds == sorted(kinds, key=lambda k: k != "source") or set(kinds) == {"source", "update"}
    assert [t["at"] for t in detail["timeline"]] == sorted(t["at"] for t in detail["timeline"])
    assert [s["title"] for s in detail["similar_past_incidents"]] == ["Old fire nearby"]
    assert 5 < detail["similar_past_incidents"][0]["distance_km"] < 15
    assert detail["exposures"][0]["asset_name"] == "A near" and detail["exposures"][0]["components"]
    assert isinstance(detail["location_candidates"], list)
    assert detail["sources"][0]["snippet"] and detail["sources"][0]["url"].startswith("https://")


# -- briefings ----------------------------------------------------------------------------------------------------------------
def add_nws_alert(conn: psycopg.Connection[Any], world: World) -> None:
    """An active weather service alert that exposes tenant A's asset, and a resolved event that did too."""
    row = conn.execute(
        """INSERT INTO events (type, subtype, severity, status, first_seen_at, last_seen_at, title, geom, uncertainty_km, expires_at)
           VALUES ('natural_hazard', 'storm', 3, 'ongoing', now(), now(), 'Severe Thunderstorm Warning', ST_SetSRID(ST_MakePoint(-89.64, 39.8), 4326),
                   10, now() + interval '6 hours') RETURNING id"""
    ).fetchone()
    assert row is not None
    conn.execute(
        "INSERT INTO event_sources (event_id, source_kind, source_ref, url) VALUES (%s, 'nws', 'urn:nws:1', 'https://api.weather.example/1')", (row[0],)
    )
    conn.execute(
        "INSERT INTO exposures (tenant_id, event_id, asset_id, distance_km, within_uncertainty, score, level, components, config_version) VALUES (%s, %s, %s, 2, true, 0.5, 'medium', '{}', 'v1')",
        (world.tenants["A"], row[0], world.assets["A_near"]),
    )
    conn.execute(
        "INSERT INTO asset_group_members (group_id, asset_id) VALUES (%s, %s)", (world.groups["A"], world.assets["A_near"])
    )
    conn.execute("UPDATE events SET status = 'resolved' WHERE id = %s", (world.events["B"],))
    conn.commit()


def test_briefing_evidence_covers_events_groups_and_hazard_outlook(client: Any, world: World, conn: psycopg.Connection[Any]) -> None:
    add_nws_alert(conn, world)
    login(client, world, "manager")
    made = client.post(f"{API}/briefings", json={"kind": "daily"})
    assert made.status_code == 201, made.text
    evidence = made.json()["evidence"]
    assert [h["title"] for h in evidence["hazard_outlook"]] == ["Severe Thunderstorm Warning"] and evidence["hazard_outlook"][0]["assets"] == 1
    assert {e["title"] for e in evidence["new_events"]} >= {"Fire near A", "Severe Thunderstorm Warning"}
    assert all(e["title"] != "Fire near B" for e in evidence["new_events"])  # another tenant's exposure is invisible
    assert evidence["resolved_events"] == []  # B's event is resolved but never exposed tenant A
    assert evidence["asset_groups_affected"] == [{"name": "Group A", "alerts": 1}]
    narrative = made.json()["narrative"]
    assert "Hazard outlook: Severe Thunderstorm Warning" in narrative and "Group A (1)" in narrative
    assert briefings.validate_narrative(narrative, evidence)


def test_model_summary_must_match_the_evidence(world: World) -> None:
    evidence = {
        "period_start": "2026-11-01T00:00:00+00:00", "period_end": "2026-11-02T00:00:00+00:00", "total_alerts": 1,
        "alerts_by_level": {"critical": 0, "high": 1, "medium": 0, "low": 0},
        "items": [{"level": "high", "title": "Fire near Springfield", "asset": "Plant 7", "distance_km": 3.2, "confirmation": "reported, not yet confirmed", "source_url": "https://news.example/a"}],
        "new_events": [], "resolved_events": [], "asset_groups_affected": [], "hazard_outlook": [],
    }  # fmt: skip

    def writer(summary: str) -> Any:
        return lambda e: summary + "\n\n" + briefings.template_narrative(e)

    good = writer("One high alert concerns a fire near Springfield and Plant 7.")
    assert briefings.narrative_for(evidence, good)[1] == "local_model_validated_v1"
    for invented in (
        "A fire near Shelbyville is 3.2 km from Plant 7.",  # unknown place
        "The fire near Springfield injured 12 people.",  # unknown number
        "Plant 7 and Acme Corporation are affected.",  # unknown organisation
    ):
        text, version = briefings.narrative_for(evidence, writer(invented))
        assert version == "briefing_template_v1" and "Shelbyville" not in text and "Acme" not in text


@needs_pdf
def test_briefing_exports_as_html_and_pdf_and_by_email(client: Any, world: World, conn: psycopg.Connection[Any], mailer: CaptureMailer) -> None:
    add_nws_alert(conn, world)
    login(client, world, "manager")
    briefing = client.post(f"{API}/briefings", json={"kind": "weekly"}).json()["id"]
    page = client.get(f"{API}/briefings/{briefing}", params={"format": "html"})
    assert page.status_code == 200 and "Hazard outlook" in page.text and "not official warnings" in page.text
    assert page.headers["content-security-policy"].startswith("default-src 'none'") and "<script" not in page.text
    pdf = client.get(f"{API}/briefings/{briefing}", params={"format": "pdf"})
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and pdf.headers["content-type"] == "application/pdf"
    sent = client.post(f"{API}/briefings/{briefing}/email", json={"to": ["analyst@example.org"]})
    assert sent.status_code == 200 and sent.json() == {"sent": 1, "attachment": "briefing.pdf"}
    assert mailer.sent[0][0] == "analyst@example.org" and mailer.attachments[0][0][1].startswith(b"%PDF")
    everyone = client.post(f"{API}/briefings/{briefing}/email", json={}).json()
    assert everyone["sent"] == 4  # analyst, manager, admin, viewer all have email on
    outside = client.post(f"{API}/briefings/{briefing}/email", json={"to": ["b_manager@example.org"]})
    assert outside.status_code == 422 and len(mailer.sent) == 5  # only users of this organisation
    assert client.get(f"{API}/briefings/{briefing}", params={"format": "docx"}).status_code == 422
    login(client, world, "b_manager")
    assert client.get(f"{API}/briefings/{briefing}", params={"format": "pdf"}).status_code == 404
    assert client.post(f"{API}/briefings/{briefing}/email", json={}).status_code == 404
    login(client, world, "viewer")
    assert client.post(f"{API}/briefings/{briefing}/email", json={}).status_code == 403


def test_scheduled_briefings_are_created_once_and_emailed(world: World, conn: psycopg.Connection[Any]) -> None:
    conn.execute(
        "UPDATE tenants SET settings = %s WHERE id = %s",
        (json.dumps({"risk_config": {"daily_briefing": True, "weekly_briefing": True, "briefing_email": True}}), world.tenants["A"]),
    )
    conn.execute("DELETE FROM briefings")
    conn.commit()
    monday = dt.datetime(2026, 11, 2, 7, 30, tzinfo=dt.UTC)
    mailer = CaptureMailer()
    first = worker.generate_briefings(conn, monday, mailer)
    assert first["daily"] == 1 and first["weekly"] == 1 and first["emailed"] == 8  # two briefings to four opted-in users
    again = worker.generate_briefings(conn, monday, mailer)
    assert again["daily"] == 0 and again["weekly"] == 0  # repeat runs create nothing
    rows = conn.execute("SELECT kind, period_start, tenant_id FROM briefings ORDER BY kind").fetchall()
    assert [(r[0], r[1].astimezone(dt.UTC).date().isoformat(), str(r[2])) for r in rows] == [
        ("daily", "2026-11-01", world.tenants["A"]), ("weekly", "2026-10-26", world.tenants["A"])
    ]
    assert worker.generate_briefings(conn, monday.replace(hour=3), mailer) == {"daily": 0, "weekly": 0, "emailed": 0}  # before 06:00 UTC
    tuesday = worker.generate_briefings(conn, dt.datetime(2026, 11, 3, 8, 0, tzinfo=dt.UTC), mailer)
    assert tuesday["daily"] == 1 and tuesday["weekly"] == 0


# -- reports ------------------------------------------------------------------------------------------------------------------
@needs_pdf
def test_incident_report_is_a_complete_pdf_and_html(client: Any, world: World) -> None:
    login(client, world, "manager")
    made = client.post(f"{API}/reports/incident/{world.events['A']}")
    assert made.status_code == 201, made.text
    report = made.json()
    assert report["formats"] == ["html", "pdf"] and report["status"] == "ready"
    page = client.get(f"{API}/reports/{report['id']}", params={"format": "html"}).text
    assert f"Report ID {report['id']}" in page and "UTC." in page  # report id and timestamp
    assert "not official warnings" in page  # disclaimer
    assert "https://news.example/A" in page and "A fire was reported." in page  # sources with links
    assert "type weight" in page and "proximity" in page  # score components
    assert "data:image/png;base64," in page  # static map rendered by the browser
    assert "39.8" not in page.split("<img")[0] + page.split("alt=")[-1]  # asset coordinates are not printed
    assert "A near" in page and "B near" not in page and "Fire near B" not in page
    pdf = client.get(f"{API}/reports/{report['id']}", params={"format": "pdf"})
    assert pdf.content.startswith(b"%PDF") and len(pdf.content) > 5000 and "attachment" in pdf.headers["content-disposition"]
    assert client.get(f"{API}/reports/{report['id']}", params={"format": "csv"}).status_code == 404
    assert [r["id"] for r in client.get(f"{API}/reports").json()["items"]][0] == report["id"]


@needs_pdf
def test_portfolio_report_formats_and_isolation(client: Any, world: World) -> None:
    login(client, world, "manager")
    report = client.post(f"{API}/reports/portfolio").json()
    assert report["formats"] == ["html", "pdf", "csv"]
    page = client.get(f"{API}/reports/{report['id']}", params={"format": "html"}).text
    assert "A near" in page and "A far" in page and "B near" not in page and "Open alerts" in page
    csv_text = client.get(f"{API}/reports/{report['id']}", params={"format": "csv"}).text
    assert csv_text.splitlines()[0] == "asset,criticality,country,highest_score,highest_level,events"
    login(client, world, "b_manager")
    assert client.get(f"{API}/reports/{report['id']}", params={"format": "pdf"}).status_code == 404
    assert report["id"] not in [r["id"] for r in client.get(f"{API}/reports").json()["items"]]
    login(client, world, "analyst")
    assert client.post(f"{API}/reports/portfolio").status_code == 403


def test_reports_survive_without_pdf_libraries(client: Any, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(render, "html_to_pdf", lambda html: None)
    monkeypatch.setattr(render, "svg_to_png", lambda svg: None)
    login(client, world, "manager")
    report = client.post(f"{API}/reports/incident/{world.events['A']}").json()
    assert report["formats"] == ["html"]
    page = client.get(f"{API}/reports/{report['id']}", params={"format": "html"}).text
    assert "data:image/svg+xml;base64," in page  # the SVG map is embedded instead
    assert client.get(f"{API}/reports/{report['id']}", params={"format": "pdf"}).status_code == 404
    pdf_less = client.post(f"{API}/briefings", json={"kind": "daily"}).json()["id"]
    assert client.get(f"{API}/briefings/{pdf_less}", params={"format": "pdf"}).status_code == 503


def test_report_text_is_escaped(client: Any, world: World, conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(render, "html_to_pdf", lambda html: None)
    monkeypatch.setattr(render, "svg_to_png", lambda svg: None)
    conn.execute("UPDATE events SET title = '<script>alert(1)</script>', summary = '<img src=x onerror=alert(1)>' WHERE id = %s", (world.events["A"],))
    conn.execute("UPDATE assets SET name = '<b>=cmd()</b>' WHERE id = %s", (world.assets["A_near"],))
    conn.commit()
    login(client, world, "manager")
    report = client.post(f"{API}/reports/incident/{world.events['A']}").json()
    page = client.get(f"{API}/reports/{report['id']}", params={"format": "html"}).text
    assert "<script>alert" not in page and "&lt;script&gt;" in page and "<img src=x" not in page and "<b>=cmd" not in page


def test_map_is_schematic_and_never_requests_tiles() -> None:
    spec = maps.MapSpec(
        markers=[maps.Marker(4.4, 51.9, "high", "1"), maps.Marker(4.6, 52.0, "low", "2")],
        event_point=(4.5, 51.95),
        circle={"type": "Polygon", "coordinates": [[[4.3, 51.8], [4.7, 51.8], [4.7, 52.1], [4.3, 52.1], [4.3, 51.8]]]},
    )
    svg = maps.build_svg(spec, [{"type": "Polygon", "coordinates": [[[4, 51], [5, 51], [5, 53], [4, 51]]]}])
    assert svg.startswith("<svg") and "http://www.w3.org/2000/svg" in svg and "<image" not in svg and "href" not in svg
    assert svg.count("<circle") == 2 and "stroke-dasharray" in svg and "Schematic map" in svg
    assert maps.build_svg(maps.MapSpec()).startswith("<svg")  # no data still draws a world frame


@needs_pdf
def test_pdf_renderer_refuses_external_resources(tmp_path: Any) -> None:
    pdf = render.html_to_pdf('<h1>Hello</h1><img src="http://127.0.0.1:9/never.png"><link rel="stylesheet" href="file:///etc/hosts">')
    assert pdf is not None and pdf.startswith(b"%PDF")
    png = render.svg_to_png('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"><rect width="100" height="50" fill="red"/></svg>')
    assert png is None or png.startswith(b"\x89PNG")


def test_report_helpers_handle_empty_tenants(client: Any, world: World, conn: psycopg.Connection[Any]) -> None:
    conn.execute("DELETE FROM exposures")
    conn.execute("DELETE FROM alerts")
    conn.execute("DELETE FROM assets WHERE tenant_id = %s", (world.tenants["A"],))
    conn.commit()
    login(client, world, "manager")
    assert client.post(f"{API}/reports/portfolio").status_code == 201
    assert client.post(f"{API}/reports/incident/{world.events['A']}").status_code == 201
    _ = reports


# -- corrections --------------------------------------------------------------------------------------------------------------
def test_corrections_flow_to_the_platform_queue_and_feed_candidates(client: Any, world: World, conn: psycopg.Connection[Any], tmp_path: Any) -> None:
    from meridian.config import get_settings

    login(client, world, "viewer")
    consenting = client.post(
        f"{API}/corrections",
        json={"event_id": world.events["A"], "kind": "wrong_location", "suggested_place": "Springfield, Missouri", "note": "Wrong state", "consent_for_gold": True},
    ).json()["id"]
    private = client.post(
        f"{API}/corrections", json={"event_id": world.events["A"], "kind": "wrong_type", "suggested_type": "natural_hazard"}
    ).json()["id"]
    assert [c["status"] for c in client.get(f"{API}/corrections").json()["items"]] == ["open", "open"]
    assert client.patch(f"{API}/corrections/{consenting}", json={"status": "accepted"}).status_code == 403  # tenants cannot review
    login(client, world, "b_manager")
    assert client.get(f"{API}/corrections").json()["items"] == []
    login(client, world, "platform")
    queue = client.get(f"{API}/corrections", params={"status": "open"}).json()["items"]
    assert len(queue) == 2 and queue[0]["event_title"] == "Fire near A"
    accepted = client.patch(f"{API}/corrections/{consenting}", json={"status": "accepted", "note": "Confirmed"})
    assert accepted.json()["status"] == "accepted" and accepted.json()["candidate"] is True
    assert client.patch(f"{API}/corrections/{consenting}", json={"status": "rejected"}).status_code == 409  # reviewed once
    no_consent = client.patch(f"{API}/corrections/{private}", json={"status": "accepted"})
    assert no_consent.json()["candidate"] is False
    lines = get_settings().data_dir.joinpath("annotation", "correction_candidates.jsonl").read_text().splitlines()
    assert len(lines) == 1  # only the correction whose submitter gave consent
    record = json.loads(lines[0])
    assert record["correction_id"] == consenting and record["suggested_place"] == "Springfield, Missouri"
    assert record["source_urls"] == ["https://news.example/A"] and "tenant_id" not in record and "note" not in record
    updates = conn.execute("SELECT count(*) FROM event_updates WHERE event_id = %s AND update_type = 'correction_accepted'", (world.events["A"],)).fetchone()
    assert updates == (2,)  # both are recorded on the event; only one is a training candidate
    stamp = conn.execute("SELECT gold_exported_at IS NOT NULL FROM correction_requests WHERE id = %s", (consenting,)).fetchone()
    assert stamp == (True,)
    assert client.patch(f"{API}/corrections/00000000-0000-0000-0000-000000000000", json={"status": "accepted"}).status_code == 404
