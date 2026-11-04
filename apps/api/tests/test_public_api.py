"""Marketing site endpoints: demo request fields, newsletter double opt-in, public figures."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from meridian.api import db
from meridian.api.services import mailer


def _demo(**over: Any) -> dict[str, Any]:
    body = {
        "name": "Sam Rivera",
        "email": "sam@example.org",
        "company": "Example Freight",
        "role": "Operations lead",
        "industry": "Logistics and shipping",
        "message": "We track 40 sites.",
        "consent": True,
    }
    return {**body, **over}


def test_demo_request_requires_consent_and_stores_fields(client: TestClient) -> None:
    assert client.post("/api/v1/contact/demo-request", json=_demo(consent=False)).status_code == 422
    ok = client.post("/api/v1/contact/demo-request", json=_demo())
    assert ok.status_code == 202
    with db.system_connection() as conn:
        row = conn.execute(
            "SELECT role, industry, consent_at FROM demo_requests WHERE email = 'sam@example.org'"
        ).fetchone()
    assert row is not None and row[0] == "Operations lead" and row[2] is not None
    with db.system_connection() as conn:  # these tables are not part of the per-test world reset
        conn.execute("DELETE FROM demo_requests WHERE email = 'sam@example.org'")
        conn.commit()


def test_newsletter_double_opt_in(client: TestClient, monkeypatch: Any) -> None:
    capture = mailer.CaptureMailer()
    monkeypatch.setattr(mailer, "get_mailer", lambda: capture)
    first = client.post("/api/v1/newsletter/subscribe", json={"email": "reader@example.org"})
    assert first.status_code == 202
    assert len(capture.sent) == 1
    token = capture.sent[0][2].split("token=")[1].split()[0]
    assert client.post("/api/v1/newsletter/confirm", json={"token": "wrong"}).status_code == 404
    assert client.post("/api/v1/newsletter/confirm", json={"token": token}).status_code == 200
    # a confirmed address gets the same answer and no second message
    again = client.post("/api/v1/newsletter/subscribe", json={"email": "reader@example.org"})
    assert again.json() == first.json() and len(capture.sent) == 1
    with db.system_connection() as conn:
        conn.execute("DELETE FROM newsletter_subscribers WHERE email = 'reader@example.org'")
        conn.commit()


def test_public_stats_are_counts_only(client: TestClient) -> None:
    data = client.get("/api/v1/public/stats").json()
    assert set(data) == {"places_indexed", "places_with_wikidata", "incidents_30d", "event_sources_30d"}
    assert all(isinstance(v, (int, dict)) for v in data.values())
