"""Bootstrap commands: python -m meridian.api.cli create-user ..., create-tenant ..., migrate-check.

Passwords are read from the MS_NEW_PASSWORD environment variable or an interactive prompt, never from arguments, so they do not
appear in process listings or shell history.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import sys

from meridian.api import db
from meridian.api.permissions import ROLES
from meridian.api.security import audit, passwords


def _password(email: str) -> str:
    value = os.environ.get("MS_NEW_PASSWORD") or getpass.getpass("Password: ")
    passwords.validate_password(value, [email, email.split("@")[0]])
    return value


def create_tenant(name: str, demo: bool) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:50]
    with db.system_connection() as conn:
        row = conn.execute(
            "INSERT INTO tenants (name, slug, is_demo) VALUES (%s, %s, %s) ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name RETURNING id",
            (name, slug, demo),
        ).fetchone()
        assert row is not None
        audit.record(
            conn,
            "cli.tenant_create",
            tenant_id=str(row[0]),
            actor_type="system",
            object_type="tenant",
            object_id=str(row[0]),
        )
        conn.commit()
        return str(row[0])


def create_user(email: str, name: str, role: str, tenant_slug: str | None) -> str:
    platform_role = role in ("platform_admin", "finance_analyst")
    if platform_role == bool(tenant_slug):
        raise SystemExit("Platform roles take no tenant; tenant roles need --tenant.")
    hashed = passwords.hash_password(_password(email))
    with db.system_connection() as conn:
        tenant_id = None
        if tenant_slug:
            found = conn.execute("SELECT id FROM tenants WHERE slug = %s", (tenant_slug,)).fetchone()
            if found is None:
                raise SystemExit(f"No tenant with slug {tenant_slug!r}.")
            tenant_id = found[0]
        row = conn.execute(
            "INSERT INTO users (tenant_id, email, display_name, password_hash, role) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (tenant_id, email.lower(), name, hashed, role),
        ).fetchone()
        assert row is not None
        audit.record(
            conn,
            "cli.user_create",
            tenant_id=str(tenant_id) if tenant_id else None,
            actor_type="system",
            object_type="user",
            object_id=str(row[0]),
            detail={"role": role},
        )
        conn.commit()
        return str(row[0])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m meridian.api.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    tenant = sub.add_parser("create-tenant")
    tenant.add_argument("--name", required=True)
    tenant.add_argument("--real", action="store_true", help="mark the tenant as not demo data")
    user = sub.add_parser("create-user")
    user.add_argument("--email", required=True)
    user.add_argument("--name", required=True)
    user.add_argument("--role", required=True, choices=ROLES)
    user.add_argument("--tenant", help="tenant slug (tenant roles only)")
    args = parser.parse_args(argv)
    if args.command == "create-tenant":
        print(create_tenant(args.name, not args.real))
    else:
        print(create_user(args.email, args.name, args.role, args.tenant))
    return 0


if __name__ == "__main__":
    sys.exit(main())
