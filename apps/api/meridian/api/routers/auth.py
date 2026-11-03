"""Authentication: login with lockout, TOTP MFA, refresh rotation, logout, password reset, sessions."""

from __future__ import annotations

import datetime as dt
import hmac
import secrets
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from meridian.api import db
from meridian.api.auth import CSRF_COOKIE, CSRF_HEADER, REFRESH_COOKIE, Principal, client_ip, get_principal
from meridian.api.errors import ProblemError
from meridian.api.permissions import MFA_REQUIRED_ROLES
from meridian.api.security import audit, crypto, mfa, passwords, ratelimit, tokens
from meridian.api.services import sessions
from meridian.api.services.mailer import Mailer, get_mailer
from meridian.api.settings import get_api_settings

router = APIRouter(prefix="/auth", tags=["auth"])
GENERIC_LOGIN_ERROR = "The email or password is not correct."
MFA_TOKEN_TTL = 300
RESET_TTL = dt.timedelta(minutes=30)


class LoginBody(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+$")
    password: str = Field(min_length=1, max_length=256)

    model_config = {"json_schema_extra": {"example": {"email": "analyst@example.org", "password": "a long passphrase"}}}


class MfaVerifyBody(BaseModel):
    mfa_token: str | None = Field(default=None, max_length=2000)
    setup_token: str | None = Field(default=None, max_length=2000)
    code: str | None = Field(default=None, max_length=16)
    recovery_code: str | None = Field(default=None, max_length=40)


class MfaSetupBody(BaseModel):
    setup_token: str | None = Field(default=None, max_length=2000)


class ForgotBody(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+$")


class ResetBody(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    new_password: str = Field(min_length=1, max_length=256)


def _user_view(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "email": row[1],
        "display_name": row[2],
        "role": row[3],
        "tenant_id": str(row[4]) if row[4] else None,
    }


def _fail(
    conn: Any, request: Request, user_id: str | None, tenant_id: str | None, reason: str, attempts: int | None = None
) -> ProblemError:
    audit.record(
        conn,
        "auth.login_failed",
        tenant_id=tenant_id,
        actor_user_id=user_id,
        ip=client_ip(request),
        request_id=getattr(request.state, "request_id", None),
        detail={"reason": reason},
    )
    conn.commit()
    return ProblemError(401, GENERIC_LOGIN_ERROR, code="invalid-credentials")


def _finish_login(conn: Any, request: Request, response: Response, row: tuple[Any, ...]) -> dict[str, Any]:
    session = sessions.start(conn, str(row[0]), client_ip(request), request.headers.get("user-agent"))
    audit.record(
        conn,
        "auth.login",
        tenant_id=str(row[4]) if row[4] else None,
        actor_user_id=str(row[0]),
        ip=client_ip(request),
        request_id=getattr(request.state, "request_id", None),
    )
    conn.commit()
    sessions.set_cookies(response, session)
    return {"status": "ok", "user": _user_view(row)}


@router.post("/login", summary="Sign in with email and password")
def login(body: LoginBody, request: Request, response: Response) -> dict[str, Any]:
    settings = get_api_settings()
    ip = client_ip(request) or "unknown"
    email = body.email.lower()
    ratelimit.check(f"login-ip:{ip}", settings.login_ip_per_minute, 60, detail="Too many sign-in attempts.")
    ratelimit.check(
        f"login-acct:{tokens.sha256_hex(email)}",
        settings.login_account_per_15min,
        900,
        detail="Too many sign-in attempts.",
    )
    with db.system_connection() as conn:
        row = conn.execute(
            """SELECT u.id, u.email, u.display_name, u.role, u.tenant_id, u.password_hash, u.status, u.failed_login_count, u.locked_until,
                      t.status, (SELECT enabled FROM user_mfa m WHERE m.user_id = u.id)
                 FROM users u LEFT JOIN tenants t ON t.id = u.tenant_id WHERE lower(u.email) = %s""",
            (email,),
        ).fetchone()
        if row is None:
            passwords.dummy_verify(body.password)
            raise _fail(conn, request, None, None, "unknown_account")
        user_id, tenant_id = str(row[0]), str(row[4]) if row[4] else None
        locked = row[8] is not None and row[8] > dt.datetime.now(dt.UTC)
        if locked or row[6] != "active" or (row[9] is not None and row[9] != "active"):
            passwords.dummy_verify(body.password)
            raise _fail(conn, request, user_id, tenant_id, "locked" if locked else "inactive")
        if not passwords.verify_password(row[5], body.password):
            failures = row[7] + 1
            lock = None
            if failures >= settings.lockout_threshold:
                minutes = min(60, 2 ** (failures - settings.lockout_threshold))
                lock = dt.datetime.now(dt.UTC) + dt.timedelta(minutes=minutes)
            conn.execute(
                "UPDATE users SET failed_login_count = %s, locked_until = %s WHERE id = %s", (failures, lock, user_id)
            )
            raise _fail(conn, request, user_id, tenant_id, "bad_password")
        view = row[:5]
        if row[10]:
            return {"status": "mfa_required", "mfa_token": tokens.issue("mfa", user_id, MFA_TOKEN_TTL)}
        if row[3] in MFA_REQUIRED_ROLES:
            return {
                "status": "mfa_enrollment_required",
                "setup_token": tokens.issue("mfa_setup", user_id, MFA_TOKEN_TTL),
            }
        return _finish_login(conn, request, response, view)


def _user_for_token(conn: Any, token: str, typ: str) -> tuple[Any, ...]:
    claims = tokens.decode(token, typ)
    row = None
    if claims:
        row = conn.execute(
            "SELECT id, email, display_name, role, tenant_id FROM users WHERE id = %s AND status = 'active'",
            (claims["sub"],),
        ).fetchone()
    if row is None:
        raise ProblemError(401, "The sign-in step has expired. Start again.", code="mfa-expired")
    result: tuple[Any, ...] = row
    return result


def _setup_secret(conn: Any, user: tuple[Any, ...]) -> dict[str, Any]:
    secret = mfa.new_secret()
    conn.execute(
        """INSERT INTO user_mfa (user_id, totp_secret_encrypted, enabled) VALUES (%s, %s, false)
           ON CONFLICT (user_id) DO UPDATE SET totp_secret_encrypted = EXCLUDED.totp_secret_encrypted
           WHERE user_mfa.enabled = false""",
        (user[0], crypto.encrypt(secret)),
    )
    uri = mfa.provisioning_uri(secret, user[1])
    return {"secret": secret, "otpauth_uri": uri, "qr_svg": mfa.qr_svg(uri)}


@router.post("/mfa/setup", summary="Start TOTP enrollment")
def mfa_setup(body: MfaSetupBody, request: Request) -> dict[str, Any]:
    with db.system_connection() as conn:
        if body.setup_token:
            user = _user_for_token(conn, body.setup_token, "mfa_setup")
        else:
            principal = get_principal(request)
            if principal.user_id is None:
                raise ProblemError(403, "API keys cannot enroll MFA.", code="forbidden")
            user = conn.execute(
                "SELECT id, email, display_name, role, tenant_id FROM users WHERE id = %s", (principal.user_id,)
            ).fetchone()  # type: ignore[assignment]
        enabled = conn.execute("SELECT enabled FROM user_mfa WHERE user_id = %s", (user[0],)).fetchone()
        if enabled and enabled[0]:
            raise ProblemError(409, "MFA is already enabled for this account.", code="mfa-enabled")
        result = _setup_secret(conn, user)
        conn.commit()
        return result


@router.post("/mfa/verify", summary="Complete sign-in or enrollment with a TOTP code or recovery code")
def mfa_verify(body: MfaVerifyBody, request: Request, response: Response) -> dict[str, Any]:
    token, typ = (body.mfa_token, "mfa") if body.mfa_token else (body.setup_token, "mfa_setup")
    with db.system_connection() as conn:
        if token:
            user = _user_for_token(conn, token, typ)
            enrolling = typ == "mfa_setup"
        else:
            principal = get_principal(request)
            if principal.user_id is None:
                raise ProblemError(403, "API keys cannot enroll MFA.", code="forbidden")
            user = conn.execute(
                "SELECT id, email, display_name, role, tenant_id FROM users WHERE id = %s", (principal.user_id,)
            ).fetchone()  # type: ignore[assignment]
            enrolling = True
        user_id = str(user[0])
        ratelimit.check(f"mfa:{user_id}", 10, 300, detail="Too many verification attempts.")
        record = conn.execute(
            "SELECT totp_secret_encrypted, enabled, recovery_code_hashes FROM user_mfa WHERE user_id = %s FOR UPDATE",
            (user_id,),
        ).fetchone()
        if record is None or (enrolling and record[1] and typ == "mfa_setup"):
            raise ProblemError(409, "MFA enrollment has not been started.", code="mfa-not-started")
        accepted = False
        if body.code:
            step = mfa.verify_code(crypto.decrypt(record[0]), body.code)
            accepted = step is not None and ratelimit.backend().once(f"totp:{user_id}:{step}", 120)
        elif body.recovery_code and record[1]:
            digest = mfa.hash_recovery_code(body.recovery_code)
            hashes = list(record[2])
            if any(hmac.compare_digest(digest, h) for h in hashes):
                hashes = [h for h in hashes if not hmac.compare_digest(digest, h)]
                conn.execute("UPDATE user_mfa SET recovery_code_hashes = %s WHERE user_id = %s", (hashes, user_id))
                accepted = True
        if not accepted:
            audit.record(
                conn,
                "auth.mfa_failed",
                tenant_id=str(user[4]) if user[4] else None,
                actor_user_id=user_id,
                ip=client_ip(request),
                request_id=getattr(request.state, "request_id", None),
            )
            conn.commit()
            raise ProblemError(401, "The code is not correct.", code="invalid-code")
        result: dict[str, Any] = {}
        if not record[1]:
            codes = mfa.new_recovery_codes()
            conn.execute(
                "UPDATE user_mfa SET enabled = true, enrolled_at = now(), recovery_code_hashes = %s WHERE user_id = %s",
                ([mfa.hash_recovery_code(c) for c in codes], user_id),
            )
            audit.record(
                conn,
                "auth.mfa_enabled",
                tenant_id=str(user[4]) if user[4] else None,
                actor_user_id=user_id,
                ip=client_ip(request),
                request_id=getattr(request.state, "request_id", None),
            )
            result["recovery_codes"] = codes
        if token:
            result.update(_finish_login(conn, request, response, user))
        else:
            conn.commit()
            result["status"] = "ok"
        return result


def _check_csrf(request: Request) -> None:
    header, cookie = request.headers.get(CSRF_HEADER, ""), request.cookies.get(CSRF_COOKIE, "")
    if not header or not hmac.compare_digest(header, cookie):
        raise ProblemError(403, "The CSRF token is missing or does not match.", code="csrf")


@router.post("/refresh", summary="Rotate the refresh token and issue a new access token")
def refresh(request: Request, response: Response) -> dict[str, Any]:
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise ProblemError(401, "The session is no longer valid. Sign in again.", code="session-invalid")
    _check_csrf(request)
    with db.system_connection() as conn:
        try:
            session = sessions.rotate(
                conn,
                raw,
                client_ip(request),
                request.headers.get("user-agent"),
                getattr(request.state, "request_id", None),
            )
        except ProblemError:
            sessions.clear_cookies(response)
            raise
        conn.commit()
    session.csrf = request.cookies.get(CSRF_COOKIE, session.csrf)  # already checked; keeps the web app's header valid
    sessions.set_cookies(response, session)
    return {"status": "ok"}


@router.post("/logout", summary="End the current session", status_code=204)
def logout(request: Request, response: Response) -> Response:
    raw = request.cookies.get(REFRESH_COOKIE)
    access = request.cookies.get("ms_access")
    if access:
        _check_csrf(request)
    with db.system_connection() as conn:
        family = None
        if raw:
            row = conn.execute(
                "SELECT family_id, user_id FROM refresh_tokens WHERE token_hash = %s", (tokens.sha256_hex(raw),)
            ).fetchone()
            if row:
                family = str(row[0])
        if family is None and access:
            claims = tokens.decode(access, "access")
            family = str(claims["sid"]) if claims and claims.get("sid") else None
        if family:
            sessions.revoke_family(conn, family)
            conn.commit()
    out = Response(status_code=204)
    sessions.clear_cookies(out)
    return out


@router.post("/password/forgot", summary="Request a password reset email", status_code=202)
def forgot(body: ForgotBody, request: Request, mailer: Mailer = Depends(get_mailer)) -> dict[str, str]:
    email = body.email.lower()
    ratelimit.check(f"forgot-ip:{client_ip(request) or 'unknown'}", 10, 3600)
    ratelimit.check(f"forgot-acct:{tokens.sha256_hex(email)}", 3, 3600)
    with db.system_connection() as conn:
        row = conn.execute(
            "SELECT id, tenant_id FROM users WHERE lower(email) = %s AND status = 'active'", (email,)
        ).fetchone()
        if row:
            raw = secrets.token_urlsafe(32)
            conn.execute(
                "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) VALUES (%s, %s, %s)",
                (row[0], tokens.sha256_hex(raw), dt.datetime.now(dt.UTC) + RESET_TTL),
            )
            audit.record(
                conn,
                "auth.password_reset_requested",
                tenant_id=str(row[1]) if row[1] else None,
                actor_user_id=str(row[0]),
                ip=client_ip(request),
                request_id=getattr(request.state, "request_id", None),
            )
            conn.commit()
            link = f"{get_api_settings().public_url}/reset-password?token={raw}"
            mailer.send(
                email,
                "Reset your password",
                f"Use this link within 30 minutes to choose a new password:\n{link}\nIf you did not request this, ignore this message.",
            )
    # The answer is the same whether or not the account exists.
    return {"status": "If the account exists, a reset message has been sent."}


@router.post("/password/reset", summary="Choose a new password with a reset token")
def reset(body: ResetBody, request: Request) -> dict[str, str]:
    with db.system_connection() as conn:
        row = conn.execute(
            """SELECT t.id, t.user_id, u.email, u.display_name, u.tenant_id FROM password_reset_tokens t JOIN users u ON u.id = t.user_id
                WHERE t.token_hash = %s AND t.used_at IS NULL AND t.expires_at > now() AND u.status IN ('active', 'invited') FOR UPDATE OF t""",
            (tokens.sha256_hex(body.token),),
        ).fetchone()
        if row is None:
            raise ProblemError(400, "The reset link is not valid or has expired.", code="invalid-token")
        try:
            passwords.validate_password(body.new_password, [row[2], row[3], row[2].split("@")[0]])
        except passwords.PasswordPolicyError as exc:
            raise ProblemError(422, str(exc), code="weak-password") from exc
        conn.execute("UPDATE password_reset_tokens SET used_at = now() WHERE id = %s", (row[0],))
        conn.execute(
            "UPDATE users SET password_hash = %s, password_changed_at = now(), failed_login_count = 0, locked_until = NULL, status = 'active' WHERE id = %s",
            (passwords.hash_password(body.new_password), row[1]),
        )
        sessions.revoke_user(conn, str(row[1]))
        audit.record(
            conn,
            "auth.password_reset",
            tenant_id=str(row[4]) if row[4] else None,
            actor_user_id=str(row[1]),
            ip=client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )
        conn.commit()
    return {"status": "The password was changed. Sign in with the new password."}


@router.get("/me", summary="The current user or API key")
def me(principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    out: dict[str, Any] = {
        "kind": principal.kind,
        "role": principal.role,
        "tenant_id": principal.tenant_id,
        "permissions": sorted(principal.permissions),
    }
    if principal.user_id:
        with db.system_connection() as conn:
            row = conn.execute(
                "SELECT email, display_name, (SELECT enabled FROM user_mfa m WHERE m.user_id = u.id), notify_email FROM users u WHERE id = %s",
                (principal.user_id,),
            ).fetchone()
        if row:
            out.update(
                {
                    "id": principal.user_id,
                    "email": row[0],
                    "display_name": row[1],
                    "mfa_enabled": bool(row[2]),
                    "notifications": {"email": bool(row[3])},
                }
            )
    else:
        out.update({"api_key_id": principal.api_key_id, "scopes": principal.scopes})
    return out


class NotificationPrefs(BaseModel):
    email: bool


@router.patch("/me/notifications", summary="Turn alert email on or off for the current user")
def set_notifications(
    body: NotificationPrefs, request: Request, principal: Principal = Depends(get_principal)
) -> dict[str, Any]:
    if principal.user_id is None:
        raise ProblemError(403, "API keys have no notification settings.", code="forbidden")
    with db.system_connection() as conn:
        conn.execute("UPDATE users SET notify_email = %s WHERE id = %s", (body.email, principal.user_id))
        conn.commit()
    return {"notifications": {"email": body.email}}


@router.get("/sessions", summary="Active sessions of the current user")
def list_sessions(principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    if principal.user_id is None:
        raise ProblemError(403, "API keys have no sessions.", code="forbidden")
    with db.system_connection() as conn:
        rows = conn.execute(
            """SELECT family_id, min(issued_at), max(issued_at), max(user_agent), max(ip::text), max(absolute_expires_at)
                 FROM refresh_tokens WHERE user_id = %s AND revoked_at IS NULL AND absolute_expires_at > now() GROUP BY family_id ORDER BY 3 DESC""",
            (principal.user_id,),
        ).fetchall()
    return {
        "items": [
            {
                "id": str(r[0]),
                "started_at": r[1],
                "last_active_at": r[2],
                "user_agent": r[3],
                "ip": r[4],
                "expires_at": r[5],
                "current": str(r[0]) == principal.session_id,
            }
            for r in rows
        ]
    }


@router.delete("/sessions/{session_id}", summary="Sign out one session", status_code=204)
def end_session(session_id: str, principal: Principal = Depends(get_principal)) -> Response:
    if principal.user_id is None:
        raise ProblemError(403, "API keys have no sessions.", code="forbidden")
    with db.system_connection() as conn:
        done = conn.execute(
            "UPDATE refresh_tokens SET revoked_at = now() WHERE family_id::text = %s AND user_id = %s AND revoked_at IS NULL",
            (session_id, principal.user_id),
        )
        conn.commit()
    if done.rowcount == 0:
        raise ProblemError(404, "Session not found.", code="not-found")
    return Response(status_code=204)
