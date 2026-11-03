"""Fixtures for API tests: a seeded two tenant world, login helpers, and fakes for mail and place linking."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import psycopg
import pyotp
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from meridian.api.security import crypto, mfa, passwords
from meridian.api.security.tokens import sha256_hex
from meridian.api.services import apikeys

PASSWORD = "correct horse battery staple 42"
NOW = dt.datetime.now(dt.UTC)

ENV = {
    "MS_ENV": "test",
    "MS_ARGON2_FAST": "1",
    "MS_COOKIE_SECURE": "true",
    "MS_SECRET_KEY": Fernet.generate_key().decode(),
    "MS_JWT_PRIVATE_KEY": Ed25519PrivateKey.generate()
    .private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    .decode()
    .replace("\n", "\\n"),
    "MS_RATE_IP_PER_MINUTE": "100000",
    "MS_RATE_USER_PER_MINUTE": "100000",
    "MS_LOGIN_IP_PER_MINUTE": "100000",
    "MS_LOGIN_ACCOUNT_PER_15MIN": "100000",
    "MS_DOCS_ENABLED": "true",
}

ROLES = {
    "viewer": ("A", "viewer"),
    "analyst": ("A", "analyst"),
    "manager": ("A", "manager"),
    "admin": ("A", "tenant_admin"),
    "b_manager": ("B", "manager"),
    "b_admin": ("B", "tenant_admin"),
    "finance": (None, "finance_analyst"),
    "platform": (None, "platform_admin"),
}


class World:
    """Ids and secrets created for one test."""

    def __init__(self) -> None:
        self.tenants: dict[str, str] = {}
        self.users: dict[str, str] = {}
        self.totp: dict[str, str] = {}
        self.assets: dict[str, str] = {}
        self.zones: dict[str, str] = {}
        self.rules: dict[str, str] = {}
        self.alerts: dict[str, str] = {}
        self.events: dict[str, str] = {}
        self.keys: dict[str, str] = {}
        self.key_ids: dict[str, str] = {}
        self.hooks: dict[str, str] = {}
        self.groups: dict[str, str] = {}
        self.uploads: dict[str, str] = {}
        self.briefings: dict[str, str] = {}
        self.reports: dict[str, str] = {}


def email_of(name: str) -> str:
    return f"{name}@example.org"


def build_world(conn: psycopg.Connection[Any]) -> World:
    w = World()
    with conn.cursor() as cur:
        cur.execute("TRUNCATE tenants, users, events, plans, places, platform_stats_daily, marketing_spend, business_events CASCADE")
        cur.execute(
            "INSERT INTO plans (id, name, monthly_price, asset_limit) VALUES ('standard', 'Standard', 900, 100)"
        )
        for key in ("A", "B"):
            cur.execute(
                "INSERT INTO tenants (name, slug, is_demo) VALUES (%s, %s, true) RETURNING id",
                (f"Tenant {key}", f"tenant-{key.lower()}"),
            )
            w.tenants[key] = str(cur.fetchone()[0])  # type: ignore[index]
        hashed = passwords.hash_password(PASSWORD)
        for name, (tenant_key, role) in ROLES.items():
            tenant = w.tenants[tenant_key] if tenant_key else None
            cur.execute(
                "INSERT INTO users (tenant_id, email, display_name, password_hash, role) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (tenant, email_of(name), name.title(), hashed, role),
            )
            w.users[name] = str(cur.fetchone()[0])  # type: ignore[index]
            if role in ("tenant_admin", "platform_admin"):
                secret = mfa.new_secret()
                w.totp[name] = secret
                cur.execute(
                    "INSERT INTO user_mfa (user_id, totp_secret_encrypted, enabled, enrolled_at, recovery_code_hashes) VALUES (%s, %s, true, now(), %s)",
                    (w.users[name], crypto.encrypt(secret), [mfa.hash_recovery_code("AAAA-BBBB-CCCC-DDDD")]),
                )
        # Global data: places and events near each tenant's assets.
        cur.execute(
            """INSERT INTO places (id, qid, name, name_normalized, type, country_code, population, lat, lon, centroid, geom, source, uncertainty_km, location_level)
               OVERRIDING SYSTEM VALUE VALUES (1, 'Q1', 'Springfield', 'springfield', 'city', 'US', 116250, 39.80, -89.64,
                   ST_SetSRID(ST_MakePoint(-89.64, 39.80), 4326), ST_SetSRID(ST_MakePoint(-89.64, 39.80), 4326), 'wikidata', 25, 'city')"""
        )
        for key, (lat, lon) in {"A": (39.80, -89.64), "B": (37.22, -93.30)}.items():
            cur.execute(
                """INSERT INTO events (type, subtype, severity, status, confirmation, first_seen_at, last_seen_at, occurred_at, title, summary, geom,
                                       uncertainty_km, location_level, location_confidence, reliability)
                   VALUES ('industrial_accident', 'fire', 3, 'new', 'unconfirmed', now(), now(), now(), %s, 'Test summary',
                           ST_SetSRID(ST_MakePoint(%s, %s), 4326), 25, 'city', 0.8, 0.6) RETURNING id""",
                (f"Fire near {key}", lon, lat),
            )
            w.events[key] = str(cur.fetchone()[0])  # type: ignore[index]
            cur.execute(
                "INSERT INTO event_sources (event_id, source_kind, url, published_at, source_ref, snippet, reliability) VALUES (%s, 'news', %s, now(), %s, 'A fire was reported.', 0.6)",
                (w.events[key], f"https://news.example/{key}", f"ref-{key}"),
            )
            # Tenant data: one asset near its event, one far away, a zone, a rule, an exposure, an alert, an API key.
            tenant = w.tenants[key]
            for label, dlat in (("near", 0.0), ("far", 5.0)):
                cur.execute(
                    "INSERT INTO assets (tenant_id, name, type, geom, criticality, country_code) VALUES (%s, %s, 'site', ST_SetSRID(ST_MakePoint(%s, %s), 4326), 4, 'US') RETURNING id",
                    (tenant, f"{key} {label}", lon + 0.01, lat + dlat),
                )
                w.assets[f"{key}_{label}"] = str(cur.fetchone()[0])  # type: ignore[index]
            cur.execute(
                "INSERT INTO watch_zones (tenant_id, name, geom, rules) VALUES (%s, %s, ST_GeomFromText('POLYGON((-100 30, -80 30, -80 45, -100 45, -100 30))', 4326), '{}') RETURNING id",
                (tenant, f"Zone {key}"),
            )
            w.zones[key] = str(cur.fetchone()[0])  # type: ignore[index]
            cur.execute(
                "INSERT INTO alert_rules (tenant_id, name, min_level) VALUES (%s, %s, 'low') RETURNING id",
                (tenant, f"Rule {key}"),
            )
            w.rules[key] = str(cur.fetchone()[0])  # type: ignore[index]
            cur.execute(
                """INSERT INTO exposures (tenant_id, event_id, asset_id, distance_km, within_uncertainty, score, level, components, config_version)
                   VALUES (%s, %s, %s, 1.2, true, 0.55, 'high', %s, 'events_config_v1')""",
                (tenant, w.events[key], w.assets[f"{key}_near"], json.dumps({"type_weight": 1.0, "proximity": 1.0})),
            )
            cur.execute(
                "INSERT INTO alerts (tenant_id, event_id, asset_id, level, last_score) VALUES (%s, %s, %s, 'high', 0.55) RETURNING id",
                (tenant, w.events[key], w.assets[f"{key}_near"]),
            )
            w.alerts[key] = str(cur.fetchone()[0])  # type: ignore[index]
            cur.execute(
                "INSERT INTO asset_groups (tenant_id, name) VALUES (%s, %s) RETURNING id", (tenant, f"Group {key}")
            )
            w.groups[key] = str(cur.fetchone()[0])  # type: ignore[index]
            full, prefix, digest = apikeys.generate()
            cur.execute(
                "INSERT INTO api_keys (tenant_id, name, prefix, secret_hash, scopes) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (tenant, f"Key {key}", prefix, digest, ["read", "alerts"]),
            )
            w.key_ids[key] = str(cur.fetchone()[0])  # type: ignore[index]
            w.keys[key] = full
            cur.execute(
                "INSERT INTO webhooks (tenant_id, name, url, secret_encrypted) VALUES (%s, %s, 'https://hooks.example.org/in', %s) RETURNING id",
                (tenant, f"Hook {key}", crypto.encrypt("whsec_test")),
            )
            w.hooks[key] = str(cur.fetchone()[0])  # type: ignore[index]
            cur.execute(
                "INSERT INTO uploads (tenant_id, filename, kind, size_bytes) VALUES (%s, 'a.csv', 'csv', 10) RETURNING id",
                (tenant,),
            )
            w.uploads[key] = str(cur.fetchone()[0])  # type: ignore[index]
            cur.execute(
                "INSERT INTO briefings (tenant_id, kind, period_start, period_end, narrative) VALUES (%s, 'daily', now() - interval '1 day', now(), 'x') RETURNING id",
                (tenant,),
            )
            w.briefings[key] = str(cur.fetchone()[0])  # type: ignore[index]
            cur.execute(
                "INSERT INTO reports (tenant_id, kind, status) VALUES (%s, 'portfolio', 'pending') RETURNING id",
                (tenant,),
            )
            w.reports[key] = str(cur.fetchone()[0])  # type: ignore[index]
            cur.execute(
                "INSERT INTO subscriptions (tenant_id, plan_id, billing_cycle, price, start_date) VALUES (%s, 'standard', 'monthly', 900, current_date - 90)",
                (tenant,),
            )
            cur.execute(
                "INSERT INTO invoices (tenant_id, period_start, period_end, status, total, issued_at, due_at) VALUES (%s, current_date - 60, current_date - 30, 'paid', 900, current_date - 59, current_date - 45)",
                (tenant,),
            )
    conn.commit()
    conn.execute("SELECT refresh_metrics()")
    conn.commit()
    return w


def totp_now(secret: str) -> str:
    return pyotp.TOTP(secret).now()


def login(client: TestClient, world: World, name: str) -> TestClient:
    """Sign in as a seeded user, completing MFA for administrators, and set the CSRF header."""
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    response = client.post("/api/v1/auth/login", json={"email": email_of(name), "password": PASSWORD})
    assert response.status_code == 200, response.text
    body = response.json()
    if body["status"] == "mfa_required":
        _forget_used_codes()
        code = pyotp.TOTP(world.totp[name]).now()
        response = client.post("/api/v1/auth/mfa/verify", json={"mfa_token": body["mfa_token"], "code": code})
        assert response.status_code == 200, response.text
    csrf = client.cookies.get("ms_csrf")
    assert csrf
    client.headers["X-CSRF-Token"] = csrf
    return client


def _forget_used_codes() -> None:
    """TOTP codes are single use; tests sign in repeatedly within one time step, so clear the replay cache."""
    from meridian.api.security import ratelimit

    ratelimit._backend.reset()  # type: ignore[attr-defined]


def key_client(client: TestClient, key: str) -> TestClient:
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    client.headers["Authorization"] = f"Bearer {key}"
    return client


_ = sha256_hex
