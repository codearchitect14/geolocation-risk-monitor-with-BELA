"""Cross-tenant access attempts through the API, including spatial queries and map data endpoints."""

from __future__ import annotations

from typing import Any

from tests.api_support import World, key_client, login

A_BBOX = "-90,39,-89,41"  # covers tenant A's assets and event


def ids_in(payload: dict[str, Any], key: str = "id") -> set[str]:
    return {i[key] for i in payload["items"]}


def test_tenant_b_cannot_read_tenant_a_objects(client: Any, world: World) -> None:
    login(client, world, "b_admin")
    w = world
    for path in (
        f"/assets/{w.assets['A_near']}", f"/assets/{w.assets['A_near']}/exposure", f"/assets/{w.assets['A_near']}/events",
        f"/zones/{w.zones['A']}", f"/alerts/{w.alerts['A']}", f"/uploads/{w.uploads['A']}", f"/briefings/{w.briefings['A']}",
        f"/reports/{w.reports['A']}", f"/admin/webhooks/{w.hooks['A']}/deliveries",
    ):  # fmt: skip
        assert client.get("/api/v1" + path).status_code == 404, path


def test_lists_never_contain_the_other_tenant(client: Any, world: World) -> None:
    login(client, world, "b_admin")
    w = world
    assert ids_in(client.get("/api/v1/assets").json()) == {w.assets["B_near"], w.assets["B_far"]}
    assert ids_in(client.get("/api/v1/zones").json()) == {w.zones["B"]}
    assert ids_in(client.get("/api/v1/rules").json()) == {w.rules["B"]}
    assert ids_in(client.get("/api/v1/alerts").json()) == {w.alerts["B"]}
    assert ids_in(client.get("/api/v1/briefings").json()) == {w.briefings["B"]}
    assert ids_in(client.get("/api/v1/admin/api-keys").json()) == {w.key_ids["B"]}
    assert ids_in(client.get("/api/v1/admin/webhooks").json()) == {w.hooks["B"]}
    users = {u["email"] for u in client.get("/api/v1/admin/users").json()["items"]}
    assert users == {"b_manager@example.org", "b_admin@example.org"}
    audit = client.get("/api/v1/admin/audit").json()
    assert all(item["detail"].get("tenant") != "A" for item in audit["items"])


def test_spatial_queries_do_not_leak_assets(client: Any, world: World) -> None:
    login(client, world, "b_manager")
    assert client.get("/api/v1/assets", params={"bbox": A_BBOX}).json()["items"] == []
    geo = client.get("/api/v1/assets", params={"bbox": A_BBOX, "format": "geojson"}).json()
    assert geo["features"] == []
    everything = client.get("/api/v1/assets", params={"format": "geojson"}).json()
    assert {f["properties"]["name"] for f in everything["features"]} == {"B near", "B far"}
    zones = client.get("/api/v1/zones", params={"format": "geojson"}).json()
    assert {f["properties"]["name"] for f in zones["features"]} == {"Zone B"}


def test_global_events_are_shared_but_exposures_are_not(client: Any, world: World) -> None:
    login(client, world, "b_manager")
    both = ids_in(client.get("/api/v1/events").json())
    assert {world.events["A"], world.events["B"]} <= both  # events are public data
    near = ids_in(client.get("/api/v1/events", params={"near_my_assets": "true"}).json())
    assert near == {world.events["B"]}
    detail = client.get(f"/api/v1/events/{world.events['A']}").json()
    assert detail["exposures"] == []  # tenant A's asset exposure is invisible to B
    own = client.get(f"/api/v1/events/{world.events['B']}").json()
    assert [e["asset_name"] for e in own["exposures"]] == ["B near"]
    geo = client.get("/api/v1/events", params={"format": "geojson", "bbox": A_BBOX}).json()
    assert {f["id"] for f in geo["features"]} == {world.events["A"]}  # public geometry, no tenant fields
    assert "exposures" not in geo["features"][0]["properties"]


def test_cross_tenant_writes_fail_as_not_found(client: Any, world: World) -> None:
    login(client, world, "b_admin")
    w = world
    assert client.patch(f"/api/v1/assets/{w.assets['A_near']}", json={"criticality": 1}).status_code == 404
    assert client.delete(f"/api/v1/assets/{w.assets['A_far']}").status_code == 404
    assert client.patch(f"/api/v1/alerts/{w.alerts['A']}", json={"status": "acknowledged"}).status_code == 404
    assert client.post(f"/api/v1/alerts/{w.alerts['A']}/comments", json={"text": "x"}).status_code == 404
    assert client.patch(f"/api/v1/zones/{w.zones['A']}", json={"name": "x"}).status_code == 404
    assert client.delete(f"/api/v1/zones/{w.zones['A']}").status_code == 404
    assert client.patch(f"/api/v1/rules/{w.rules['A']}", json={"enabled": False}).status_code == 404
    assert client.delete(f"/api/v1/admin/api-keys/{w.key_ids['A']}").status_code == 404
    assert client.delete(f"/api/v1/admin/webhooks/{w.hooks['A']}").status_code == 404
    assert client.post(f"/api/v1/admin/webhooks/{w.hooks['A']}/rotate-secret").status_code == 404
    assert client.patch(f"/api/v1/admin/users/{w.users['viewer']}", json={"role": "tenant_admin"}).status_code == 404
    login(client, world, "admin")
    assert client.get(f"/api/v1/assets/{w.assets['A_near']}").status_code == 200  # nothing changed


def test_references_to_other_tenants_are_rejected(client: Any, world: World) -> None:
    login(client, world, "b_admin")
    rule = client.post("/api/v1/rules", json={"name": "x", "asset_group_ids": [world.groups["A"]]})
    assert rule.status_code == 422
    login(client, world, "b_manager")
    alert_id = world.alerts["B"]
    assignee = client.patch(f"/api/v1/alerts/{alert_id}", json={"assignee_id": world.users["analyst"]})
    assert assignee.status_code == 422
    group = client.post("/api/v1/asset-groups", json={"name": "g", "asset_ids": [world.assets["A_near"]]}).json()
    assert group["asset_count"] == 0  # tenant A's asset is not visible, so it cannot be grouped


def test_tenant_admin_cannot_create_users_in_another_tenant(client: Any, world: World) -> None:
    login(client, world, "b_admin")
    response = client.post(
        "/api/v1/admin/users",
        json={"email": "x@example.org", "display_name": "X", "role": "viewer", "tenant_id": world.tenants["A"]},
    )
    assert response.status_code == 403


def test_api_key_is_scoped_to_its_tenant(client: Any, world: World) -> None:
    key_client(client, world.keys["B"])
    assert ids_in(client.get("/api/v1/alerts").json()) == {world.alerts["B"]}
    assert client.get(f"/api/v1/alerts/{world.alerts['A']}").status_code == 404


def test_platform_admin_acting_inside_a_tenant_is_limited_to_it(client: Any, world: World) -> None:
    login(client, world, "platform")
    all_assets = ids_in(client.get("/api/v1/assets", params={"limit": 200}).json())
    assert len(all_assets) == 4  # platform administrators read across tenants
    scoped = client.get("/api/v1/assets", headers={"X-Tenant-Id": world.tenants["B"]}).json()
    assert ids_in(scoped) == {world.assets["B_near"], world.assets["B_far"]}
    created = client.post(
        "/api/v1/assets",
        headers={"X-Tenant-Id": world.tenants["B"]},
        json={"name": "Platform made", "geometry": {"type": "Point", "coordinates": [2, 2]}},
    )
    assert created.status_code == 201
    login(client, world, "b_manager")
    assert "Platform made" in {a["name"] for a in client.get("/api/v1/assets").json()["items"]}
    login(client, world, "platform")
    assert (
        client.post(
            "/api/v1/assets", json={"name": "No tenant", "geometry": {"type": "Point", "coordinates": [2, 2]}}
        ).status_code
        == 422
    )


def test_finance_role_cannot_read_tenant_data_but_can_read_revenue(client: Any, world: World) -> None:
    login(client, world, "finance")
    assert client.get("/api/v1/assets").status_code == 403
    summary = client.get("/api/v1/platform/revenue/summary")
    assert summary.status_code == 200 and summary.json()["demo_data"] is True and summary.json()["active_tenants"] == 2
