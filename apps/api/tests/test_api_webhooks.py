"""Webhook signing, delivery, retries, SSRF protection, payload privacy, and live streams."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from typing import Any

import httpx
import psycopg
import pytest

from meridian import notify
from meridian.api.routers import system
from meridian.api.security import crypto
from meridian.api.services import webhooks
from tests.api_support import World, login

API = "/api/v1"
PUBLIC = [(2, 1, 6, "", ("93.184.216.34", 443))]


def public_resolver(host: str, port: int, **kwargs: Any) -> list[Any]:
    return PUBLIC


def private_resolver(host: str, port: int, **kwargs: Any) -> list[Any]:
    return [(2, 1, 6, "", ("10.0.0.5", 443))]


def make_client(status: int = 200, seen: list[httpx.Request] | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status)

    return httpx.Client(transport=httpx.MockTransport(handler))


def queue_delivery(conn: psycopg.Connection[Any], world: World, key: str = "A", min_level: str = "low") -> str:
    conn.execute("UPDATE webhooks SET min_level = %s WHERE id = %s", (min_level, world.hooks[key]))
    conn.commit()
    assert notify.enqueue_webhooks(conn, [world.alerts[key]]) == 1
    conn.commit()
    return str(
        conn.execute("SELECT id FROM webhook_deliveries WHERE webhook_id = %s", (world.hooks[key],)).fetchone()[0]
    )  # type: ignore[index]


def test_signature_roundtrip_and_tamper_detection() -> None:
    body = b'{"a":1}'
    header = webhooks.signature_header(["s1"], 1000, body)
    assert webhooks.verify_signature("s1", header, body, now=1100)
    assert not webhooks.verify_signature("s1", header, b'{"a":2}', now=1100)
    assert not webhooks.verify_signature("other", header, body, now=1100)
    assert not webhooks.verify_signature("s1", header, body, now=1000 + 301)  # replay window
    assert not webhooks.verify_signature("s1", "garbage", body)
    both = webhooks.signature_header(["new", "old"], 1000, body)
    assert webhooks.verify_signature("old", both, body, now=1000) and webhooks.verify_signature(
        "new", both, body, now=1000
    )


def test_creation_rejects_unsafe_urls(client: Any, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    from meridian.api.security import ssrf

    monkeypatch.setattr(ssrf, "_lookup", public_resolver)
    login(client, world, "admin")
    for url in (
        "http://hooks.example.org/in",
        "ftp://hooks.example.org/in",
        "https://127.0.0.1/in",
        "https://169.254.169.254/latest/meta-data",
        "https://user:pass@hooks.example.org/in",
        "https://[::1]/in",
        "https:///nohost",
    ):
        monkeypatch.setattr(ssrf, "_lookup", public_resolver if "example.org" in url else ssrf.socket.getaddrinfo)
        assert client.post(f"{API}/admin/webhooks", json={"name": "h", "url": url}).status_code == 422, url
    monkeypatch.setattr(ssrf, "_lookup", private_resolver)
    assert (
        client.post(f"{API}/admin/webhooks", json={"name": "h", "url": "https://rebind.example.org/in"}).status_code
        == 422
    )
    monkeypatch.setattr(ssrf, "_lookup", public_resolver)
    ok = client.post(
        f"{API}/admin/webhooks", json={"name": "Ops", "url": "https://hooks.example.org/in", "min_level": "high"}
    )
    assert ok.status_code == 201 and ok.json()["signing_secret"].startswith("whsec_")
    listed = client.get(f"{API}/admin/webhooks").json()["items"]
    assert all(
        "signing_secret" not in h and "secret" not in json.dumps(h).lower().replace("secret_rotated_at", "")
        for h in listed
    )
    assert (
        client.patch(f"{API}/admin/webhooks/{ok.json()['id']}", json={"url": "http://insecure.example.org"}).status_code
        == 422
    )


def test_secret_is_encrypted_at_rest_and_rotation_keeps_the_old_one_for_a_week(
    client: Any, world: World, conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    login(client, world, "admin")
    rotated = client.post(f"{API}/admin/webhooks/{world.hooks['A']}/rotate-secret").json()
    row = conn.execute(
        "SELECT secret_encrypted, previous_secret_encrypted FROM webhooks WHERE id = %s", (world.hooks["A"],)
    ).fetchone()
    assert row is not None and rotated["signing_secret"].encode() not in bytes(row[0])
    assert crypto.decrypt(row[0]) == rotated["signing_secret"] and crypto.decrypt(row[1]) == "whsec_test"
    delivery = queue_delivery(conn, world)
    seen: list[httpx.Request] = []
    assert webhooks.deliver_one(conn, delivery, client=make_client(200, seen), resolver=public_resolver) == "delivered"
    header = seen[0].headers["x-meridian-signature"]
    assert header.count("v1=") == 2
    assert webhooks.verify_signature("whsec_test", header, seen[0].content) and webhooks.verify_signature(
        rotated["signing_secret"], header, seen[0].content
    )
    conn.execute("UPDATE webhooks SET secret_rotated_at = now() - interval '8 days' WHERE id = %s", (world.hooks["A"],))
    conn.commit()
    conn.execute("UPDATE webhook_deliveries SET status = 'pending'")
    conn.commit()
    seen.clear()
    webhooks.deliver_one(conn, delivery, client=make_client(200, seen), resolver=public_resolver)
    assert seen[0].headers["x-meridian-signature"].count("v1=") == 1


def test_enqueue_respects_level_and_tenant(conn: psycopg.Connection[Any], world: World) -> None:
    conn.execute("UPDATE webhooks SET min_level = 'critical' WHERE id = %s", (world.hooks["A"],))
    conn.commit()
    assert notify.enqueue_webhooks(conn, [world.alerts["A"]]) == 0  # the alert is high
    conn.execute("UPDATE webhooks SET min_level = 'high' WHERE id = %s", (world.hooks["A"],))
    conn.execute("UPDATE webhooks SET enabled = false WHERE id = %s", (world.hooks["B"],))
    conn.commit()
    assert notify.enqueue_webhooks(conn, [world.alerts["A"], world.alerts["B"]]) == 1
    conn.commit()
    rows = conn.execute("SELECT webhook_id, tenant_id FROM webhook_deliveries").fetchall()
    assert [(str(r[0]), str(r[1])) for r in rows] == [(world.hooks["A"], world.tenants["A"])]


def test_payload_contains_no_coordinates_unless_both_opt_in(conn: psycopg.Connection[Any], world: World) -> None:
    def payload_for(hook_flag: bool, tenant_flag: bool) -> dict[str, Any]:
        conn.execute("DELETE FROM webhook_deliveries")
        conn.execute(
            "UPDATE webhooks SET include_coordinates = %s, min_level = 'low' WHERE id = %s",
            (hook_flag, world.hooks["A"]),
        )
        conn.execute(
            "UPDATE tenants SET settings = %s WHERE id = %s",
            (json.dumps({"risk_config": {"include_coordinates": tenant_flag}}), world.tenants["A"]),
        )
        conn.commit()
        notify.enqueue_webhooks(conn, [world.alerts["A"]])
        conn.commit()
        return conn.execute("SELECT payload FROM webhook_deliveries").fetchone()[0]  # type: ignore[no-any-return,index]

    default = payload_for(False, False)
    assert (
        default["asset"] == {"name": "A near", "distance_km": 1.2} and "not official warnings" in default["disclaimer"]
    )
    assert "latitude" not in json.dumps(payload_for(True, False)) and "latitude" not in json.dumps(
        payload_for(False, True)
    )
    both = payload_for(True, True)
    assert both["asset"]["latitude"] == pytest.approx(39.80, abs=0.01)
    assert default["event"]["confirmation"] == "reported, not yet confirmed" and default["link"].startswith(
        "/app/alerts/"
    )


def test_delivery_success_failure_and_backoff(conn: psycopg.Connection[Any], world: World) -> None:
    delivery = queue_delivery(conn, world)
    assert webhooks.deliver_one(conn, delivery, client=make_client(503), resolver=public_resolver) == "retry"
    row = conn.execute(
        "SELECT status, attempts, last_status_code, next_attempt_at > now() + interval '50 seconds' FROM webhook_deliveries WHERE id = %s",
        (delivery,),
    ).fetchone()
    assert row == ("pending", 1, 503, True)
    expected = webhooks.BACKOFF_SECONDS
    assert expected == sorted(expected) and expected[0] == 60
    for _ in range(2, webhooks.MAX_ATTEMPTS):
        assert webhooks.deliver_one(conn, delivery, client=make_client(500), resolver=public_resolver) == "retry"
    assert webhooks.deliver_one(conn, delivery, client=make_client(500), resolver=public_resolver) == "abandoned"
    assert conn.execute("SELECT status, attempts FROM webhook_deliveries WHERE id = %s", (delivery,)).fetchone() == (
        "abandoned",
        webhooks.MAX_ATTEMPTS,
    )
    ok = queue_delivery(conn, world, "B")
    assert webhooks.deliver_one(conn, ok, client=make_client(204), resolver=public_resolver) == "delivered"
    assert conn.execute(
        "SELECT status, delivered_at IS NOT NULL FROM webhook_deliveries WHERE id = %s", (ok,)
    ).fetchone() == ("delivered", True)


def test_delivery_blocks_non_public_targets_without_retrying(conn: psycopg.Connection[Any], world: World) -> None:
    delivery = queue_delivery(conn, world)
    seen: list[httpx.Request] = []
    result = webhooks.deliver_one(conn, delivery, client=make_client(200, seen), resolver=private_resolver)
    assert result == "abandoned" and seen == []  # nothing was sent
    assert conn.execute("SELECT last_error FROM webhook_deliveries WHERE id = %s", (delivery,)).fetchone() == (
        "target not allowed",
    )


def test_disabled_webhooks_are_not_called(conn: psycopg.Connection[Any], world: World) -> None:
    delivery = queue_delivery(conn, world)
    conn.execute("UPDATE webhooks SET enabled = false WHERE id = %s", (world.hooks["A"],))
    conn.commit()
    seen: list[httpx.Request] = []
    assert (
        webhooks.deliver_one(conn, delivery, client=make_client(200, seen), resolver=public_resolver) == "abandoned"
        and seen == []
    )


def test_run_due_only_processes_due_deliveries(conn: psycopg.Connection[Any], world: World) -> None:
    queue_delivery(conn, world)
    conn.execute(
        "INSERT INTO webhook_deliveries (webhook_id, tenant_id, kind, payload, next_attempt_at) VALUES (%s, %s, 'test', '{}', now() + interval '1 hour')",
        (world.hooks["A"], world.tenants["A"]),
    )
    conn.commit()
    counts = webhooks.run_due(conn, client=make_client(200), resolver=public_resolver)
    assert counts == {"delivered": 1, "retry": 0, "abandoned": 0}


def test_test_delivery_and_log_endpoints(client: Any, world: World, conn: psycopg.Connection[Any]) -> None:
    login(client, world, "admin")
    queued = client.post(f"{API}/admin/webhooks/{world.hooks['A']}/test")
    assert queued.status_code == 202
    log = client.get(f"{API}/admin/webhooks/{world.hooks['A']}/deliveries").json()["items"]
    assert log[0]["kind"] == "test" and log[0]["status"] == "pending"
    assert client.post(f"{API}/admin/webhooks/{world.hooks['B']}/test").status_code == 404


# -- live streams ---------------------------------------------------------------------------------------------------------------
class FakeRequest:
    def __init__(self, polls: int) -> None:
        self.polls = polls

    async def is_disconnected(self) -> bool:
        self.polls -= 1
        return self.polls < 0


def collect(channel: str, key: str, polls: int = 3, before: Any = None) -> list[str]:
    async def run() -> list[str]:
        out = []
        stream = system._stream(FakeRequest(polls), channel, key)  # type: ignore[arg-type]
        async for chunk in stream:
            out.append(chunk)
            if before and len(out) == 1:
                before()
        return out

    return asyncio.run(run())


def test_streams_deliver_only_the_tenants_own_messages(conn: psycopg.Connection[Any], world: World) -> None:
    def publish() -> None:
        notify.publish_alerts(conn, [world.alerts["A"], world.alerts["B"]])

    chunks = collect(f"alerts:{world.tenants['A']}", world.tenants["A"], before=publish)
    text = "".join(chunks)
    assert "event: update" in text and "A near" in text and "B near" not in text and "latitude" not in text
    events = "".join(collect(f"events:{world.tenants['B']}", world.tenants["B"], before=publish))
    assert "Fire near B" in events and "Fire near A" not in events
    assert "not official warnings" in events


def test_stream_connection_cap(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    from meridian.api.errors import ProblemError

    monkeypatch.setenv("MS_SSE_CONNECTIONS_PER_TENANT", "1")
    system._open_streams.clear()
    system._open_streams[world.tenants["A"]] = 1
    with pytest.raises(ProblemError) as caught:
        collect(f"alerts:{world.tenants['A']}", world.tenants["A"])
    assert caught.value.status == 429
    system._open_streams.clear()


def test_stream_endpoints_need_a_tenant_and_permission(client: Any, world: World) -> None:
    login(client, world, "finance")
    assert client.get(f"{API}/stream/alerts").status_code == 403
    login(client, world, "platform")
    assert client.get(f"{API}/stream/alerts").status_code == 403  # no tenant context


# -- pipeline integration -----------------------------------------------------------------------------------------------------------
def test_pipeline_queues_webhooks_and_publishes_after_commit(
    conn: psycopg.Connection[Any], world: World, tmp_path: Any
) -> None:
    from meridian.events import service
    from meridian.events.config import load_events_config

    conn.execute("DELETE FROM alerts")
    conn.execute("DELETE FROM exposures")
    conn.execute(
        "DELETE FROM watch_zones WHERE tenant_id = %s", (world.tenants["B"],)
    )  # the seeded zones cover this area
    conn.execute("UPDATE webhooks SET min_level = 'low' WHERE id = %s", (world.hooks["A"],))
    conn.commit()
    when = dt.datetime.now(dt.UTC)
    ms = int(when.timestamp() * 1000)
    quake = {
        "feature": {
            "id": "us-int-1",
            "properties": {"mag": 6.6, "time": ms, "updated": ms, "type": "earthquake", "title": "M 6.6 test"},
            "geometry": {"type": "Point", "coordinates": [-89.64, 39.80, 10.0]},
        }
    }
    path = tmp_path / "q.jsonl"
    path.write_text(json.dumps(quake) + "\n", encoding="utf-8")
    subscription = notify.Subscription(f"alerts:{world.tenants['A']}")
    other = notify.Subscription(f"alerts:{world.tenants['B']}")
    try:
        run = service.ingest_usgs(conn, load_events_config(), [path], now=when)
        message = subscription.get(timeout=2)
        assert other.get(timeout=0.2) is None
    finally:
        subscription.close()
        other.close()
    assert run.alerts.created >= 1 and message is not None
    assert json.loads(message)["asset"]["name"] == "A near"
    queued = conn.execute(
        "SELECT count(*) FROM webhook_deliveries WHERE tenant_id = %s AND alert_id IS NOT NULL", (world.tenants["A"],)
    ).fetchone()
    assert queued is not None and queued[0] >= 1
    assert conn.execute(
        "SELECT count(*) FROM webhook_deliveries WHERE tenant_id = %s", (world.tenants["B"],)
    ).fetchone() == (0,)
