"""Authentication and session behavior."""

from __future__ import annotations

import re
from typing import Any

import psycopg
import pyotp
import pytest
from fastapi.testclient import TestClient

from meridian.api.security import ratelimit
from tests.api_support import PASSWORD, World, email_of, key_client, login

URL = "/api/v1/auth"


def fresh(app: Any) -> TestClient:
    return TestClient(app, base_url="https://testserver", raise_server_exceptions=False)


def test_login_sets_hardened_cookies(client: Any, world: World) -> None:
    response = client.post(f"{URL}/login", json={"email": email_of("viewer"), "password": PASSWORD})
    assert response.status_code == 200 and response.json()["status"] == "ok"
    cookies = {c.split("=")[0]: c for c in response.headers.get_list("set-cookie")}
    for name in ("ms_access", "ms_refresh"):
        assert "HttpOnly" in cookies[name] and "Secure" in cookies[name] and "samesite=strict" in cookies[name].lower()
    assert "HttpOnly" not in cookies["ms_csrf"]  # readable so the web app can send it back
    assert "path=/api/v1/auth" in cookies["ms_refresh"].lower()
    assert "token" not in response.text.lower()  # tokens only travel in cookies


def test_wrong_password_and_unknown_account_look_identical(client: Any, world: World) -> None:
    wrong = client.post(f"{URL}/login", json={"email": email_of("viewer"), "password": "not the password at all"})
    unknown = client.post(f"{URL}/login", json={"email": "nobody@example.org", "password": "not the password at all"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"] and wrong.json()["type"] == unknown.json()["type"]


def test_lockout_after_repeated_failures_even_with_the_right_password(
    client: Any, world: World, conn: psycopg.Connection[Any]
) -> None:
    for _ in range(5):
        assert (
            client.post(f"{URL}/login", json={"email": email_of("viewer"), "password": "wrong wrong wrong"}).status_code
            == 401
        )
    locked = client.post(f"{URL}/login", json={"email": email_of("viewer"), "password": PASSWORD})
    assert locked.status_code == 401 and locked.json()["detail"] == "The email or password is not correct."
    assert conn.execute(
        "SELECT locked_until > now() FROM users WHERE id = %s", (world.users["viewer"],)
    ).fetchone() == (True,)
    reasons = [
        r[0]
        for r in conn.execute(
            "SELECT detail->>'reason' FROM audit_log WHERE action = 'auth.login_failed' AND actor_user_id = %s ORDER BY id",
            (world.users["viewer"],),
        ).fetchall()
    ]
    assert reasons[-1] == "locked" and reasons.count("bad_password") == 5
    conn.execute("UPDATE users SET locked_until = NULL, failed_login_count = 0 WHERE id = %s", (world.users["viewer"],))
    conn.commit()
    assert client.post(f"{URL}/login", json={"email": email_of("viewer"), "password": PASSWORD}).status_code == 200


def test_login_rate_limits_per_ip_and_per_account(client: Any, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MS_LOGIN_ACCOUNT_PER_15MIN", "3")
    ratelimit._backend.reset()  # type: ignore[attr-defined]
    codes = [
        client.post(f"{URL}/login", json={"email": email_of("analyst"), "password": "wrong wrong wrong"}).status_code
        for _ in range(5)
    ]
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]
    limited = client.post(f"{URL}/login", json={"email": email_of("analyst"), "password": PASSWORD})
    assert limited.status_code == 429 and "Retry-After" in limited.headers
    monkeypatch.setenv("MS_LOGIN_ACCOUNT_PER_15MIN", "100000")
    monkeypatch.setenv("MS_LOGIN_IP_PER_MINUTE", "2")
    ratelimit._backend.reset()  # type: ignore[attr-defined]
    statuses = [
        client.post(f"{URL}/login", json={"email": f"user{i}@example.org", "password": "wrong wrong wrong"}).status_code
        for i in range(4)
    ]
    assert statuses == [401, 401, 429, 429]


def test_administrators_must_use_mfa(client: Any, world: World, conn: psycopg.Connection[Any]) -> None:
    conn.execute("DELETE FROM user_mfa WHERE user_id = %s", (world.users["admin"],))
    conn.commit()
    start = client.post(f"{URL}/login", json={"email": email_of("admin"), "password": PASSWORD}).json()
    assert start["status"] == "mfa_enrollment_required" and "ms_access" not in client.cookies
    setup = client.post(f"{URL}/mfa/setup", json={"setup_token": start["setup_token"]}).json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/") and setup["qr_svg"].startswith("<svg")
    stored = conn.execute(
        "SELECT totp_secret_encrypted, enabled FROM user_mfa WHERE user_id = %s", (world.users["admin"],)
    ).fetchone()
    assert (
        stored is not None and stored[1] is False and setup["secret"].encode() not in bytes(stored[0])
    )  # encrypted at rest
    wrong = client.post(f"{URL}/mfa/verify", json={"setup_token": start["setup_token"], "code": "000000"})
    assert wrong.status_code == 401
    done = client.post(
        f"{URL}/mfa/verify", json={"setup_token": start["setup_token"], "code": pyotp.TOTP(setup["secret"]).now()}
    )
    assert done.status_code == 200 and len(done.json()["recovery_codes"]) == 10 and "ms_access" in client.cookies
    assert client.get(f"{URL}/me").json()["mfa_enabled"] is True
    hashed = conn.execute(
        "SELECT recovery_code_hashes FROM user_mfa WHERE user_id = %s", (world.users["admin"],)
    ).fetchone()[0]  # type: ignore[index]
    assert done.json()["recovery_codes"][0] not in hashed and len(hashed) == 10


def test_totp_codes_are_single_use_and_recovery_codes_work_once(client: Any, world: World) -> None:
    ratelimit._backend.reset()  # type: ignore[attr-defined]
    first = client.post(f"{URL}/login", json={"email": email_of("admin"), "password": PASSWORD}).json()
    assert first["status"] == "mfa_required"
    code = pyotp.TOTP(world.totp["admin"]).now()
    assert client.post(f"{URL}/mfa/verify", json={"mfa_token": first["mfa_token"], "code": code}).status_code == 200
    again = client.post(f"{URL}/login", json={"email": email_of("admin"), "password": PASSWORD}).json()
    assert (
        client.post(f"{URL}/mfa/verify", json={"mfa_token": again["mfa_token"], "code": code}).status_code == 401
    )  # replay
    recovery = {"mfa_token": again["mfa_token"], "recovery_code": "aaaa-bbbb-cccc-dddd"}
    assert client.post(f"{URL}/mfa/verify", json=recovery).status_code == 200
    third = client.post(f"{URL}/login", json={"email": email_of("admin"), "password": PASSWORD}).json()
    assert (
        client.post(
            f"{URL}/mfa/verify", json={"mfa_token": third["mfa_token"], "recovery_code": "AAAA-BBBB-CCCC-DDDD"}
        ).status_code
        == 401
    )


def test_mfa_token_is_not_an_access_token(client: Any, world: World) -> None:
    start = client.post(f"{URL}/login", json={"email": email_of("admin"), "password": PASSWORD}).json()
    client.cookies.set("ms_access", start["mfa_token"])
    assert client.get(f"{URL}/me").status_code == 401


def test_refresh_rotates_and_reuse_revokes_the_family(client: Any, app: Any, world: World) -> None:
    login(client, world, "viewer")
    old_refresh, csrf = client.cookies.get("ms_refresh"), client.cookies.get("ms_csrf")
    assert client.post(f"{URL}/refresh").status_code == 200
    new_refresh = client.cookies.get("ms_refresh")
    assert new_refresh != old_refresh
    assert client.get("/api/v1/assets").status_code == 200
    thief = fresh(app)
    replay = thief.post(
        f"{URL}/refresh", headers={"Cookie": f"ms_refresh={old_refresh}; ms_csrf={csrf}", "X-CSRF-Token": csrf}
    )
    assert replay.status_code == 401
    assert (
        client.get("/api/v1/assets").status_code == 401
    )  # the whole family is revoked, including the legitimate session
    assert client.post(f"{URL}/refresh").status_code == 401


def test_expired_and_forged_access_tokens_are_rejected(
    client: Any, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MS_ACCESS_TTL_SECONDS", "-5")
    login(client, world, "viewer")
    assert client.get("/api/v1/assets").status_code == 401
    monkeypatch.setenv("MS_ACCESS_TTL_SECONDS", "900")
    login(client, world, "viewer")
    token = client.cookies.get("ms_access")
    client.cookies.set("ms_access", token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB"))
    assert client.get("/api/v1/assets").status_code == 401
    client.cookies.set("ms_access", "eyJhbGciOiJub25lIn0.e30.")
    assert client.get("/api/v1/assets").status_code == 401


def test_session_lifetimes_idle_and_absolute(client: Any, world: World, conn: psycopg.Connection[Any]) -> None:
    login(client, world, "analyst")
    conn.execute(
        "UPDATE refresh_tokens SET expires_at = now() - interval '1 minute' WHERE user_id = %s",
        (world.users["analyst"],),
    )
    conn.commit()
    assert client.post(f"{URL}/refresh").status_code == 401  # idle timeout
    login(client, world, "analyst")
    conn.execute(
        "UPDATE refresh_tokens SET absolute_expires_at = now() - interval '1 minute' WHERE user_id = %s",
        (world.users["analyst"],),
    )
    conn.commit()
    assert client.get("/api/v1/assets").status_code == 401  # absolute lifetime also ends access tokens
    assert client.post(f"{URL}/refresh").status_code == 401


def test_logout_ends_the_session(client: Any, world: World) -> None:
    login(client, world, "viewer")
    assert client.post(f"{URL}/logout").status_code == 204
    assert client.get("/api/v1/assets").status_code == 401
    assert client.post(f"{URL}/refresh").status_code == 401


def test_csrf_is_required_for_cookie_sessions_only(client: Any, world: World) -> None:
    login(client, world, "manager")
    body = {"name": "csrf test", "geometry": {"type": "Point", "coordinates": [1, 1]}}
    token = client.headers.pop("X-CSRF-Token")
    assert client.post("/api/v1/assets", json=body).status_code == 403
    assert client.post("/api/v1/assets", json=body, headers={"X-CSRF-Token": "x" * len(token)}).status_code == 403
    assert client.post("/api/v1/assets", json=body, headers={"X-CSRF-Token": token}).status_code == 201
    assert client.get("/api/v1/assets").status_code == 200  # safe methods do not need it
    assert client.post(f"{URL}/refresh").status_code == 403
    assert client.post(f"{URL}/logout").status_code == 403


def test_password_policy(client: Any, world: World) -> None:
    from meridian.api.security import passwords

    for weak in ("short1!", "password1234", "aaaaaaaaaaaa", "qwertyuiop12", "meridianmeridian"):
        with pytest.raises(passwords.PasswordPolicyError):
            passwords.validate_password(weak, ["meridian"])
    passwords.validate_password("lantern orbit velvet quarry")
    passwords.validate_password("a long phrase without digits or symbols but with many unrelated words")
    with pytest.raises(passwords.PasswordPolicyError):
        passwords.validate_password("x" * 200)
    hashed = passwords.hash_password("lantern orbit velvet quarry")
    assert hashed.startswith("$argon2id$") and passwords.verify_password(hashed, "lantern orbit velvet quarry")
    assert not passwords.verify_password(hashed, "other") and not passwords.verify_password("garbage", "x")


def test_password_reset_flow(client: Any, world: World, mailer: Any, conn: psycopg.Connection[Any]) -> None:
    known = client.post(f"{URL}/password/forgot", json={"email": email_of("viewer")})
    unknown = client.post(f"{URL}/password/forgot", json={"email": "ghost@example.org"})
    assert known.status_code == unknown.status_code == 202 and known.json() == unknown.json()
    assert [m[0] for m in mailer.sent] == [email_of("viewer")]
    token = re.search(r"token=([\w-]+)", mailer.sent[0][2]).group(1)  # type: ignore[union-attr]
    stored = conn.execute("SELECT token_hash FROM password_reset_tokens").fetchone()[0]  # type: ignore[index]
    assert token not in stored and len(stored) == 64  # only a hash is stored
    login(client, world, "viewer")
    assert client.post(f"{URL}/password/reset", json={"token": token, "new_password": "short"}).status_code == 422
    assert (
        client.post(f"{URL}/password/reset", json={"token": token, "new_password": "password1234"}).status_code == 422
    )
    new = "velvet harbor lantern quarry 7"
    assert client.post(f"{URL}/password/reset", json={"token": token, "new_password": new}).status_code == 200
    assert client.get("/api/v1/assets").status_code == 401  # existing sessions end
    assert (
        client.post(f"{URL}/password/reset", json={"token": token, "new_password": new + "x"}).status_code == 400
    )  # single use
    assert client.post(f"{URL}/login", json={"email": email_of("viewer"), "password": PASSWORD}).status_code == 401
    assert client.post(f"{URL}/login", json={"email": email_of("viewer"), "password": new}).status_code == 200


def test_reset_tokens_expire(client: Any, world: World, mailer: Any, conn: psycopg.Connection[Any]) -> None:
    client.post(f"{URL}/password/forgot", json={"email": email_of("viewer")})
    token = re.search(r"token=([\w-]+)", mailer.sent[0][2]).group(1)  # type: ignore[union-attr]
    conn.execute("UPDATE password_reset_tokens SET expires_at = now() - interval '1 second'")
    conn.commit()
    assert (
        client.post(
            f"{URL}/password/reset", json={"token": token, "new_password": "velvet harbor lantern quarry 7"}
        ).status_code
        == 400
    )
    assert (
        client.post(
            f"{URL}/password/reset", json={"token": "x" * 40, "new_password": "velvet harbor lantern quarry 7"}
        ).status_code
        == 400
    )


def test_forgot_password_is_rate_limited(client: Any, world: World) -> None:
    codes = [client.post(f"{URL}/password/forgot", json={"email": email_of("viewer")}).status_code for _ in range(5)]
    assert codes[:3] == [202, 202, 202] and codes[3:] == [429, 429]


def test_invited_user_sets_a_password_and_signs_in(client: Any, world: World, mailer: Any) -> None:
    login(client, world, "admin")
    created = client.post(
        "/api/v1/admin/users", json={"email": "New.Person@example.org", "display_name": "New Person", "role": "analyst"}
    )
    assert created.status_code == 201 and created.json()["status"] == "invited"
    assert "password" not in created.text.lower()
    token = re.search(r"token=([\w-]+)", mailer.sent[-1][2]).group(1)  # type: ignore[union-attr]
    fresh_client = TestClient(client.app, base_url="https://testserver")
    assert (
        fresh_client.post(f"{URL}/login", json={"email": "new.person@example.org", "password": PASSWORD}).status_code
        == 401
    )
    assert (
        fresh_client.post(
            f"{URL}/password/reset", json={"token": token, "new_password": "orbit canyon velvet lantern 3"}
        ).status_code
        == 200
    )
    assert (
        fresh_client.post(
            f"{URL}/login", json={"email": "new.person@example.org", "password": "orbit canyon velvet lantern 3"}
        ).status_code
        == 200
    )


def test_disabled_users_and_suspended_tenants_lose_access(client: Any, world: World) -> None:
    login(client, world, "analyst")
    admin = TestClient(client.app, base_url="https://testserver")
    login(admin, world, "admin")
    assert admin.patch(f"/api/v1/admin/users/{world.users['analyst']}", json={"status": "disabled"}).status_code == 200
    assert client.get("/api/v1/assets").status_code == 401
    assert client.post(f"{URL}/login", json={"email": email_of("analyst"), "password": PASSWORD}).status_code == 401
    login(client, world, "b_manager")
    platform = TestClient(client.app, base_url="https://testserver")
    login(platform, world, "platform")
    assert (
        platform.patch(f"/api/v1/platform/tenants/{world.tenants['B']}", json={"status": "suspended"}).status_code
        == 200
    )
    assert client.get("/api/v1/assets").status_code == 401
    assert client.post(f"{URL}/login", json={"email": email_of("b_manager"), "password": PASSWORD}).status_code == 401


def test_users_cannot_change_their_own_role(client: Any, world: World) -> None:
    login(client, world, "admin")
    assert client.patch(f"/api/v1/admin/users/{world.users['admin']}", json={"role": "viewer"}).status_code == 409
    assert client.patch(f"/api/v1/admin/users/{world.users['admin']}", json={"status": "disabled"}).status_code == 409


def test_sessions_list_and_sign_out_one(client: Any, app: Any, world: World) -> None:
    login(client, world, "viewer")
    other = fresh(app)
    login(other, world, "viewer")
    sessions = client.get(f"{URL}/sessions").json()["items"]
    assert len(sessions) == 2 and sum(s["current"] for s in sessions) == 1
    victim = next(s for s in sessions if not s["current"])
    assert client.delete(f"{URL}/sessions/{victim['id']}").status_code == 204
    assert other.get("/api/v1/assets").status_code == 401
    assert client.get("/api/v1/assets").status_code == 200
    assert client.delete(f"{URL}/sessions/{victim['id']}").status_code == 404


def test_api_key_lifecycle(client: Any, app: Any, world: World, conn: psycopg.Connection[Any]) -> None:
    login(client, world, "admin")
    created = client.post(
        "/api/v1/admin/api-keys", json={"name": "Reporting", "scopes": ["read"], "expires_in_days": 30}
    ).json()
    key = created["key"]
    assert key.startswith("msk_") and "key" not in client.get("/api/v1/admin/api-keys").json()["items"][0]
    stored = conn.execute("SELECT secret_hash FROM api_keys WHERE id = %s", (created["id"],)).fetchone()[0]  # type: ignore[index]
    assert key.split("_", 2)[2] not in stored
    other = fresh(app)
    assert key_client(other, key).get("/api/v1/assets").status_code == 200
    assert conn.execute("SELECT last_used_at IS NOT NULL FROM api_keys WHERE id = %s", (created["id"],)).fetchone() == (
        True,
    )
    assert other.get("/api/v1/auth/me").json()["kind"] == "api_key"
    assert key_client(fresh(app), key[:-3] + "xyz").get("/api/v1/assets").status_code == 401
    conn.execute("UPDATE api_keys SET expires_at = now() - interval '1 second' WHERE id = %s", (created["id"],))
    conn.commit()
    assert other.get("/api/v1/assets").status_code == 401
    conn.execute("UPDATE api_keys SET expires_at = NULL WHERE id = %s", (created["id"],))
    conn.commit()
    assert other.get("/api/v1/assets").status_code == 200
    assert client.delete(f"/api/v1/admin/api-keys/{created['id']}").status_code == 204
    assert other.get("/api/v1/assets").status_code == 401
    assert client.post("/api/v1/admin/api-keys", json={"name": "bad", "scopes": ["admin"]}).status_code == 422


def test_api_key_rate_limit(client: Any, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MS_RATE_KEY_PER_MINUTE", "3")
    key_client(client, world.keys["A"])
    codes = [client.get("/api/v1/assets").status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]


def test_user_and_ip_rate_limits(client: Any, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MS_RATE_USER_PER_MINUTE", "3")
    login(client, world, "viewer")
    ratelimit._backend.reset()  # type: ignore[attr-defined]
    assert [client.get("/api/v1/assets").status_code for _ in range(5)] == [200, 200, 200, 429, 429]
    monkeypatch.setenv("MS_RATE_USER_PER_MINUTE", "1000")
    monkeypatch.setenv("MS_RATE_IP_PER_MINUTE", "4")
    ratelimit._backend.reset()  # type: ignore[attr-defined]
    codes = [client.get("/api/v1/health").status_code for _ in range(6)]
    assert codes == [200, 200, 200, 200, 429, 429]
    blocked = client.get("/api/v1/health")
    assert blocked.headers["content-type"].startswith("application/problem+json") and blocked.headers["retry-after"]
