"""Phase 6 exit test: upload assets, create a watch zone, ingest a fixture incident, the alert appears on the stream, a webhook is
delivered, the analyst acknowledges, and the report exports."""

from __future__ import annotations

import datetime as dt
import io
import json
from typing import Any

import httpx
import psycopg
import pytest

from meridian import notify
from meridian.api.security import ssrf
from meridian.api.services import mailer as mailer_module
from meridian.api.services import render, webhooks
from meridian.events import service
from meridian.events.config import load_events_config
from tests.api_support import World, login

API = "/api/v1"
PUBLIC = [(2, 1, 6, "", ("93.184.216.34", 443))]


def clear_seeded_tenant_data(conn: psycopg.Connection[Any]) -> None:
    """Start from empty tenants (users and webhooks stay) with no events, so that only this test's data is involved."""
    for table in ("alert_events", "alerts", "exposures", "watch_zones", "alert_rules", "asset_group_members", "assets", "event_sources", "events"):
        conn.execute(f"DELETE FROM {table}")  # noqa: S608
    conn.commit()


def test_upload_zone_incident_alert_webhook_acknowledge_report(
    client: Any, world: World, conn: psycopg.Connection[Any], tmp_path: Any, monkeypatch: pytest.MonkeyPatch, mailer: mailer_module.CaptureMailer
) -> None:
    clear_seeded_tenant_data(conn)
    monkeypatch.setattr(mailer_module, "get_mailer", lambda: mailer)  # the pipeline sends alert mail through this
    monkeypatch.setattr(ssrf, "_lookup", lambda host, port, **kw: PUBLIC)

    # 1. A manager uploads assets: one by coordinates, one by city, and reviews the staged rows before committing.
    login(client, world, "manager")
    sheet = "name,lat,lon,city,country,criticality,external_id\nHarbour crane,39.90,-89.50,,,5,H-1\nSpringfield depot,,,Springfield,US,4,H-2\n"
    staged = client.post(f"{API}/uploads/stage", files={"file": ("sites.csv", io.BytesIO(sheet.encode()), "text/csv")})
    assert staged.status_code == 201 and staged.json()["summary"]["ready"] == 2
    committed = client.post(f"{API}/uploads/{staged.json()['id']}/commit", json={})
    assert committed.json()["created"] == 2 and committed.json()["status"] == "processed"

    # 2. An analyst draws a watch zone as a circle around the area.
    login(client, world, "analyst")
    zone = client.post(f"{API}/zones", json={"name": "Springfield area", "circle": {"center": [-89.64, 39.80], "radius_km": 60}, "rules": {"min_level": "low"}})
    assert zone.status_code == 201

    # 3. An administrator registers a signed webhook.
    login(client, world, "admin")
    hook = client.post(f"{API}/admin/webhooks", json={"name": "Ops", "url": "https://hooks.example.org/in", "min_level": "low"})
    assert hook.status_code == 201
    secret = hook.json()["signing_secret"]
    conn.execute("UPDATE webhooks SET enabled = false WHERE id <> %s", (hook.json()["id"],))  # the seeded hooks are not part of this test
    conn.commit()

    # 4. A fixture incident is ingested through the real pipeline while the stream is open.
    now = dt.datetime.now(dt.UTC)
    ms = int(now.timestamp() * 1000)
    quake = {
        "feature": {
            "id": "us-e2e-1",
            "properties": {"mag": 6.4, "time": ms, "updated": ms, "type": "earthquake", "title": "M 6.4 - near Springfield (fixture)"},
            "geometry": {"type": "Point", "coordinates": [-89.64, 39.80, 10.0]},
        }
    }
    path = tmp_path / "quake.jsonl"
    path.write_text(json.dumps(quake) + "\n", encoding="utf-8")
    stream_a = notify.Subscription(f"alerts:{world.tenants['A']}")
    stream_b = notify.Subscription(f"alerts:{world.tenants['B']}")
    try:
        run = service.ingest_usgs(conn, load_events_config(), [path], now=now)
        messages = [stream_a.get(timeout=3) for _ in range(2)]
        leaked = stream_b.get(timeout=0.3)
    finally:
        stream_a.close()
        stream_b.close()

    # 5. The alerts appear on tenant A's stream, with names and distances but no coordinates, and never on B's.
    assert run.alerts.created == 3  # two assets and the zone
    assert leaked is None and all(m is not None for m in messages)
    payloads = [json.loads(m) for m in messages if m]
    assert {p["asset"]["name"] for p in payloads} <= {"Harbour crane", "Springfield depot", None}
    assert all("latitude" not in json.dumps(p) and p["disclaimer"] for p in payloads)
    login(client, world, "analyst")
    alerts = client.get(f"{API}/alerts").json()["items"]
    assert len(alerts) == 3 and {a["status"] for a in alerts} == {"new"}
    event_id = alerts[0]["event"]["id"]

    # 6. Alert email went to the analysts, managers, and administrators of tenant A only, without coordinates.
    assert sorted({to for to, _, _ in mailer.sent}) == ["admin@example.org", "analyst@example.org", "manager@example.org"]
    assert all("39.8" not in body and "-89.6" not in body for _, _, body in mailer.sent)

    # 7. The webhook is delivered with a valid signature.
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    counts = webhooks.run_due(conn, client=httpx.Client(transport=httpx.MockTransport(handler)), resolver=lambda *a, **k: PUBLIC)
    assert counts["delivered"] == 3 and len(seen) == 3
    assert all(webhooks.verify_signature(secret, r.headers["x-meridian-signature"], r.content) for r in seen)
    body = json.loads(seen[0].content)
    assert body["event"]["id"] == event_id and "latitude" not in seen[0].content.decode()

    # 8. The analyst acknowledges the asset alert; the change is recorded and announced.
    asset_alert = next(a for a in alerts if a["asset"])
    listener = notify.Subscription(f"alerts:{world.tenants['A']}")
    try:
        done = client.patch(f"{API}/alerts/{asset_alert['id']}", json={"status": "acknowledged"})
        update = listener.get(timeout=2)
    finally:
        listener.close()
    assert done.json()["status"] == "acknowledged" and update is not None and json.loads(update)["alert"]["status"] == "acknowledged"
    history = client.get(f"{API}/alerts/{asset_alert['id']}").json()["history"]
    assert [h["kind"] for h in history if h["kind"] != "notification"] == ["created", "status_change"]

    # 9. The incident detail and the report export (PDF when the renderer is installed).
    detail = client.get(f"{API}/events/{event_id}").json()
    assert {e["asset_name"] for e in detail["exposures"]} == {"Harbour crane", "Springfield depot"} and detail["location"]["uncertainty_circle"]
    login(client, world, "manager")
    report = client.post(f"{API}/reports/incident/{event_id}")
    assert report.status_code == 201, report.text
    page = client.get(f"{API}/reports/{report.json()['id']}", params={"format": "html"}).text
    assert "Harbour crane" in page and "Springfield depot" in page and "not official warnings" in page
    if render.html_to_pdf("<p>x</p>"):
        assert "pdf" in report.json()["formats"]
        pdf = client.get(f"{API}/reports/{report.json()['id']}", params={"format": "pdf"})
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    # 10. Tenant B sees none of it.
    login(client, world, "b_manager")
    assert client.get(f"{API}/alerts").json()["items"] == []
    assert client.get(f"{API}/zones").json()["items"] == [] and client.get(f"{API}/assets").json()["items"] == []
    assert client.get(f"{API}/reports/{report.json()['id']}").status_code == 404
