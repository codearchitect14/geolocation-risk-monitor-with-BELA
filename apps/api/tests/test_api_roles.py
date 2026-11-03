"""Every role against every endpoint group. The expected table comes from the specification, not from the code."""

from __future__ import annotations

from typing import Any

import pytest

from tests.api_support import World, login

ALL = ["viewer", "analyst", "manager", "admin", "finance", "platform"]
VIEW = {"viewer", "analyst", "manager", "admin", "platform"}
ACT = {"analyst", "manager", "admin", "platform"}
ASSETS = {"manager", "admin", "platform"}
RULES = {"manager", "admin", "platform"}
ADMIN = {"admin", "platform"}
REVENUE = {"finance", "platform"}
PLATFORM = {"platform"}


def endpoints(w: World) -> list[tuple[str, str, str, Any, set[str]]]:
    a, ev = w.assets, w.events["A"]
    csv = ("assets.csv", b"name,lat,lon\nRoles test,10,10\n", "text/csv")
    return [
        # view
        ("view", "GET", "/assets", None, VIEW),
        ("view", "GET", f"/assets/{a['A_near']}", None, VIEW),
        ("view", "GET", f"/assets/{a['A_near']}/exposure", None, VIEW),
        ("view", "GET", f"/assets/{a['A_near']}/events", None, VIEW),
        ("view", "GET", "/asset-groups", None, VIEW),
        ("view", "GET", "/zones", None, VIEW),
        ("view", "GET", "/rules", None, VIEW),
        ("view", "GET", "/events", None, VIEW),
        ("view", "GET", f"/events/{ev}", None, VIEW),
        ("view", "GET", "/places/search?q=springfield", None, VIEW),
        ("view", "GET", "/places/1", None, VIEW),
        ("view", "GET", "/alerts", None, VIEW),
        ("view", "GET", f"/alerts/{w.alerts['A']}", None, VIEW),
        ("view", "GET", "/sources", None, VIEW),
        ("view", "GET", "/briefings", None, VIEW),
        ("view", "GET", f"/briefings/{w.briefings['A']}", None, VIEW),
        ("view", "GET", f"/uploads/{w.uploads['A']}", None, VIEW),
        ("view", "GET", "/corrections", None, VIEW),
        ("view", "GET", "/uploads/template", None, VIEW),
        ("view", "GET", f"/uploads/{w.uploads['A']}/rows", None, VIEW),
        ("view", "GET", f"/uploads/{w.uploads['A']}/result", None, VIEW),
        ("view", "GET", "/alerts?mine=true", None, VIEW),
        ("view", "GET", f"/briefings/{w.briefings['A']}?format=html", None, VIEW),
        ("view", "POST", "/corrections", {"event_id": ev, "kind": "wrong_type"}, VIEW),
        # alerts.act
        ("act", "PATCH", f"/alerts/{w.alerts['A']}", {"status": "acknowledged"}, ACT),
        ("act", "POST", f"/alerts/{w.alerts['A']}/comments", {"text": "checking"}, ACT),
        (
            "act",
            "POST",
            "/zones",
            {"name": "z", "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}},
            ACT,
        ),
        ("act", "PATCH", f"/zones/{w.zones['A']}", {"name": "renamed"}, ACT),
        # assets.write
        ("assets", "POST", "/assets", {"name": "n", "geometry": {"type": "Point", "coordinates": [1, 1]}}, ASSETS),
        ("assets", "PATCH", f"/assets/{a['A_far']}", {"criticality": 2}, ASSETS),
        ("assets", "POST", "/asset-groups", {"name": "g"}, ASSETS),
        ("assets", "POST", "/uploads", csv, ASSETS),
        ("assets", "POST", "/uploads/stage", csv, ASSETS),
        ("assets", "POST", f"/uploads/{w.uploads['A']}/commit", {}, ASSETS),
        ("assets", "POST", f"/uploads/{w.uploads['A']}/cancel", None, ASSETS),
        ("assets", "POST", "/assets/bulk", {"asset_ids": [a["A_far"]], "criticality": 2}, ASSETS),
        ("assets", "PATCH", f"/asset-groups/{w.groups['A']}", {"name": "Renamed"}, ASSETS),
        # rules.manage, analytics, reports
        ("rules", "POST", "/rules", {"name": "r"}, RULES),
        ("rules", "PATCH", f"/rules/{w.rules['A']}", {"enabled": True}, RULES),
        ("rules", "POST", "/briefings", {"kind": "daily"}, RULES),
        ("rules", "POST", "/reports/portfolio", None, RULES),
        ("rules", "POST", f"/reports/incident/{ev}", None, RULES),
        ("rules", "GET", f"/reports/{w.reports['A']}", None, RULES),
        ("rules", "GET", "/reports", None, RULES),
        ("rules", "POST", f"/briefings/{w.briefings['A']}/email", {"to": ["viewer@example.org"]}, RULES),
        ("rules", "GET", "/analytics/operations", None, RULES),
        ("rules", "GET", "/analytics/quality", None, RULES),
        ("rules", "GET", "/analytics/usage", None, RULES),
        # admin.manage
        ("admin", "GET", "/admin/users", None, ADMIN),
        (
            "admin",
            "POST",
            "/admin/users",
            {"email": "new.person@example.org", "display_name": "New", "role": "viewer"},
            ADMIN,
        ),
        ("admin", "GET", "/admin/api-keys", None, ADMIN),
        ("admin", "POST", "/admin/api-keys", {"name": "k", "scopes": ["read"]}, ADMIN),
        ("admin", "GET", "/admin/webhooks", None, ADMIN),
        ("admin", "POST", "/admin/webhooks", {"name": "h", "url": "http://insecure.example.org"}, ADMIN),
        ("admin", "GET", "/admin/risk-config", None, ADMIN),
        ("admin", "PUT", "/admin/risk-config", {"min_level": "medium"}, ADMIN),
        ("admin", "GET", "/billing/plan", None, ADMIN),
        ("admin", "GET", "/billing/invoices", None, ADMIN),
        # audit
        ("audit", "GET", "/admin/audit", None, ADMIN),
        ("audit", "GET", "/admin/audit/verify", None, ADMIN),
        # revenue and platform
        ("revenue", "GET", "/platform/revenue/summary", None, REVENUE),
        ("revenue", "GET", "/platform/revenue/mrr", None, REVENUE),
        ("revenue", "GET", "/platform/revenue/tenants", None, REVENUE),
        ("platform", "GET", "/platform/tenants", None, PLATFORM),
        (
            "platform",
            "POST",
            "/platform/tenants",
            {"name": "New Co", "admin_email": "nc@example.org", "admin_name": "NC"},
            PLATFORM,
        ),
        ("platform", "PATCH", "/corrections/00000000-0000-0000-0000-000000000000", {"status": "accepted"}, PLATFORM),
        # open to every signed in role
        ("open", "GET", "/auth/me", None, set(ALL)),
        ("open", "GET", "/auth/sessions", None, set(ALL)),
        ("open", "PATCH", "/auth/me/notifications", {"email": True}, set(ALL)),
        # deleting a group goes last so that the rows above can use it
        ("assets", "DELETE", f"/asset-groups/{w.groups['A']}", None, ASSETS),
    ]


def call(c: Any, method: str, path: str, body: Any) -> int:
    url = "/api/v1" + path
    if isinstance(body, tuple):
        return int(c.post(url, files={"file": body}).status_code)
    return int(c.request(method, url, json=body).status_code)


@pytest.mark.parametrize("role", ALL)
def test_role_against_every_endpoint(client: Any, world: World, role: str) -> None:
    login(client, world, role)
    failures = []
    for group, method, path, body, allowed in endpoints(world):
        status = call(client, method, path, body)
        if status >= 500:
            failures.append(f"{role}: {method} {path} ({group}) returned a server error {status}")
        if role in allowed and status in (401, 403):
            failures.append(f"{role} should reach {method} {path} ({group}) but got {status}")
        if role not in allowed and status != 403:
            failures.append(f"{role} should be forbidden {method} {path} ({group}) but got {status}")
    assert not failures, "\n".join(failures)


def test_unauthenticated_requests_are_rejected_everywhere(client: Any, world: World) -> None:
    failures = []
    for group, method, path, body, _ in endpoints(world):
        status = call(client, method, path, body)
        if status != 401:
            failures.append(f"{method} {path} ({group}) answered {status} without credentials")
    assert not failures, "\n".join(failures)


def test_hidden_actions_are_enforced_on_the_server_for_api_keys(client: Any, world: World) -> None:
    from tests.api_support import key_client

    key_client(client, world.keys["A"])  # scopes: read, alerts
    assert client.get("/api/v1/assets").status_code == 200
    assert (
        client.post("/api/v1/alerts/" + world.alerts["A"] + "/comments", json={"text": "from a key"}).status_code == 201
    )
    assert (
        client.post(
            "/api/v1/assets", json={"name": "n", "geometry": {"type": "Point", "coordinates": [1, 1]}}
        ).status_code
        == 403
    )
    assert client.get("/api/v1/admin/users").status_code == 403
    assert client.get("/api/v1/platform/revenue/summary").status_code == 403
