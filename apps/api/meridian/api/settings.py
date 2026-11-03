"""API settings from the environment. Secrets are never committed: development keys are generated into .local/secrets."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from meridian.config import REPO_ROOT

SECRET_DIR = REPO_ROOT / ".local" / "secrets"


def _flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _dev_secret(name: str, make: bytes) -> bytes:
    path = SECRET_DIR / name
    if path.exists():
        return path.read_bytes()
    SECRET_DIR.mkdir(parents=True, exist_ok=True)
    path.write_bytes(make)
    path.chmod(0o600)
    return make


@dataclass(frozen=True)
class ApiSettings:
    env: str
    fernet_key: bytes
    jwt_private_pem: bytes
    access_ttl_seconds: int
    refresh_idle_seconds: int
    refresh_absolute_seconds: int
    cookie_secure: bool
    trust_proxy: bool
    valkey_url: str | None
    max_body_bytes: int
    max_upload_bytes: int
    max_upload_rows: int
    max_vertices: int
    rate_ip_per_minute: int
    rate_user_per_minute: int
    rate_key_per_minute: int
    login_ip_per_minute: int
    login_account_per_15min: int
    lockout_threshold: int
    sse_connections_per_tenant: int
    argon2_fast: bool
    docs_enabled: bool
    smtp_host: str
    smtp_port: int
    mail_from: str
    public_url: str

    @property
    def production(self) -> bool:
        return self.env == "production"


def get_api_settings() -> ApiSettings:
    env = os.environ.get("MS_ENV", "development").strip().lower()
    fernet = os.environ.get("MS_SECRET_KEY", "").strip().encode()
    private = os.environ.get("MS_JWT_PRIVATE_KEY", "").replace("\\n", "\n").encode()
    if not fernet or not private:
        if env == "production":
            raise RuntimeError("MS_SECRET_KEY and MS_JWT_PRIVATE_KEY are required in production")
        fernet = fernet or _dev_secret("fernet.key", Fernet.generate_key())
        private = private or _dev_secret(
            "jwt_ed25519.pem",
            Ed25519PrivateKey.generate().private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            ),
        )
    return ApiSettings(
        env=env,
        fernet_key=fernet,
        jwt_private_pem=private,
        access_ttl_seconds=_int("MS_ACCESS_TTL_SECONDS", 15 * 60),
        refresh_idle_seconds=_int("MS_REFRESH_IDLE_SECONDS", 8 * 3600),
        refresh_absolute_seconds=_int("MS_REFRESH_ABSOLUTE_SECONDS", 7 * 86400),
        cookie_secure=_flag("MS_COOKIE_SECURE", env != "development"),
        trust_proxy=_flag("MS_TRUST_PROXY", False),
        valkey_url=os.environ.get("MS_VALKEY_URL") or None,
        max_body_bytes=_int("MS_MAX_BODY_BYTES", 1_000_000),
        max_upload_bytes=_int("MS_MAX_UPLOAD_BYTES", 5_000_000),
        max_upload_rows=_int("MS_MAX_UPLOAD_ROWS", 5000),
        max_vertices=_int("MS_MAX_VERTICES", 50_000),
        rate_ip_per_minute=_int("MS_RATE_IP_PER_MINUTE", 300),
        rate_user_per_minute=_int("MS_RATE_USER_PER_MINUTE", 600),
        rate_key_per_minute=_int("MS_RATE_KEY_PER_MINUTE", 120),
        login_ip_per_minute=_int("MS_LOGIN_IP_PER_MINUTE", 20),
        login_account_per_15min=_int("MS_LOGIN_ACCOUNT_PER_15MIN", 10),
        lockout_threshold=_int("MS_LOCKOUT_THRESHOLD", 5),
        sse_connections_per_tenant=_int("MS_SSE_CONNECTIONS_PER_TENANT", 20),
        argon2_fast=_flag("MS_ARGON2_FAST", False),
        docs_enabled=_flag("MS_DOCS_ENABLED", env != "production"),
        smtp_host=os.environ.get("MS_SMTP_HOST", "localhost"),
        smtp_port=_int("MS_SMTP_PORT", 1025),
        mail_from=os.environ.get("MS_MAIL_FROM", "no-reply@meridian.invalid"),
        public_url=os.environ.get("MS_PUBLIC_URL", "http://localhost:3000"),
    )


def secret_path() -> Path:
    return SECRET_DIR
