"""Row Level Security at the database: the same rules hold without the API in the way."""

from __future__ import annotations

from typing import Any

import psycopg
import pytest

from meridian.api import db
from tests.api_support import World


def tx_for(world: World, tenant_key: str | None, role: str = "manager", bypass: bool = False) -> db.Tx:
    return db.open_tx(db.Context(world.tenants[tenant_key] if tenant_key else None, None, role, bypass))


def test_each_tenant_sees_only_its_rows_in_every_table(world: World) -> None:
    for key, other in (("A", "B"), ("B", "A")):
        tx = tx_for(world, key)
        try:
            for table in (
                "assets",
                "watch_zones",
                "alert_rules",
                "alerts",
                "exposures",
                "api_keys",
                "webhooks",
                "uploads",
                "briefings",
                "reports",
                "asset_groups",
                "subscriptions",
                "invoices",
            ):
                tenants = {str(r[0]) for r in tx.all(f"SELECT DISTINCT tenant_id FROM {table}")}  # noqa: S608
                assert tenants == {world.tenants[key]}, f"{table} leaked rows of tenant {other}"
        finally:
            tx.close()


def test_without_context_no_tenant_rows_are_visible(world: World) -> None:
    tx = db.open_tx(db.Context(None, None, None, False))
    try:
        for table in ("assets", "alerts", "exposures", "watch_zones", "users", "tenants", "audit_log"):
            assert tx.one(f"SELECT count(*) FROM {table}")[0] == 0, table  # type: ignore[index] # noqa: S608
    finally:
        tx.close()


def test_spatial_queries_are_filtered(world: World) -> None:
    tx = tx_for(world, "B")
    try:
        near_a = tx.one(
            "SELECT count(*) FROM assets WHERE ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(-89.64, 39.80), 4326)::geography, 100000)"
        )
        assert near_a == (0,)
        count = tx.one(
            "SELECT count(*) FROM exposures x JOIN assets a ON a.id = x.asset_id WHERE ST_DWithin(a.geom::geography, ST_SetSRID(ST_MakePoint(-93.3, 37.2), 4326)::geography, 100000)"
        )
        assert count == (1,)
        aggregate = tx.one("SELECT count(*), count(DISTINCT tenant_id) FROM assets")
        assert aggregate == (2, 1)
    finally:
        tx.close()


def test_writes_for_another_tenant_are_blocked(world: World) -> None:
    tx = tx_for(world, "B")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            tx.execute(
                "INSERT INTO assets (tenant_id, name, type, geom) VALUES (%s, 'x', 'site', ST_SetSRID(ST_MakePoint(1, 1), 4326))",
                (world.tenants["A"],),
            )
    finally:
        tx.close()
    tx = tx_for(world, "B")
    try:
        assert (
            tx.execute("UPDATE assets SET name = 'hijacked' WHERE tenant_id = %s", (world.tenants["A"],)).rowcount == 0
        )
        assert tx.execute("DELETE FROM alerts WHERE tenant_id = %s", (world.tenants["A"],)).rowcount == 0
    finally:
        tx.close()


def test_context_is_reapplied_after_commit(world: World) -> None:
    tx = tx_for(world, "B")
    try:
        tx.execute("UPDATE assets SET criticality = 2 WHERE name = 'B far'")
        tx.commit()
        assert tx.one("SELECT current_user")[0] == "meridian_app"  # type: ignore[index]
        assert tx.one("SELECT count(*) FROM assets")[0] == 2  # type: ignore[index]
        tx.rollback()
        assert tx.one("SELECT current_user")[0] == "meridian_app"  # type: ignore[index]
    finally:
        tx.close()


def test_password_hashes_and_secret_tables_are_out_of_reach(world: World) -> None:
    tx = tx_for(world, "A", role="tenant_admin")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            tx.one("SELECT password_hash FROM users")
        tx.rollback()
        for table in ("refresh_tokens", "user_mfa", "password_reset_tokens"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                tx.one(f"SELECT count(*) FROM {table}")  # noqa: S608
            tx.rollback()
    finally:
        tx.close()


def test_global_tables_are_read_only_for_the_application_role(world: World) -> None:
    tx = tx_for(world, "A")
    try:
        assert tx.one("SELECT count(*) FROM events")[0] == 2  # type: ignore[index]
        for statement in (
            "UPDATE events SET title = 'x'",
            "DELETE FROM places",
            "INSERT INTO event_sources (event_id, source_kind, source_ref) SELECT id, 'news', 'zz' FROM events",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                tx.execute(statement)
            tx.rollback()
    finally:
        tx.close()


def test_audit_log_is_append_only_and_chained(world: World, conn: psycopg.Connection[Any]) -> None:
    tx = tx_for(world, "A", role="tenant_admin")
    try:
        for i in range(3):
            tx.execute(
                "INSERT INTO audit_log (tenant_id, action, detail) VALUES (%s, 'test.action', %s)",
                (world.tenants["A"], f'{{"n": {i}}}'),
            )
        tx.commit()
        for statement in ("UPDATE audit_log SET action = 'x'", "DELETE FROM audit_log", "TRUNCATE audit_log"):
            with pytest.raises(psycopg.Error):
                tx.execute(statement)
            tx.rollback()
        assert tx.one("SELECT checked, first_bad_id FROM audit_verify()") is not None
    finally:
        tx.close()
    # The owner role also cannot change entries without disabling the trigger on purpose.
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute("UPDATE audit_log SET action = 'tampered'")
    conn.rollback()
    checked, bad = conn.execute("SELECT checked, first_bad_id FROM audit_verify()").fetchone()  # type: ignore[misc]
    assert checked >= 3 and bad is None


def test_audit_tampering_is_detected(world: World, conn: psycopg.Connection[Any]) -> None:
    for i in range(4):
        conn.execute(
            "INSERT INTO audit_log (tenant_id, action, detail) VALUES (%s, 'test.chain', %s)",
            (world.tenants["A"], f'{{"n": {i}}}'),
        )
    conn.commit()
    middle = conn.execute(
        "SELECT id FROM audit_log WHERE action = 'test.chain' ORDER BY id OFFSET 1 LIMIT 1"
    ).fetchone()[0]  # type: ignore[index]
    conn.execute("ALTER TABLE audit_log DISABLE TRIGGER audit_no_change")
    conn.execute("UPDATE audit_log SET detail = '{\"n\": 99}' WHERE id = %s", (middle,))
    conn.execute("ALTER TABLE audit_log ENABLE TRIGGER audit_no_change")
    conn.commit()
    checked, bad = conn.execute("SELECT checked, first_bad_id FROM audit_verify()").fetchone()  # type: ignore[misc]
    assert bad == middle
    # Restore the original value so later tests start from an intact chain.
    conn.execute("ALTER TABLE audit_log DISABLE TRIGGER audit_no_change")
    conn.execute("UPDATE audit_log SET detail = '{\"n\": 1}' WHERE id = %s", (middle,))
    conn.execute("ALTER TABLE audit_log ENABLE TRIGGER audit_no_change")
    conn.commit()
    assert conn.execute("SELECT first_bad_id FROM audit_verify()").fetchone() == (None,)
