"""Phase 6: guided upload, asset management, and watch zone shapes."""

from __future__ import annotations

import io
import json
from typing import Any

import psycopg
import pytest

from tests.api_support import World, login

API = "/api/v1"


@pytest.fixture
def places(conn: psycopg.Connection[Any], world: World) -> None:
    """Reference places for city resolution: an ambiguous pair, a clear case, a country, and a region with a boundary."""
    rows = [
        (2, "Springfield", "city", "US", "Missouri", 169176, 37.21, -93.29),
        (3, "Rotterdam", "city", "NL", "South Holland", 656050, 51.92, 4.48),
        (4, "Rotterdam", "town", "US", "New York", 1200, 42.80, -74.00),
        (5, "Netherlands", "country", "NL", None, 17_000_000, 52.1, 5.3),
        (6, "Zuid-Holland", "admin1", "NL", "South Holland", 3_700_000, 52.0, 4.5),
    ]
    for pid, name, kind, cc, admin, pop, lat, lon in rows:
        polygon = (
            "ST_GeomFromText('POLYGON((3.9 51.7, 5.0 51.7, 5.0 52.4, 3.9 52.4, 3.9 51.7))', 4326)"
            if kind == "admin1"
            else f"ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326)"
        )
        conn.execute(
            f"""INSERT INTO places (id, geonames_id, name, name_normalized, type, country_code, admin1_name, population, lat, lon, centroid, geom,
                                    source, uncertainty_km, location_level, has_polygon)
                OVERRIDING SYSTEM VALUE VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326),
                                                {polygon}, 'geonames', 15, 'city', %s)""",  # noqa: S608
            (pid, 9000 + pid, name, name.lower(), kind, cc, admin, pop, lat, lon, kind == "admin1"),
        )
    conn.commit()


def stage(client: Any, text: str, name: str = "sites.csv", mapping: dict[str, str] | None = None) -> Any:
    data = {"mapping": json.dumps(mapping)} if mapping else {}
    return client.post(
        f"{API}/uploads/stage", files={"file": (name, io.BytesIO(text.encode()), "text/csv")}, data=data
    )


def test_templates_download(client: Any, world: World) -> None:
    login(client, world, "viewer")
    csv_file = client.get(f"{API}/uploads/template")
    assert csv_file.status_code == 200 and csv_file.text.startswith("name,lat,lon,city,country")
    assert "attachment" in csv_file.headers["content-disposition"]
    geo = client.get(f"{API}/uploads/template", params={"format": "geojson"}).json()
    assert geo["type"] == "FeatureCollection" and len(geo["features"]) == 2
    assert client.get(f"{API}/uploads/template", params={"format": "xls"}).status_code == 422


def test_stage_resolves_cities_and_flags_what_needs_review(client: Any, world: World, places: None) -> None:
    login(client, world, "manager")
    text = (
        "name,lat,lon,city,country,criticality,external_id\n"
        "Plant A,51.9,4.4,,,5,P-1\n"  # coordinates
        "Depot Rotterdam,,,Rotterdam,NL,3,P-2\n"  # one clear match in the country
        "Depot Springfield,,,Springfield,,2,P-3\n"  # no country: confirm
        "Depot Nowhere,,,Qwertyville,NL,3,P-4\n"  # unknown place
        "Depot Odd,,,Rotterdam,Atlantis,3,P-5\n"  # unknown country
        "Plant B,95,4.4,,,3,P-6\n"  # bad latitude
        "Plant A again,51.9,4.4,,,3,P-1\n"  # duplicate external id
        ",,,,,,\n"
    )
    r = stage(client, text)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "staged" and body["rows_total"] == 7
    by_name = {row["name"]: row for row in body["rows"]}
    assert by_name["Plant A"]["status"] == "ready" and by_name["Plant A"]["geometry"]["coordinates"] == [4.4, 51.9]
    rotterdam = by_name["Depot Rotterdam"]
    assert rotterdam["status"] == "ready" and rotterdam["place"]["name"] == "Rotterdam" and rotterdam["confidence"] >= 0.62
    springfield = by_name["Depot Springfield"]
    assert springfield["status"] == "review" and len(springfield["candidates"]) == 2
    assert "country" in springfield["message"]
    assert by_name["Depot Nowhere"]["status"] == "error" and "no place" in by_name["Depot Nowhere"]["message"]
    assert by_name["Depot Odd"]["status"] == "error" and "country" in by_name["Depot Odd"]["message"]
    assert by_name["Plant B"]["status"] == "error"
    assert by_name["Plant A again"]["status"] == "duplicate"
    assert body["summary"] == {"ready": 2, "review": 1, "duplicate": 1, "error": 3}
    # The map preview carries every row that has a position, with its status.
    statuses = {f["properties"]["name"]: f["properties"]["status"] for f in body["preview"]["features"]}
    assert statuses["Depot Springfield"] == "review" and "Plant B" not in statuses
    # Nothing is created until commit.
    assert client.get(f"{API}/assets", params={"q": "Depot"}).json()["items"] == []
    review = client.get(f"{API}/uploads/{body['id']}/rows", params={"status": "review"}).json()
    assert review["total"] == 1 and review["items"][0]["name"] == "Depot Springfield"


def test_commit_uses_reviewer_choices_and_reports_every_row(client: Any, world: World, places: None) -> None:
    login(client, world, "manager")
    text = (
        "name,lat,lon,city,country,external_id\n"
        "Plant A,51.9,4.4,,,P-1\n"
        "Depot Rotterdam,,,Rotterdam,NL,P-2\n"
        "Depot Springfield,,,Springfield,,P-3\n"
        "Depot Unreviewed,,,Springfield,,P-4\n"
        "Bad,,,Qwertyville,NL,P-5\n"
    )
    staged = stage(client, text).json()
    upload_id = staged["id"]
    # A pick must be one of the stored candidates.
    wrong = client.post(f"{API}/uploads/{upload_id}/commit", json={"choices": [{"row": 4, "place_id": 999}]})
    assert wrong.status_code == 422 and wrong.json()["type"].endswith("invalid-choice")
    not_review = client.post(f"{API}/uploads/{upload_id}/commit", json={"choices": [{"row": 2, "place_id": 3}]})
    assert not_review.status_code == 422
    done = client.post(f"{API}/uploads/{upload_id}/commit", json={"choices": [{"row": 4, "place_id": 2}]})
    assert done.status_code == 200, done.text
    result = done.json()
    assert result["created"] == 3 and result["skipped"] == 1 and result["rejected"] == 1 and result["status"] == "partial"
    assets = {a["name"]: a for a in client.get(f"{API}/assets").json()["items"] if a["name"].startswith(("Plant", "Depot"))}
    assert set(assets) == {"Plant A", "Depot Rotterdam", "Depot Springfield"}
    assert assets["Plant A"]["location_source"] == "provided" and assets["Plant A"]["place_id"] is None
    assert assets["Depot Rotterdam"]["location_source"] == "place" and assets["Depot Rotterdam"]["place_id"] == 3
    assert assets["Depot Rotterdam"]["location_uncertainty_km"] == 15
    chosen = assets["Depot Springfield"]["geometry"]["coordinates"]
    assert chosen == [-93.29, 37.21]  # Missouri, as the reviewer picked
    # A second commit is refused, and the upload record shows the outcome.
    again = client.post(f"{API}/uploads/{upload_id}/commit", json={})
    assert again.status_code == 409
    record = client.get(f"{API}/uploads/{upload_id}").json()
    assert record["status"] == "partial" and record["rows_accepted"] == 3 and record["rows_rejected"] == 1
    export = client.get(f"{API}/uploads/{upload_id}/result")
    assert export.status_code == 200 and "text/csv" in export.headers["content-type"]
    lines = export.text.strip().splitlines()
    assert lines[0].startswith("row,name,status,outcome") and len(lines) == 6
    assert any("not_reviewed" in line for line in lines) and any("rejected" in line for line in lines)


def test_column_mapping_is_detected_or_given(client: Any, world: World, places: None) -> None:
    login(client, world, "manager")
    odd = "Site,Town,Nation,Priority\nHarbour,Rotterdam,Netherlands,4\n"
    body = stage(client, odd).json()
    assert body["mapping"] == {"name": "Site", "city": "Town", "country": "Nation", "criticality": "Priority"}
    assert body["rows"][0]["status"] == "ready" and body["rows"][0]["criticality"] == 4  # country given by name
    assert body["headers"] == ["Site", "Town", "Nation", "Priority"]
    # Columns that cannot be detected need a mapping from the user.
    hidden = "A,B,C\nHarbour,51.9,4.4\n"
    missing = stage(client, hidden)
    assert missing.status_code == 422 and missing.json()["headers"] == ["A", "B", "C"]
    given = stage(client, hidden, mapping={"name": "A", "lat": "B", "lon": "C"})
    assert given.status_code == 201 and given.json()["rows"][0]["status"] == "ready"
    for bad in ({"name": "Z"}, {"colour": "A"}, ["name"]):
        assert stage(client, hidden, mapping=bad).status_code == 422  # type: ignore[arg-type]
    assert (
        client.post(
            f"{API}/uploads/stage",
            files={"file": ("a.csv", io.BytesIO(hidden.encode()), "text/csv")},
            data={"mapping": "{not json"},
        ).status_code
        == 422
    )


def test_geojson_staging_and_limits(client: Any, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    login(client, world, "manager")
    doc = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [4.4, 51.9]}, "properties": {"name": "Gate", "external_id": "G1"}},
            {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[4.1, 51.9], [4.5, 52.0]]}, "properties": {"name": "Route"}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [400, 51.9]}, "properties": {"name": "Broken"}},
        ],
    }
    r = client.post(
        f"{API}/uploads/stage", files={"file": ("a.geojson", io.BytesIO(json.dumps(doc).encode()), "application/geo+json")}
    )
    assert r.status_code == 201 and r.json()["summary"] == {"ready": 2, "review": 0, "duplicate": 0, "error": 1}
    committed = client.post(f"{API}/uploads/{r.json()['id']}/commit", json={}).json()
    assert committed["created"] == 2
    types = {a["name"]: a["type"] for a in client.get(f"{API}/assets").json()["items"]}
    assert types["Gate"] == "site" and types["Route"] == "route"
    monkeypatch.setenv("MS_MAX_UPLOAD_ROWS", "2")
    big = "name,lat,lon\nA,1,1\nB,1,2\nC,1,3\n"
    assert stage(client, big).status_code == 413


def test_staged_uploads_are_private_and_need_permission(client: Any, world: World, places: None) -> None:
    login(client, world, "viewer")
    assert stage(client, "name,lat,lon\nA,1,1\n").status_code == 403
    login(client, world, "manager")
    upload = stage(client, "name,lat,lon\nA,1,1\n").json()["id"]
    login(client, world, "viewer")
    assert client.post(f"{API}/uploads/{upload}/commit", json={}).status_code == 403
    assert client.get(f"{API}/uploads/{upload}/rows").status_code == 200  # reviewing is read only
    login(client, world, "b_manager")
    for method, path in (("GET", f"/uploads/{upload}/rows"), ("GET", f"/uploads/{upload}/result"), ("POST", f"/uploads/{upload}/cancel")):
        assert client.request(method, API + path).status_code == 404
    assert client.post(f"{API}/uploads/{upload}/commit", json={}).status_code == 404
    login(client, world, "manager")
    assert client.post(f"{API}/uploads/{upload}/cancel").json()["status"] == "cancelled"
    assert client.post(f"{API}/uploads/{upload}/cancel").status_code == 409
    assert client.post(f"{API}/uploads/{upload}/commit", json={}).status_code == 409


def test_result_export_is_formula_safe(client: Any, world: World, places: None) -> None:
    login(client, world, "manager")
    staged = stage(client, 'name,lat,lon\n"=HYPERLINK(""http://x"")",1,1\n').json()
    client.post(f"{API}/uploads/{staged['id']}/commit", json={})
    text = client.get(f"{API}/uploads/{staged['id']}/result").text
    assert "'=HYPERLINK" in text and "\n2,=HYPERLINK" not in text


# -- asset management ---------------------------------------------------------------------------------------------------------
def test_bulk_edit_tags_criticality_groups_and_archive(client: Any, world: World) -> None:
    login(client, world, "manager")
    near, far = world.assets["A_near"], world.assets["A_far"]
    r = client.post(
        f"{API}/assets/bulk",
        json={"asset_ids": [near, far], "criticality": 5, "add_tags": ["priority", "port"], "add_to_group": world.groups["A"]},
    )
    assert r.status_code == 200 and r.json() == {"updated": 2}
    one = client.get(f"{API}/assets/{near}").json()
    assert one["criticality"] == 5 and sorted(one["tags"]) == ["port", "priority"]
    assert {a["id"] for a in client.get(f"{API}/assets", params={"group_id": world.groups["A"]}).json()["items"]} == {near, far}
    assert len(client.get(f"{API}/assets", params={"tag": "port"}).json()["items"]) == 2
    client.post(f"{API}/assets/bulk", json={"asset_ids": [far], "remove_tags": ["port"], "remove_from_group": world.groups["A"]})
    assert [a["id"] for a in client.get(f"{API}/assets", params={"tag": "port"}).json()["items"]] == [near]
    archived = client.post(f"{API}/assets/bulk", json={"asset_ids": [far], "status": "archived"})
    assert archived.status_code == 200
    assert far not in {a["id"] for a in client.get(f"{API}/assets").json()["items"]}
    assert far in {a["id"] for a in client.get(f"{API}/assets", params={"status": "archived"}).json()["items"]}
    # Errors: nothing to change, unknown ids, another tenant's asset, bad group.
    assert client.post(f"{API}/assets/bulk", json={"asset_ids": [near]}).status_code == 422
    assert client.post(f"{API}/assets/bulk", json={"asset_ids": [world.assets["B_near"]], "criticality": 1}).status_code == 404
    assert client.post(f"{API}/assets/bulk", json={"asset_ids": [near], "add_to_group": world.groups["B"]}).status_code == 422
    assert client.get(f"{API}/assets/{world.assets['B_near']}").status_code == 404
    login(client, world, "analyst")
    assert client.post(f"{API}/assets/bulk", json={"asset_ids": [near], "criticality": 1}).status_code == 403


def test_group_management_and_maintenance_windows(client: Any, world: World) -> None:
    login(client, world, "manager")
    group = world.groups["A"]
    near = world.assets["A_near"]
    patched = client.patch(f"{API}/asset-groups/{group}", json={"name": "Ports", "add_asset_ids": [near, world.assets["B_near"]]})
    assert patched.status_code == 200 and patched.json() == {"id": group, "name": "Ports", "asset_count": 1}  # B's asset is invisible
    other = client.post(f"{API}/asset-groups", json={"name": "Depots"}).json()["id"]
    assert client.patch(f"{API}/asset-groups/{other}", json={"name": "Ports"}).status_code == 409
    assert client.patch(f"{API}/asset-groups/{world.groups['B']}", json={"name": "x"}).status_code == 404
    assert client.delete(f"{API}/asset-groups/{world.groups['B']}").status_code == 404
    assert client.delete(f"{API}/asset-groups/{group}").status_code == 204
    assert client.get(f"{API}/assets/{near}").status_code == 200  # assets survive a deleted group
    window = {"start": "2026-01-01T00:00:00Z", "end": "2026-01-02T00:00:00Z", "reason": "planned outage"}
    assert client.patch(f"{API}/assets/{near}", json={"maintenance_windows": [window]}).status_code == 200
    for bad in (
        {"start": "2026-01-02T00:00:00Z", "end": "2026-01-01T00:00:00Z"},
        {"start": "tomorrow", "end": "next week"},
        {"start": "2026-01-01T00:00:00Z"},
    ):
        assert client.patch(f"{API}/assets/{near}", json={"maintenance_windows": [bad]}).status_code == 422
    live = {"start": "2020-01-01T00:00:00Z", "end": "2099-01-01T00:00:00Z"}
    client.patch(f"{API}/assets/{near}", json={"maintenance_windows": [live]})
    now = client.get(f"{API}/assets", params={"in_maintenance": "true"}).json()["items"]
    assert [a["id"] for a in now] == [near]
    assert near not in {a["id"] for a in client.get(f"{API}/assets", params={"in_maintenance": "false"}).json()["items"]}
    assert client.get(f"{API}/assets", params={"min_criticality": 5}).json()["items"] == []


# -- zones --------------------------------------------------------------------------------------------------------------------
def test_zone_from_a_circle(client: Any, world: World, conn: psycopg.Connection[Any]) -> None:
    login(client, world, "analyst")
    r = client.post(
        f"{API}/zones",
        json={"name": "Port approaches", "circle": {"center": [4.4, 51.95], "radius_km": 25}, "rules": {"min_level": "high"}},
    )
    assert r.status_code == 201, r.text
    zone = r.json()
    assert zone["rules"]["origin"] == {"kind": "circle", "center": [4.4, 51.95], "radius_km": 25}
    assert zone["geometry"]["type"] == "Polygon" and zone["rules"]["min_level"] == "high"
    area = conn.execute(
        "SELECT ST_Area(geom::geography) / 1e6 FROM watch_zones WHERE id = %s", (zone["id"],)
    ).fetchone()
    assert area is not None and 1850 < area[0] < 2000  # pi * 25^2 = 1963 km2
    resized = client.patch(f"{API}/zones/{zone['id']}", json={"circle": {"center": [4.4, 51.95], "radius_km": 10}})
    assert resized.json()["rules"]["origin"]["radius_km"] == 10 and resized.json()["rules"]["min_level"] == "high"  # rules are kept
    for bad in (
        {"radius_km": 0, "center": [4, 51]},
        {"radius_km": 5000, "center": [4, 51]},
        {"radius_km": 5, "center": [400, 51]},
        {"radius_km": 5, "center": [4]},
    ):
        assert client.post(f"{API}/zones", json={"name": "bad", "circle": bad}).status_code == 422


def test_zone_from_a_region_and_exactly_one_shape(client: Any, world: World, places: None) -> None:
    login(client, world, "analyst")
    r = client.post(f"{API}/zones", json={"name": "South Holland", "region_place_id": 6, "rules": {"quiet_hours": {"start": "22:00", "end": "06:00"}}})
    assert r.status_code == 201, r.text
    assert r.json()["rules"]["origin"] == {"kind": "region", "place_id": 6, "name": "Zuid-Holland"}
    assert r.json()["rules"]["quiet_hours"] == {"start": "22:00", "end": "06:00"}
    assert client.post(f"{API}/zones", json={"name": "x", "region_place_id": 3}).status_code == 422  # a city has no boundary
    assert client.post(f"{API}/zones", json={"name": "x", "region_place_id": 999}).status_code == 404
    assert client.post(f"{API}/zones", json={"name": "x"}).status_code == 422
    both = {"name": "x", "region_place_id": 6, "circle": {"center": [4, 51], "radius_km": 5}}
    assert client.post(f"{API}/zones", json=both).status_code == 422
    polygon = {"type": "Polygon", "coordinates": [[[4, 51], [5, 51], [5, 52], [4, 51]]]}
    assert client.post(f"{API}/zones", json={"name": "poly", "geometry": polygon}).json()["rules"]["origin"] == {"kind": "polygon"}
    point = {"type": "Point", "coordinates": [4, 51]}
    assert client.post(f"{API}/zones", json={"name": "pt", "geometry": point}).status_code == 422
    assert client.post(f"{API}/zones", json={"name": "q", "region_place_id": 6, "rules": {"quiet_hours": {"start": "25:00", "end": "06:00"}}}).status_code == 422


def test_rule_escalation_is_validated_and_stored(client: Any, world: World) -> None:
    login(client, world, "manager")
    made = client.post(f"{API}/rules", json={"name": "Critical", "min_level": "critical", "escalation": {"after_minutes": 30}})
    assert made.status_code == 201 and made.json()["escalation"] == {"after_minutes": 30}
    rule_id = made.json()["id"]
    assert client.post(f"{API}/rules", json={"name": "x", "escalation": {"after_minutes": 1}}).status_code == 422
    assert client.patch(f"{API}/rules/{rule_id}", json={"escalation": {"after_minutes": 60}}).json()["escalation"] == {"after_minutes": 60}
    assert client.patch(f"{API}/rules/{rule_id}", json={"escalation": None}).json()["escalation"] == {}
