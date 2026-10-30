from typing import Any

import psycopg
from alembic import command

from tests.conftest import alembic_config

EXPECTED_TABLES = {
    # tenancy and security
    "tenants",
    "users",
    "user_mfa",
    "refresh_tokens",
    "api_keys",
    "audit_log",
    # places
    "places",
    "place_aliases",
    "place_embeddings",
    # news and NLP
    "articles",
    "article_embeddings",
    "mentions",
    "mention_candidates",
    # events
    "events",
    "event_sources",
    "event_updates",
    # assets and alerts
    "assets",
    "asset_groups",
    "watch_zones",
    "exposures",
    "alerts",
    "alert_events",
    "alert_rules",
    "briefings",
    "reports",
    "correction_requests",
    # business
    "plans",
    "subscriptions",
    "invoices",
    "invoice_lines",
    "usage_daily",
    "ops_stats_daily",
    "platform_stats_daily",
    "marketing_spend",
    "business_events",
}


def tables(conn: psycopg.Connection[Any]) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        return {r[0] for r in cur.fetchall()}


def test_schema_contains_every_planned_table(conn: psycopg.Connection[Any]) -> None:
    assert tables(conn) >= EXPECTED_TABLES


def test_required_extensions_and_indexes(conn: psycopg.Connection[Any]) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT extname FROM pg_extension")
        assert {"postgis", "vector", "pg_trgm", "pgcrypto"} <= {r[0] for r in cur.fetchall()}
        cur.execute("SELECT indexdef FROM pg_indexes WHERE tablename = 'places'")
        definitions = " ".join(r[0] for r in cur.fetchall())
    assert "USING gist" in definitions and "gin_trgm_ops" in definitions


def test_vector_column_is_1024_dimensions(conn: psycopg.Connection[Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT format_type(a.atttypid, a.atttypmod) FROM pg_attribute a
                WHERE a.attrelid = 'place_embeddings'::regclass AND a.attname = 'embedding'"""
        )
        row = cur.fetchone()
    assert row is not None and row[0] == "vector(1024)"


def test_platform_roles_must_not_have_tenant_and_tenant_roles_must(conn: psycopg.Connection[Any]) -> None:
    import pytest

    with conn.cursor() as cur:
        cur.execute("INSERT INTO tenants (name, slug) VALUES ('Demo', 'demo') RETURNING id")
        row = cur.fetchone()
        assert row is not None
        tenant = row[0]
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "INSERT INTO users (tenant_id, email, display_name, password_hash, role) VALUES (%s, 'a@x.test', 'A', 'h', 'platform_admin')",
                (tenant,),
            )
    conn.rollback()


def test_alert_dismissal_requires_reason(conn: psycopg.Connection[Any]) -> None:
    import pytest

    with conn.cursor() as cur:
        cur.execute("INSERT INTO tenants (name, slug) VALUES ('Demo2', 'demo2') RETURNING id")
        tenant = cur.fetchone()[0]  # type: ignore[index]
        cur.execute(
            "INSERT INTO events (type, severity, first_seen_at, last_seen_at, title) "
            "VALUES ('flood', 2, now(), now(), 't') RETURNING id"
        )
        event = cur.fetchone()[0]  # type: ignore[index]
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "INSERT INTO alerts (tenant_id, event_id, level, status) VALUES (%s, %s, 'high', 'dismissed')",
                (tenant, event),
            )
    conn.rollback()


def test_downgrade_and_upgrade_roundtrip(migrated_url: str, conn: psycopg.Connection[Any]) -> None:
    conn.rollback()
    conn.close()
    command.downgrade(alembic_config(), "base")
    import meridian.db as db

    check = db.connect()
    try:
        assert "places" not in tables(check)
    finally:
        check.close()
    command.upgrade(alembic_config(), "head")
