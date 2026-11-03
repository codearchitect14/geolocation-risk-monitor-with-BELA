"""Unit tests for the security building blocks and a structural check that every route is protected."""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
from collections.abc import Iterator
from typing import Any

import jwt
import psycopg
import pyotp
import pytest

from meridian.api import auth
from meridian.api.errors import ProblemError
from meridian.api.pagination import clamp_limit, decode_cursor, encode_cursor
from meridian.api.permissions import ROLE_PERMISSIONS, SCOPE_PERMISSIONS, permissions_for_scopes
from meridian.api.security import mfa, ratelimit, ssrf, tokens
from meridian.api.services import briefings, uploads
from tests.api_support import World

PUBLIC_ROUTES = {
    ("GET", "/api/v1/health"), ("GET", "/api/v1/health/ready"), ("POST", "/api/v1/auth/login"), ("POST", "/api/v1/auth/mfa/setup"),
    ("POST", "/api/v1/auth/mfa/verify"), ("POST", "/api/v1/auth/refresh"), ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/auth/password/forgot"), ("POST", "/api/v1/auth/password/reset"), ("POST", "/api/v1/contact/demo-request"),
}  # fmt: skip


def _dependencies(dependant: Any) -> Iterator[Any]:
    for dep in dependant.dependencies:
        yield dep.call
        yield from _dependencies(dep)


def _is_permission_check(call: Any) -> bool:
    return getattr(call, "__qualname__", "").startswith("require.")


def test_every_route_requires_authentication_unless_listed_as_public(app: Any) -> None:
    unprotected = []
    for route in app.routes:
        if not getattr(route, "path", "").startswith("/api/v1"):
            continue
        calls = list(_dependencies(route.dependant))
        guarded = auth.get_principal in calls or any(_is_permission_check(c) for c in calls)
        for method in route.methods - {"HEAD", "OPTIONS"}:
            if not guarded and (method, route.path) not in PUBLIC_ROUTES:
                unprotected.append(f"{method} {route.path}")
    assert not unprotected, unprotected


def test_routes_that_use_a_tenant_connection_also_check_a_permission(app: Any) -> None:
    gaps = []
    for route in app.routes:
        if not getattr(route, "path", "").startswith("/api/v1"):
            continue
        calls = list(_dependencies(route.dependant))
        if auth.get_tx in calls and not any(_is_permission_check(c) for c in calls):
            gaps.append(route.path)
    assert not gaps, gaps


def test_permission_table_matches_the_specification() -> None:
    p = ROLE_PERMISSIONS
    assert p["viewer"] == {"view"}
    assert "alerts.act" in p["analyst"] and "assets.write" not in p["analyst"]
    assert {"assets.write", "rules.manage"} <= p["manager"] and "admin.manage" not in p["manager"]
    assert {"admin.manage", "audit.view"} <= p["tenant_admin"] and "revenue.view" not in p["tenant_admin"]
    assert p["finance_analyst"] == {"revenue.view"}
    assert "platform.manage" in p["platform_admin"] and "platform.manage" not in p["tenant_admin"]
    granted = permissions_for_scopes(list(SCOPE_PERMISSIONS))
    assert not granted & {"admin.manage", "audit.view", "revenue.view", "platform.manage"}


def test_tokens_reject_tampering_and_wrong_types(world: World) -> None:
    good = tokens.access_token("user-1", "family-1")
    assert tokens.decode(good, "access") is not None and tokens.decode(good, "mfa") is None
    assert tokens.decode(good + "x", "access") is None and tokens.decode("", "access") is None
    forged = jwt.encode(
        {"sub": "u", "typ": "access", "iss": tokens.ISSUER, "aud": tokens.AUDIENCE, "exp": 9999999999, "iat": 1},
        "secret" * 8,
        algorithm="HS256",
    )
    assert tokens.decode(forged, "access") is None
    none_alg = jwt.encode({"sub": "u", "typ": "access", "exp": 9999999999, "iat": 1}, None, algorithm="none")
    assert tokens.decode(none_alg, "access") is None
    assert tokens.decode(tokens.issue("access", "u", -10), "access") is None
    claims = tokens.decode(tokens.issue("access", "u", 60), "access")
    assert claims is not None and claims["sub"] == "u"
    assert jwt.get_unverified_header(good)["alg"] == "EdDSA"
    assert tokens.new_refresh_token() != tokens.new_refresh_token() and len(tokens.new_refresh_token()) >= 60


def test_totp_window_and_recovery_codes() -> None:
    secret = mfa.new_secret()
    now = time.time()
    totp = pyotp.TOTP(secret)
    assert mfa.verify_code(secret, totp.at(int(now)), now) is not None
    assert mfa.verify_code(secret, totp.at(int(now) - 30), now) is not None  # one step of drift
    assert mfa.verify_code(secret, totp.at(int(now) - 90), now) is None
    assert mfa.verify_code(secret, "12345", now) is None and mfa.verify_code(secret, "abcdef", now) is None
    codes = mfa.new_recovery_codes()
    assert len(codes) == 10 and len(set(codes)) == 10 and all(len(c) == 19 for c in codes)
    assert mfa.hash_recovery_code(codes[0].lower()) == mfa.hash_recovery_code(codes[0])
    assert mfa.provisioning_uri(secret, "a@example.org").startswith("otpauth://totp/Meridian%20Signal:")


def fake(addresses: list[str]) -> Any:
    def resolver(host: str, port: int, **kwargs: Any) -> list[Any]:
        return [
            (socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port)) for a in addresses
        ]

    return resolver


@pytest.mark.parametrize(
    "address",
    [
        "10.1.2.3",
        "172.16.0.1",
        "192.168.1.1",
        "127.0.0.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:10.0.0.1",
        "::ffff:127.0.0.1",
        "240.0.0.1",
    ],
)  # noqa: S104
def test_ssrf_blocks_non_public_addresses(address: str) -> None:
    assert not ssrf.is_public(address)
    with pytest.raises(ssrf.UnsafeUrl):
        ssrf.validate_url("https://target.example.org/hook", fake([address]))


def test_ssrf_validation_rules() -> None:
    assert ssrf.is_public("93.184.216.34") and ssrf.is_public("2606:2800:220:1:248:1893:25c8:1946")
    host, port, addresses = ssrf.validate_url("https://target.example.org:8443/hook?x=1", fake(["93.184.216.34"]))
    assert (host, port, addresses) == ("target.example.org", 8443, ["93.184.216.34"])
    with pytest.raises(ssrf.UnsafeUrl):
        ssrf.validate_url(
            "https://target.example.org/", fake(["93.184.216.34", "10.0.0.1"])
        )  # one private answer is enough to refuse
    for url in (
        "http://target.example.org/",
        "https://u:p@target.example.org/",
        "https:///x",
        "ftp://x/",
        "//x/y",
        "javascript:alert(1)",
        "",
    ):
        with pytest.raises(ssrf.UnsafeUrl):
            ssrf.validate_url(url, fake(["93.184.216.34"]))

    def failing(*args: Any, **kwargs: Any) -> list[Any]:
        raise OSError("no such host")

    with pytest.raises(ssrf.UnsafeUrl):
        ssrf.validate_url("https://missing.example.org/", failing)


def test_memory_rate_limiter() -> None:
    backend = ratelimit.MemoryBackend()
    assert [backend.incr("k", 60)[0] for _ in range(3)] == [1, 2, 3]
    assert backend.incr("other", 60)[0] == 1
    assert backend.once("a", 60) is True and backend.once("a", 60) is False
    previous = ratelimit._backend
    ratelimit._backend = backend
    try:
        ratelimit.check("x", 2, 60)
        ratelimit.check("x", 2, 60)
        with pytest.raises(ProblemError) as caught:
            ratelimit.check("x", 2, 60)
        assert caught.value.status == 429 and caught.value.headers["Retry-After"]
    finally:
        ratelimit._backend = previous


@pytest.fixture(scope="module")
def valkey_url() -> Iterator[str]:
    binary = shutil.which("valkey-server")
    if not binary:
        pytest.skip("valkey-server is not installed")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen(
        [binary, "--port", str(port), "--save", "", "--appendonly", "no", "--bind", "127.0.0.1"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )  # noqa: S603
    url = f"valkey://127.0.0.1:{port}/0"
    try:
        for _ in range(50):
            try:
                import valkey

                valkey.Valkey.from_url(url).ping()
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.1)
        else:
            pytest.skip("valkey did not start")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_valkey_rate_limiter_is_shared_between_instances(valkey_url: str) -> None:
    one, two = ratelimit.ValkeyBackend(valkey_url), ratelimit.ValkeyBackend(valkey_url)
    assert one.incr("shared", 60)[0] == 1 and two.incr("shared", 60)[0] == 2
    assert one.once("code", 60) is True and two.once("code", 60) is False
    assert ratelimit.configure(valkey_url).__class__ is ratelimit.ValkeyBackend
    assert ratelimit.configure("valkey://127.0.0.1:1/0").__class__ is ratelimit.MemoryBackend  # unreachable: falls back
    ratelimit.configure(None)


def test_valkey_pubsub_delivers_across_publishers(valkey_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from meridian import notify

    monkeypatch.setenv("MS_VALKEY_URL", valkey_url)
    monkeypatch.setattr(notify, "_valkey", None)
    sub = notify.Subscription("alerts:test-tenant")
    other = notify.Subscription("alerts:other-tenant")
    try:
        time.sleep(0.2)
        notify.publish("alerts:test-tenant", {"hello": "world"})
        message = None
        for _ in range(10):
            message = sub.get(timeout=0.3)
            if message:
                break
        assert message is not None and '"hello": "world"' in message
        assert other.get(timeout=0.3) is None
    finally:
        sub.close()
        other.close()
    monkeypatch.setattr(notify, "_valkey", None)


def test_cursor_helpers() -> None:
    cursor = encode_cursor("2026-01-01T00:00:00+00:00", "abc")
    assert decode_cursor(cursor, 2) == ["2026-01-01T00:00:00+00:00", "abc"] and decode_cursor(None, 2) is None
    for bad in ("not base64!!", encode_cursor("only-one"), "e30"):
        with pytest.raises(ProblemError):
            decode_cursor(bad, 2)
    assert clamp_limit(None) == 50 and clamp_limit(0) == 1 and clamp_limit(10_000) == 200


def test_upload_helpers() -> None:
    assert (
        uploads.csv_safe("=SUM(A1)") == "'=SUM(A1)"
        and uploads.csv_safe("@x") == "'@x"
        and uploads.csv_safe("ok") == "ok"
        and uploads.csv_safe(5) == 5
    )
    assert uploads.clean_text("a\x00b\x07c  ") == "abc"
    assert uploads.count_vertices([[[0, 0], [1, 1]], [[2, 2]]]) == 3
    assert (
        uploads.valid_position(10, 20)
        and not uploads.valid_position(181, 0)
        and not uploads.valid_position(0, -91)
        and not uploads.valid_position(True, 1)
    )
    assert uploads._check_geometry({"type": "Point", "coordinates": [1, 1]}, 10) is None
    assert uploads._check_geometry({"type": "Point", "coordinates": ["a", 1]}, 10) is not None
    assert (
        uploads._check_geometry({"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}, 2)
        == "geometry has too many vertices"
    )


EVIDENCE = {
    "period_start": "2026-11-01T00:00:00+00:00", "period_end": "2026-11-02T00:00:00+00:00", "total_alerts": 2,
    "alerts_by_level": {"critical": 0, "high": 1, "medium": 1, "low": 0},
    "items": [{"level": "high", "title": "Fire near Springfield", "asset": "Plant 7", "distance_km": 3.2, "confirmation": "reported, not yet confirmed", "source_url": "https://news.example/a"}],
}  # fmt: skip


def test_briefing_narratives_are_validated_against_the_evidence() -> None:
    from meridian.notify import DISCLAIMER

    template = briefings.template_narrative(EVIDENCE)
    assert briefings.validate_narrative(template, EVIDENCE) and DISCLAIMER in template
    honest = (
        f"Two alerts were raised. A fire near Springfield is 3.2 km from Plant 7 (https://news.example/a). {DISCLAIMER}"
    )
    assert briefings.narrative_for(EVIDENCE, lambda e: honest) == (honest, "local_model_validated_v1")
    for bad in (
        honest.replace("3.2 km", "9.9 km"),
        honest.replace("https://news.example/a", "https://evil.example/x"),
        honest.replace(DISCLAIMER, ""),
    ):
        narrative, version = briefings.narrative_for(EVIDENCE, lambda e, b=bad: b)  # type: ignore[misc]
        assert version == "briefing_template_v1" and "9.9" not in narrative and "evil.example" not in narrative

    def broken(evidence: dict[str, Any]) -> str:
        raise RuntimeError("model unavailable")

    assert briefings.narrative_for(EVIDENCE, broken)[1] == "briefing_template_v1"


def test_purge_respects_retention_and_never_touches_the_audit_log(world: World, conn: psycopg.Connection[Any]) -> None:
    from meridian.api import worker

    conn.execute(
        "UPDATE alerts SET status = 'resolved', updated_at = now() - interval '400 days' WHERE id = %s",
        (world.alerts["A"],),
    )
    conn.execute(
        "UPDATE alerts SET status = 'resolved', updated_at = now() - interval '400 days' WHERE id = %s",
        (world.alerts["B"],),
    )
    conn.execute(
        "UPDATE tenants SET settings = %s WHERE id = %s",
        ('{"risk_config": {"retention_days": 1000}}', world.tenants["B"]),
    )
    conn.execute(
        "UPDATE briefings SET created_at = now() - interval '500 days' WHERE tenant_id = %s", (world.tenants["A"],)
    )
    conn.execute(
        "INSERT INTO refresh_tokens (user_id, family_id, token_hash, expires_at, absolute_expires_at) VALUES (%s, gen_random_uuid(), 'old', now(), now() - interval '3 days')",
        (world.users["viewer"],),
    )
    conn.commit()
    before = conn.execute("SELECT count(*) FROM audit_log").fetchone()[0]  # type: ignore[index]
    counts = worker.purge(conn)
    conn.commit()
    assert counts["alerts"] == 1 and counts["briefings"] == 1 and counts["tokens"] >= 1
    assert {str(r[0]) for r in conn.execute("SELECT id FROM alerts").fetchall()} == {
        world.alerts["B"]
    }  # tenant B keeps alerts for 1000 days
    assert conn.execute("SELECT count(*) FROM audit_log").fetchone()[0] == before + 1  # type: ignore[index]  # only the purge entry was added
    assert worker.verify_audit(conn)["intact"] is True


def test_worker_run_once_with_nothing_due(world: World) -> None:
    from meridian.api import worker

    result = worker.run_once()
    assert result["webhooks"] == {"delivered": 0, "retry": 0, "abandoned": 0} and result["escalated"] == 0
