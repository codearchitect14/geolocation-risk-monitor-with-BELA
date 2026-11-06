"""Demonstration data: one illustrative tenant with sign-in accounts and assets placed near recent incidents.

python -m meridian.demo seed [--rotate] [--assets 120]

Account passwords are generated here, printed once, and stored only as Argon2id hashes. Running the command again
does not change or reveal them; `--rotate` issues new ones. The public demonstration uses the read-only viewer
account. Every asset is labeled illustrative; nothing here is customer data.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import secrets
import string
import sys
from typing import Any

import psycopg

from meridian.api import db
from meridian.api.security import audit, passwords
from meridian.events import service
from meridian.events.config import load_events_config

TENANT_SLUG = "demo"
TENANT_NAME = "Illustrative demo tenant (synthetic data)"
DOMAIN = "example.com"
ACCOUNTS = (
    ("viewer", "Demo viewer (read only)", "viewer", True),
    ("analyst", "Demo analyst", "analyst", True),
    ("manager", "Demo manager", "manager", True),
    ("admin", "Demo tenant administrator", "tenant_admin", True),
    ("platform", "Demo platform administrator", "platform_admin", False),
    ("finance", "Demo finance analyst", "finance_analyst", False),
)  # (local part, display name, role, belongs to the tenant)
KINDS = ("site", "site", "site")
LABELS = ("Plant", "Warehouse", "Terminal", "Office", "Depot", "Port facility")
ALPHABET = string.ascii_lowercase + string.digits


def email_for(local: str) -> str:
    return f"demo-{local}@{DOMAIN}"


def generate_password() -> str:
    """Five groups of four random characters: about 100 bits, accepted by the password policy."""
    return "-".join("".join(secrets.choice(ALPHABET) for _ in range(4)) for _ in range(5))


def seed_accounts(conn: psycopg.Connection[Any], rotate: bool = False) -> dict[str, str]:
    """Create the tenant and accounts. Returns the plain passwords issued now (empty when nothing changed)."""
    row = conn.execute(
        """INSERT INTO tenants (name, slug, industry, is_demo) VALUES (%s, %s, 'illustrative', true)
           ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name RETURNING id""",
        (TENANT_NAME, TENANT_SLUG),
    ).fetchone()
    assert row is not None
    tenant_id = row[0]
    issued: dict[str, str] = {}
    for local, display, role, in_tenant in ACCOUNTS:
        email = email_for(local)
        existing = conn.execute("SELECT id FROM users WHERE lower(email) = %s", (email,)).fetchone()
        if existing is not None and not rotate:
            continue
        password = generate_password()
        passwords.validate_password(password, [email, local])
        hashed = passwords.hash_password(password)
        if existing is None:
            conn.execute(
                "INSERT INTO users (tenant_id, email, display_name, password_hash, role) VALUES (%s, %s, %s, %s, %s)",
                (tenant_id if in_tenant else None, email, display, hashed, role),
            )
        else:
            conn.execute(
                "UPDATE users SET password_hash = %s, failed_login_count = 0, locked_until = NULL WHERE id = %s",
                (hashed, existing[0]),
            )
        issued[email] = password
    audit.record(conn, "demo.seed", tenant_id=str(tenant_id), actor_type="system", detail={"issued": len(issued)})
    conn.commit()
    return issued


def seed_assets(conn: psycopg.Connection[Any], count: int, seed: int = 11) -> int:
    """Illustrative assets: half within about 20 km of the most severe incidents (alerts), the rest in cities."""
    tenant = conn.execute("SELECT id FROM tenants WHERE slug = %s", (TENANT_SLUG,)).fetchone()
    assert tenant is not None
    if conn.execute("SELECT count(*) FROM assets WHERE tenant_id = %s", (tenant[0],)).fetchone() != (0,):
        return 0
    rng = random.Random(seed)  # noqa: S311 - synthetic placement
    near = conn.execute(
        """SELECT ST_Y(ST_PointOnSurface(geom)), ST_X(ST_PointOnSurface(geom)) FROM events
            WHERE geom IS NOT NULL ORDER BY severity DESC, last_seen_at DESC LIMIT 30"""
    ).fetchall()
    cities = conn.execute(
        """SELECT lat, lon, country_code FROM places WHERE type IN ('city', 'town') AND population >= 200000
              AND lat IS NOT NULL ORDER BY id"""
    ).fetchall()
    rows: list[tuple[float, float, str | None]] = []
    for i in range(count):
        if near and i % 2 == 0:
            lat, lon = rng.choice(near)
            rows.append((lat + rng.uniform(-0.15, 0.15), lon + rng.uniform(-0.2, 0.2), None))
        elif cities:
            lat, lon, cc = rng.choice(cities)
            rows.append((lat + rng.uniform(-0.2, 0.2), lon + rng.uniform(-0.3, 0.3), cc))
    with conn.cursor().copy(
        "COPY assets (tenant_id, name, type, geom, criticality, country_code, tags, external_id) FROM STDIN"
    ) as copy:
        for i, (lat, lon, cc) in enumerate(rows, 1):
            label = rng.choice(LABELS)
            copy.write_row(
                (
                    tenant[0],
                    f"{label} {i:03d} (illustrative)",
                    "site",
                    f"SRID=4326;POINT({max(-179.0, min(179.0, lon)):.5f} {max(-85.0, min(85.0, lat)):.5f})",
                    rng.randint(1, 5),
                    cc,
                    "{illustrative}",
                    f"DEMO-{i:03d}",
                )
            )
    conn.commit()
    return len(rows)


def refresh_exposures(conn: psycopg.Connection[Any]) -> dict[str, int]:
    """Exposure and alert evaluation for the incidents that exist now."""
    cfg = load_events_config()
    now = dt.datetime.now(dt.UTC)
    ids = [str(r[0]) for r in conn.execute("SELECT id FROM events WHERE status <> 'closed'").fetchall()]
    alerts = 0
    for event_id in ids:
        result = service.process_event(conn, cfg, event_id, now)
        alerts += result.created
    conn.commit()
    return {"events": len(ids), "alerts_created": alerts}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m meridian.demo")
    sub = parser.add_subparsers(dest="command", required=True)
    seed = sub.add_parser("seed")
    seed.add_argument("--rotate", action="store_true", help="issue new passwords for the existing demo accounts")
    seed.add_argument("--assets", type=int, default=120)
    seed.add_argument("--accounts-only", action="store_true")
    args = parser.parse_args(argv)
    with db.system_connection() as conn:
        issued = seed_accounts(conn, rotate=args.rotate)
        result: dict[str, Any] = {"accounts_issued": len(issued)}
        if not args.accounts_only:
            result["assets_created"] = seed_assets(conn, args.assets)
            result.update(refresh_exposures(conn))
    db.close_pools()
    print(json.dumps(result), file=sys.stderr)
    if issued:
        print("Demo sign-in details (shown once; stored only as hashes):")
        for email, password in issued.items():
            print(f"  {email}  {password}")
        print("Tenant administrator and platform accounts ask for an authenticator app (TOTP) at first sign-in.")
        print("The public demonstration should publish only the read only viewer account.")
    else:
        print(
            "Demo accounts already exist; passwords are not shown again. Use --rotate to issue new ones.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
