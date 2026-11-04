"""Functional behavior of the endpoint groups."""

from __future__ import annotations

import json
from typing import Any

import psycopg
import pytest

from meridian.api.routers.events import LocateBody, get_locator
from tests.api_support import World, login

API = "/api/v1"
SQUARE = {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}


# -- protocol ---------------------------------------------------------------------------------------------------------
def test_errors_are_problem_documents_without_internals(client: Any, world: World) -> None:
    login(client, world, "viewer")
    missing = client.get(f"{API}/assets/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404 and missing.headers["content-type"].startswith("application/problem+json")
    body = missing.json()
    assert (
        set(body) >= {"type", "title", "status", "detail", "instance", "request_id"}
        and body["request_id"] == missing.headers["x-request-id"]
    )
    assert client.get(f"{API}/assets/not-a-uuid").status_code == 422
    assert client.get(f"{API}/nothing-here").status_code == 404
    assert client.delete(f"{API}/auth/me").status_code == 405
    invalid = client.post(f"{API}/locate", json={"text": 5})
    assert invalid.status_code == 422 and "errors" in invalid.json()
    assert "input" not in json.dumps(invalid.json()) and "Traceback" not in invalid.text


def test_security_headers_on_every_response(client: Any, world: World) -> None:
    for path in ("/health", "/assets", "/nothing"):
        r = client.get(API + path)
        h = r.headers
        assert (
            h["x-content-type-options"] == "nosniff"
            and h["x-frame-options"] == "DENY"
            and h["referrer-policy"] == "no-referrer"
        )
        assert (
            "default-src 'none'" in h["content-security-policy"]
            and "frame-ancestors 'none'" in h["content-security-policy"]
        )
        assert h["cache-control"] == "no-store" and "permissions-policy" in h and "access-control-allow-origin" not in h
    assert client.get("/api/docs").headers["content-security-policy"].startswith("default-src 'self'")


def test_hsts_is_sent_in_production(client: Any, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MS_ENV", "production")
    assert "max-age=" in client.get(f"{API}/health").headers["strict-transport-security"]


def test_cors_is_not_enabled(client: Any, world: World) -> None:
    r = client.options(
        f"{API}/assets", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"}
    )
    assert "access-control-allow-origin" not in r.headers


def test_oversized_bodies_are_rejected(client: Any, world: World) -> None:
    login(client, world, "manager")
    big = client.post(f"{API}/locate", content=b"x" * 2_000_000, headers={"Content-Type": "application/json"})
    assert big.status_code == 413 and big.headers["content-type"].startswith("application/problem+json")


def test_openapi_has_examples_and_the_disclaimer(client: Any, world: World) -> None:
    spec = client.get("/api/openapi.json").json()
    assert "not official warnings" in spec["info"]["description"]
    assert len(spec["paths"]) >= 60
    text = json.dumps(spec)
    assert "Rotterdam terminal (illustrative)" in text and "Known maintenance window" in text
    assert all(op.get("summary") for item in spec["paths"].values() for op in item.values())


def test_pagination_walks_every_item_once(client: Any, world: World) -> None:
    login(client, world, "manager")
    for i in range(5):
        assert (
            client.post(
                f"{API}/assets", json={"name": f"P{i}", "geometry": {"type": "Point", "coordinates": [i, i]}}
            ).status_code
            == 201
        )
    seen, cursor, pages = [], None, 0
    while True:
        page = client.get(f"{API}/assets", params={"limit": 2, **({"cursor": cursor} if cursor else {})}).json()
        seen += [a["name"] for a in page["items"]]
        pages += 1
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(seen) == 7 and len(set(seen)) == 7 and pages == 4
    assert client.get(f"{API}/assets", params={"cursor": "###"}).status_code == 400
    assert client.get(f"{API}/assets", params={"limit": 1000}).status_code == 422


# -- assets and uploads --------------------------------------------------------------------------------------------------
def test_asset_crud_and_validation(client: Any, world: World) -> None:
    login(client, world, "manager")
    created = client.post(
        f"{API}/assets",
        json={
            "name": "Rotterdam terminal (illustrative)",
            "geometry": {"type": "Point", "coordinates": [4.4, 51.95]},
            "criticality": 5,
            "country_code": "nl",
            "tags": ["port"],
            "external_id": "T-1",
        },
    )
    assert created.status_code == 201
    asset = created.json()
    assert asset["country_code"] == "NL" and asset["geometry"]["coordinates"] == [4.4, 51.95]
    assert (
        client.post(
            f"{API}/assets",
            json={"name": "dup", "geometry": {"type": "Point", "coordinates": [1, 1]}, "external_id": "T-1"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"{API}/assets", json={"name": "bad", "geometry": {"type": "Point", "coordinates": [200, 10]}}
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"{API}/assets", json={"name": "bad", "geometry": {"type": "Point", "coordinates": [10, 95]}}
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"{API}/assets", json={"name": "bad", "type": "route", "geometry": {"type": "Point", "coordinates": [1, 1]}}
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"{API}/assets", json={"name": "bad", "geometry": {"type": "GeometryCollection", "geometries": []}}
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"{API}/assets",
            json={"name": "bad", "criticality": 9, "geometry": {"type": "Point", "coordinates": [1, 1]}},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"{API}/assets",
            json={
                "name": "bad",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]},
                "type": "region",
            },
        ).status_code
        == 422
    )  # self-intersecting
    window = [{"start": "2026-11-02T00:00:00Z", "end": "2026-11-02T06:00:00Z", "reason": "service"}]
    patched = client.patch(
        f"{API}/assets/{asset['id']}", json={"criticality": 2, "maintenance_windows": window, "tags": ["a", "b"]}
    ).json()
    assert patched["criticality"] == 2 and patched["maintenance_windows"] == window
    assert (
        client.patch(f"{API}/assets/{asset['id']}", json={"maintenance_windows": [{"start": "x"}]}).status_code == 422
    )
    route = client.post(
        f"{API}/assets",
        json={"name": "Route", "type": "route", "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}},
    )
    assert route.status_code == 201 and route.json()["type"] == "route"
    assert client.get(f"{API}/assets", params={"type": "route"}).json()["items"][0]["name"] == "Route"
    assert client.get(f"{API}/assets", params={"q": "rotter"}).json()["items"][0]["id"] == asset["id"]
    assert client.delete(f"{API}/assets/{asset['id']}").status_code == 204
    assert client.get(f"{API}/assets/{asset['id']}").status_code == 404


def test_asset_exposure_and_events_show_every_component(client: Any, world: World) -> None:
    login(client, world, "viewer")
    exposure = client.get(f"{API}/assets/{world.assets['A_near']}/exposure").json()
    assert (
        exposure["exposures"][0]["components"] == {"type_weight": 1.0, "proximity": 1.0}
        and exposure["exposures"][0]["level"] == "high"
    )
    events = client.get(f"{API}/assets/{world.assets['A_near']}/events").json()["items"]
    assert events[0]["event_id"] == world.events["A"]
    assert client.get(f"{API}/assets/{world.assets['A_far']}/exposure").json()["exposures"] == []


def upload(client: Any, name: str, data: bytes, ctype: str, key: str | None = None) -> Any:
    return client.post(
        f"{API}/uploads", files={"file": (name, data, ctype)}, headers={"Idempotency-Key": key} if key else {}
    )


def test_csv_upload_reports_row_errors(client: Any, world: World) -> None:
    login(client, world, "manager")
    csv_text = "name,lat,lon,criticality,country_code,external_id,tags\nPlant 1,10.5,20.5,4,de,P1,a|b\nBad lat,abc,1,3,,,\nOut of range,95,10,3,,,\n,1,1,3,,,\nCrit,1,1,9,,,\n"
    r = upload(client, "sites.csv", csv_text.encode(), "text/csv")
    assert r.status_code == 201
    body = r.json()
    assert (body["rows_total"], body["rows_accepted"], body["rows_rejected"], body["status"]) == (5, 1, 4, "partial")
    assert {e["row"] for e in body["errors"]} == {3, 4, 5, 6}
    assert client.get(f"{API}/uploads/{body['id']}").json()["rows_rejected"] == 4
    assert client.get(f"{API}/assets", params={"q": "Plant 1"}).json()["items"][0]["tags"] == ["a", "b"]


def test_geojson_upload_accepts_routes_and_regions(client: Any, world: World) -> None:
    login(client, world, "manager")
    doc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": "Port", "criticality": 5}, "geometry": {"type": "Point", "coordinates": [4.4, 51.9]}},
        {"type": "Feature", "properties": {"name": "Lane"}, "geometry": {"type": "LineString", "coordinates": [[0, 0], [5, 5]]}},
        {"type": "Feature", "properties": {"name": "Region"}, "geometry": SQUARE},
        {"type": "Feature", "properties": {"name": "Bad"}, "geometry": {"type": "Point", "coordinates": [500, 0]}},
    ]}  # fmt: skip
    r = upload(client, "sites.geojson", json.dumps(doc).encode(), "application/geo+json")
    assert r.status_code == 201 and r.json()["rows_accepted"] == 3 and r.json()["errors"][0]["row"] == 4
    types = {a["name"]: a["type"] for a in client.get(f"{API}/assets", params={"limit": 200}).json()["items"]}
    assert types["Port"] == "site" and types["Lane"] == "route" and types["Region"] == "region"


def test_upload_limits_and_content_checks(client: Any, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    login(client, world, "manager")
    assert upload(client, "x.csv", b"name,lat,lon\nA,1,1\nB,2,2\nC,3,3\n", "text/csv").status_code == 201
    monkeypatch.setenv("MS_MAX_UPLOAD_ROWS", "2")
    assert upload(client, "x.csv", b"name,lat,lon\nA,1,1\nB,2,2\nC,3,3\n", "text/csv").status_code == 413
    monkeypatch.setenv("MS_MAX_UPLOAD_BYTES", "50")
    assert upload(client, "x.csv", b"name,lat,lon\n" + b"A,1,1\n" * 30, "text/csv").status_code == 413
    monkeypatch.delenv("MS_MAX_UPLOAD_BYTES")
    assert upload(client, "x.csv", b"\x00\x01\x02binary", "text/csv").status_code == 415
    assert upload(client, "x.exe", b"name,lat,lon\n", "application/octet-stream").status_code == 415
    assert upload(client, "x.csv", b'{"type": "FeatureCollection"}', "text/csv").status_code == 415
    assert upload(client, "x.geojson", b"name,lat,lon\nA,1,1\n", "application/json").status_code == 415
    assert upload(client, "x.csv", b"id,place\n1,Paris\n", "text/csv").status_code == 422
    assert upload(client, "x.csv", b"", "text/csv").status_code == 422
    assert upload(client, "x.geojson", b"{not json", "application/json").status_code == 422
    monkeypatch.setenv("MS_MAX_VERTICES", "10")
    ring = [[i / 10, (i % 2) / 10] for i in range(25)]
    doc = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"name": "Huge"}, "geometry": {"type": "LineString", "coordinates": ring}}
        ],
    }
    assert upload(client, "big.geojson", json.dumps(doc).encode(), "application/json").status_code == 413


def test_upload_idempotency(client: Any, world: World) -> None:
    login(client, world, "manager")
    data = b"name,lat,lon\nIdem,1,1\n"
    first = upload(client, "a.csv", data, "text/csv", key="upload-1")
    replay = upload(client, "a.csv", data, "text/csv", key="upload-1")
    assert (
        first.status_code == replay.status_code == 201
        and replay.headers["idempotent-replay"] == "true"
        and replay.json() == first.json()
    )
    assert len(client.get(f"{API}/assets", params={"q": "Idem"}).json()["items"]) == 1
    assert upload(client, "a.csv", b"name,lat,lon\nOther,1,1\n", "text/csv", key="upload-1").status_code == 422
    assert (
        client.post(
            f"{API}/uploads", files={"file": ("a.csv", data, "text/csv")}, headers={"Idempotency-Key": "bad key!"}
        ).status_code
        == 422
    )


def test_reupload_with_external_id_updates_instead_of_duplicating(client: Any, world: World) -> None:
    login(client, world, "manager")
    upload(client, "a.csv", b"name,lat,lon,external_id\nFirst,1,1,X1\n", "text/csv")
    upload(client, "a.csv", b"name,lat,lon,external_id\nRenamed,2,2,X1\n", "text/csv")
    items = client.get(f"{API}/assets", params={"q": "Renamed"}).json()["items"]
    assert len(items) == 1 and items[0]["geometry"]["coordinates"] == [2.0, 2.0]
    assert client.get(f"{API}/assets", params={"q": "First"}).json()["items"] == []


def test_exports_neutralize_spreadsheet_formulas(client: Any, world: World) -> None:
    login(client, world, "manager")
    for name in ('=HYPERLINK("http://evil")', "+1+1", "-2+3", "@SUM(A1)"):
        client.post(f"{API}/assets", json={"name": name, "geometry": {"type": "Point", "coordinates": [1, 1]}})
    export = client.get(f"{API}/assets-export")
    assert export.headers["content-type"].startswith("text/csv")
    rows = export.text.splitlines()
    assert not any(line.split(",")[0].lstrip('"')[:1] in "=+-@" for line in rows[1:] if line)
    assert "'=HYPERLINK" in export.text and "'+1+1" in export.text


# -- zones, rules, groups -------------------------------------------------------------------------------------------------
def test_zones(client: Any, world: World) -> None:
    login(client, world, "analyst")
    created = client.post(
        f"{API}/zones",
        json={
            "name": "Port approach",
            "geometry": SQUARE,
            "rules": {"min_severity": 3, "event_types": ["natural_hazard"], "min_level": "low"},
        },
    )
    assert created.status_code == 201
    zone_id = created.json()["id"]
    assert (
        client.post(
            f"{API}/zones", json={"name": "Pt", "geometry": {"type": "Point", "coordinates": [1, 1]}}
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"{API}/zones", json={"name": "Bad", "geometry": SQUARE, "rules": {"event_types": ["nonsense"]}}
        ).status_code
        == 422
    )
    assert (
        client.post(f"{API}/zones", json={"name": "Bad", "geometry": SQUARE, "rules": {"min_severity": 7}}).status_code
        == 422
    )
    assert (
        client.patch(f"{API}/zones/{zone_id}", json={"name": "Renamed", "rules": {"min_severity": 2}}).json()["rules"][
            "min_severity"
        ]
        == 2
    )
    assert client.get(f"{API}/zones/{zone_id}").json()["name"] == "Renamed"
    assert (
        client.get(f"{API}/zones", params={"format": "geojson"}).json()["features"][0]["geometry"]["type"] == "Polygon"
    )
    assert client.delete(f"{API}/zones/{zone_id}").status_code == 204
    assert client.delete(f"{API}/zones/{zone_id}").status_code == 404


def test_rules(client: Any, world: World) -> None:
    login(client, world, "manager")
    group = client.post(f"{API}/asset-groups", json={"name": "Ports", "asset_ids": [world.assets["A_near"]]}).json()
    assert group["asset_count"] == 1
    body = {
        "name": "Night rule",
        "event_types": ["industrial_accident"],
        "min_severity": 2,
        "min_level": "high",
        "asset_group_ids": [group["id"]],
        "quiet_hours": {"start": "22:00", "end": "06:00"},
    }
    created = client.post(f"{API}/rules", json=body)
    assert created.status_code == 201 and created.json()["quiet_hours"] == {"start": "22:00", "end": "06:00"}
    rule_id = created.json()["id"]
    assert (
        client.post(f"{API}/rules", json={**body, "quiet_hours": {"start": "25:00", "end": "06:00"}}).status_code == 422
    )
    assert client.post(f"{API}/rules", json={**body, "min_level": "extreme"}).status_code == 422
    assert client.post(f"{API}/rules", json={**body, "event_types": ["x"]}).status_code == 422
    assert (
        client.patch(f"{API}/rules/{rule_id}", json={"enabled": False, "min_level": "critical"}).json()["enabled"]
        is False
    )
    assert client.patch(f"{API}/rules/{rule_id}", json={"quiet_hours": None}).json()["quiet_hours"] is None
    assert client.get(f"{API}/rules").json()["default_when_none"] == {"min_level": "medium"}


# -- events, places, locate, sources ----------------------------------------------------------------------------------------
def test_events_filters_and_detail(client: Any, world: World) -> None:
    login(client, world, "viewer")
    listing = client.get(f"{API}/events").json()
    assert "not official warnings" in listing["disclaimer"] and len(listing["items"]) == 2
    assert [e["id"] for e in client.get(f"{API}/events", params={"bbox": "-90,39,-89,41"}).json()["items"]] == [
        world.events["A"]
    ]
    assert client.get(f"{API}/events", params={"min_severity": 4}).json()["items"] == []
    assert (
        len(
            client.get(f"{API}/events", params={"type": "industrial_accident", "confirmation": "unconfirmed"}).json()[
                "items"
            ]
        )
        == 2
    )
    assert client.get(f"{API}/events", params={"type": "nonsense"}).status_code == 422
    assert client.get(f"{API}/events", params={"bbox": "1,2,3"}).status_code == 422
    assert client.get(f"{API}/events", params={"bbox": "-500,0,10,10"}).status_code == 422
    assert client.get(f"{API}/events", params={"status": "weird"}).status_code == 422
    detail = client.get(f"{API}/events/{world.events['A']}").json()
    assert detail["confirmation_text"] == "reported, not yet confirmed"
    assert detail["sources"][0]["url"] == "https://news.example/A" and "official warnings" in detail["disclaimer"]
    geo = client.get(f"{API}/events", params={"format": "geojson"}).json()
    assert geo["type"] == "FeatureCollection" and len(geo["features"]) == 2


def test_places(client: Any, world: World) -> None:
    login(client, world, "viewer")
    hits = client.get(f"{API}/places/search", params={"q": "Springfield", "country": "us"}).json()["items"]
    assert hits and hits[0]["name"] == "Springfield" and hits[0]["lat"] == 39.8
    assert client.get(f"{API}/places/1").json()["qid"] == "Q1"
    assert client.get(f"{API}/places/999999").status_code == 404
    assert client.get(f"{API}/places/search", params={"q": ""}).status_code == 422


def test_locate_uses_the_provider_and_is_limited(client: Any, app: Any, world: World) -> None:
    calls: list[LocateBody] = []

    def fake(body: LocateBody) -> dict[str, Any]:
        calls.append(body)
        return {
            "mentions": [],
            "event_location": {"name": "Springfield", "lat": 39.8, "lon": -89.64, "uncertainty_km": 25},
        }

    app.dependency_overrides[get_locator] = lambda: fake
    login(client, world, "viewer")
    ok = client.post(
        f"{API}/locate", json={"title": "Fire in Springfield, Illinois", "text": "A fire broke out.", "lang": "en"}
    )
    assert (
        ok.status_code == 200
        and ok.json()["event_location"]["name"] == "Springfield"
        and "official warnings" in ok.json()["disclaimer"]
    )
    assert calls[0].text == "A fire broke out."
    assert client.post(f"{API}/locate", json={"text": "x" * 20001}).status_code == 422
    assert client.post(f"{API}/locate", json={"text": "ok", "lang": "<script>"}).status_code == 422
    codes = [client.post(f"{API}/locate", json={"text": "ok"}).status_code for _ in range(32)]
    assert codes.count(429) >= 2


def test_locate_reports_unavailable_linker(client: Any, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEL_URL", "http://127.0.0.1:9")
    login(client, world, "viewer")
    assert client.post(f"{API}/locate", json={"text": "Fire in Springfield"}).status_code == 503


def test_sources_report_freshness(client: Any, world: World) -> None:
    login(client, world, "viewer")
    items = {i["kind"]: i for i in client.get(f"{API}/sources").json()["items"]}
    assert items["news"]["freshness"] == "current" and items["news"]["records_total"] == 2
    assert items["usgs"]["freshness"] == "no data" and "Public domain" in items["usgs"]["license_note"]


# -- alerts and corrections ----------------------------------------------------------------------------------------------------
def test_alert_workflow(client: Any, world: World, conn: psycopg.Connection[Any]) -> None:
    login(client, world, "analyst")
    alert_id = world.alerts["A"]
    listing = client.get(f"{API}/alerts", params={"status": "new", "level": "high"}).json()
    assert [a["id"] for a in listing["items"]] == [alert_id] and "official warnings" in listing["disclaimer"]
    assert (
        listing["items"][0]["asset"]["distance_km"] == 1.2
        and listing["items"][0]["event"]["confirmation_text"] == "reported, not yet confirmed"
    )
    assert (
        client.patch(f"{API}/alerts/{alert_id}", json={"status": "dismissed"}).status_code == 422
    )  # a reason is required
    assert client.patch(f"{API}/alerts/{alert_id}", json={"status": "acknowledged"}).json()["status"] == "acknowledged"
    assert client.post(f"{API}/alerts/{alert_id}/comments", json={"text": "Calling the site"}).status_code == 201
    assert client.post(f"{API}/alerts/{alert_id}/comments", json={"text": ""}).status_code == 422
    assert client.post(f"{API}/alerts/{alert_id}/comments", json={"text": "x" * 2001}).status_code == 422
    assigned = client.patch(
        f"{API}/alerts/{alert_id}", json={"assignee_id": world.users["manager"], "status": "escalated"}
    ).json()
    assert assigned["assignee_id"] == world.users["manager"] and assigned["status"] == "escalated"
    dismissed = client.patch(
        f"{API}/alerts/{alert_id}", json={"status": "dismissed", "dismissal_reason": "Known maintenance window"}
    ).json()
    assert dismissed["dismissal_reason"] == "Known maintenance window"
    history = client.get(f"{API}/alerts/{alert_id}").json()["history"]
    assert [h["kind"] for h in history] == ["status_change", "comment", "status_change", "assignment", "status_change"]
    assert history[1]["detail"] == {"text": "Calling the site"}
    assert client.get(f"{API}/alerts", params={"status": "new"}).json()["items"] == []
    actions = [
        r[0]
        for r in conn.execute(
            "SELECT action FROM audit_log WHERE tenant_id = %s AND action LIKE 'alert.%%' ORDER BY id",
            (world.tenants["A"],),
        ).fetchall()
    ]
    assert actions.count("alert.update") == 3 and "alert.comment" in actions


def test_corrections_and_review(client: Any, app: Any, world: World) -> None:
    login(client, world, "viewer")
    made = client.post(
        f"{API}/corrections",
        json={
            "event_id": world.events["A"],
            "kind": "wrong_location",
            "note": "This is the other Springfield",
            "suggested_place": "Springfield, Missouri",
            "consent_for_gold": True,
        },
    )
    assert made.status_code == 201 and made.json()["status"] == "open"
    assert (
        client.post(
            f"{API}/corrections", json={"event_id": "00000000-0000-0000-0000-000000000000", "kind": "duplicate"}
        ).status_code
        == 404
    )
    assert client.post(f"{API}/corrections", json={"event_id": world.events["A"], "kind": "other"}).status_code == 422
    assert client.get(f"{API}/corrections").json()["items"][0]["details"]["suggested_place"] == "Springfield, Missouri"
    assert client.patch(f"{API}/corrections/{made.json()['id']}", json={"status": "accepted"}).status_code == 403
    login(client, world, "b_manager")
    assert client.get(f"{API}/corrections").json()["items"] == []  # another tenant's corrections are not visible
    login(client, world, "platform")
    queue = client.get(f"{API}/corrections", params={"status": "open"}).json()["items"]
    assert len(queue) == 1
    reviewed = client.patch(f"{API}/corrections/{made.json()['id']}", json={"status": "accepted", "note": "Confirmed"})
    assert reviewed.status_code == 200 and reviewed.json()["status"] == "accepted"
    login(client, world, "viewer")
    assert client.get(f"{API}/corrections").json()["items"][0]["status"] == "accepted"


# -- briefings, reports, analytics ----------------------------------------------------------------------------------------------
def test_briefing_is_built_from_stored_alerts(client: Any, world: World) -> None:
    login(client, world, "manager")
    made = client.post(f"{API}/briefings", json={"kind": "daily"})
    assert made.status_code == 201
    briefing = made.json()
    assert briefing["model_version"] == "briefing_template_v1" and briefing["evidence"]["alerts_by_level"]["high"] == 1
    assert (
        "A near" in briefing["narrative"]
        and "not official warnings" in briefing["narrative"]
        and "https://news.example/A" in briefing["narrative"]
    )
    assert "Fire near B" not in briefing["narrative"] and "B near" not in briefing["narrative"]
    assert client.get(f"{API}/briefings/{briefing['id']}").json()["narrative"] == briefing["narrative"]
    assert client.post(f"{API}/briefings", json={"kind": "custom"}).status_code == 422
    assert (
        client.post(
            f"{API}/briefings",
            json={"kind": "custom", "period_start": "2026-01-01T00:00:00Z", "period_end": "2026-06-01T00:00:00Z"},
        ).status_code
        == 422
    )


def test_reports_escape_content_and_neutralize_formulas(client: Any, world: World) -> None:
    login(client, world, "manager")
    client.post(
        f"{API}/assets",
        json={"name": "<script>alert(1)</script>", "geometry": {"type": "Point", "coordinates": [1, 1]}},
    )
    client.post(f"{API}/assets", json={"name": "=1+1", "geometry": {"type": "Point", "coordinates": [2, 2]}})
    portfolio = client.post(f"{API}/reports/portfolio").json()
    html = client.get(f"{API}/reports/{portfolio['id']}", params={"format": "html"})
    assert "&lt;script&gt;" in html.text and "<script>" not in html.text and "not official warnings" in html.text
    assert "sandbox" in html.headers["content-security-policy"]
    csv_text = client.get(f"{API}/reports/{portfolio['id']}", params={"format": "csv"}).text
    assert "'=1+1" in csv_text
    incident = client.post(f"{API}/reports/incident/{world.events['A']}").json()
    page = client.get(f"{API}/reports/{incident['id']}", params={"format": "html"}).text
    assert "Fire near A" in page and "A near" in page and "Fire near B" not in page and "B near" not in page
    assert client.get(f"{API}/reports/{incident['id']}").json()["status"] == "ready"
    assert client.post(f"{API}/reports/incident/00000000-0000-0000-0000-000000000000").status_code == 404


def test_analytics(client: Any, world: World) -> None:
    login(client, world, "analyst")
    client.patch(f"{API}/alerts/{world.alerts['A']}", json={"status": "acknowledged"})
    login(client, world, "manager")
    ops = client.get(f"{API}/analytics/operations").json()
    assert ops["alerts_by_level"] == {"critical": 0, "high": 1, "medium": 0, "low": 0} and ops["most_alerted_assets"] == [{"asset": "A near", "alerts": 1}]
    assert ops["median_minutes_to_acknowledge"] is not None
    quality = client.get(f"{API}/analytics/quality").json()
    assert quality["events"] == 2 and quality["confirmed_share"] == 0.0
    assert client.get(f"{API}/analytics/usage").json()["demo_data"] is True


def test_revenue_views_are_labeled_demo_data(client: Any, world: World) -> None:
    login(client, world, "finance")
    summary = client.get(f"{API}/platform/revenue/summary").json()
    assert (
        summary["mrr"]["value"] == 1800.0
        and summary["arr"]["value"] == 21600.0
        and summary["customers"]["value"] == 2
        and summary["demo_data"] is True
    )
    series = client.get(f"{API}/platform/revenue/mrr").json()
    assert series["items"][-1]["mrr"] == 1800.0 and series["demo_data"] is True
    assert [t["mrr"] for t in client.get(f"{API}/platform/revenue/tenants").json()["items"]] == [900.0, 900.0]


# -- administration -----------------------------------------------------------------------------------------------------------------
def test_risk_config_and_audit(client: Any, world: World) -> None:
    login(client, world, "admin")
    assert client.get(f"{API}/admin/risk-config").json() == {
        "min_level": "medium",
        "include_coordinates": False,
        "retention_days": 365,
        "model_training_opt_in": False,
        "daily_briefing": False,
        "weekly_briefing": False,
        "briefing_email": False,
    }
    put = client.put(
        f"{API}/admin/risk-config",
        json={"min_level": "high", "include_coordinates": True, "retention_days": 90, "model_training_opt_in": False},
    )
    assert put.status_code == 200 and client.get(f"{API}/admin/risk-config").json()["retention_days"] == 90
    assert client.put(f"{API}/admin/risk-config", json={"retention_days": 5}).status_code == 422
    assert client.put(f"{API}/admin/risk-config", json={"min_level": "extreme"}).status_code == 422
    for days in (100, 120):
        client.put(f"{API}/admin/risk-config", json={"retention_days": days})
    trail = client.get(f"{API}/admin/audit", params={"action": "risk_config.update"}).json()["items"]
    assert trail and trail[0]["actor_id"] == world.users["admin"]
    assert client.get(f"{API}/admin/audit/verify").json()["intact"] is True
    page = client.get(f"{API}/admin/audit", params={"limit": 2}).json()
    assert len(page["items"]) == 2 and page["next_cursor"]


def test_audit_entries_never_hold_secrets_or_coordinates(
    client: Any, world: World, conn: psycopg.Connection[Any]
) -> None:
    login(client, world, "manager")
    client.post(
        f"{API}/assets", json={"name": "Secret site", "geometry": {"type": "Point", "coordinates": [12.34567, 45.6789]}}
    )
    rows = " ".join(
        r[0] for r in conn.execute("SELECT detail::text || coalesce(object_id, '') FROM audit_log").fetchall()
    )
    for needle in ("12.34567", "45.6789", "Secret site", "correct horse"):
        assert needle not in rows
    from meridian.api.security import audit

    cleaned = audit.sanitize(
        {
            "password": "x",
            "token": "t",
            "lat": 1,
            "nested": {"api_key": "k", "ok": "fine"},
            "geometry": {},
            "note": "y" * 500,
        }
    )
    assert cleaned["password"] == cleaned["token"] == cleaned["lat"] == cleaned["geometry"] == "[redacted]"
    assert cleaned["nested"] == {"api_key": "[redacted]", "ok": "fine"} and len(cleaned["note"]) == 300


def test_demo_request_form(client: Any, world: World, conn: psycopg.Connection[Any]) -> None:
    body = {"name": "Visitor", "email": "visitor@example.org", "company": "Example Co", "message": "Please contact me.", "consent": True}
    assert client.post(f"{API}/contact/demo-request", json={**body, "consent": False}).status_code == 422
    assert client.post(f"{API}/contact/demo-request", json=body).status_code == 202
    assert conn.execute("SELECT count(*) FROM demo_requests").fetchone() == (1,)
    assert (
        client.post(f"{API}/contact/demo-request", json={**body, "website": "http://spam.example"}).status_code == 202
    )
    assert conn.execute("SELECT count(*) FROM demo_requests").fetchone() == (
        1,
    )  # the honeypot was filled: nothing stored
    assert client.post(f"{API}/contact/demo-request", json={**body, "email": "not-an-email"}).status_code == 422
    codes = [client.post(f"{API}/contact/demo-request", json=body).status_code for _ in range(5)]
    assert 429 in codes


def test_billing_views_are_labeled_demo_data(client: Any, world: World) -> None:
    login(client, world, "admin")
    plan = client.get(f"{API}/billing/plan").json()
    assert plan["demo_data"] is True and plan["plan"]["name"] == "Standard" and plan["plan"]["assets_in_use"] == 2
    invoices = client.get(f"{API}/billing/invoices").json()
    assert len(invoices["items"]) == 1 and invoices["demo_data"] is True


def test_platform_tenant_management(client: Any, world: World, conn: psycopg.Connection[Any]) -> None:
    login(client, world, "platform")
    made = client.post(
        f"{API}/platform/tenants",
        json={
            "name": "Northwind Logistics (demo)",
            "admin_email": "owner@northwind.example",
            "admin_name": "Owner",
            "industry": "logistics",
            "country_code": "nl",
        },
    )
    assert made.status_code == 201
    assert (
        client.post(
            f"{API}/platform/tenants",
            json={"name": "Again", "admin_email": "owner@northwind.example", "admin_name": "Owner"},
        ).status_code
        == 409
    )
    listing = {t["name"]: t for t in client.get(f"{API}/platform/tenants").json()["items"]}
    assert (
        listing["Northwind Logistics (demo)"]["is_demo"] is True and listing["Northwind Logistics (demo)"]["users"] == 1
    )
    assert conn.execute("SELECT role, status FROM users WHERE email = 'owner@northwind.example'").fetchone() == (
        "tenant_admin",
        "invited",
    )
    assert client.patch(f"{API}/platform/tenants/{made.json()['id']}", json={"status": "closed"}).status_code == 422
    assert (
        client.patch(
            f"{API}/platform/tenants/00000000-0000-0000-0000-000000000000", json={"status": "suspended"}
        ).status_code
        == 404
    )
