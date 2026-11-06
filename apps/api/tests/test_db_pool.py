"""The connection pool must never carry a request's role or tenant context into the next user of the connection."""

from __future__ import annotations

from typing import Any

import psycopg
import pytest

from meridian.api import db


@pytest.fixture
def pooled(migrated_url: str) -> Any:
    db.close_pools()
    yield
    db.close_pools()


def test_connections_are_reused_and_come_back_clean(pooled: Any, conn: psycopg.Connection[Any]) -> None:
    tenant = conn.execute("INSERT INTO tenants (name, slug) VALUES ('Pool', 'pool-test') RETURNING id").fetchone()
    assert tenant is not None
    conn.execute(
        "INSERT INTO assets (tenant_id, name, type, geom) VALUES (%s, 'A', 'site', ST_SetSRID(ST_MakePoint(1, 1), 4326))",
        (tenant[0],),
    )
    conn.commit()

    ctx = db.Context(str(tenant[0]), None, "manager")
    first = db.open_tx(ctx)
    assert first.one("SELECT current_user") == ("meridian_app",)
    assert first.one("SELECT count(*) FROM assets") == (1,)
    first.close()

    for _ in range(4):  # every pooled connection, including the one just released, comes back without role or context
        with db.system_connection() as owner:
            assert owner.execute("SELECT current_user").fetchone() != ("meridian_app",)
            assert owner.execute("SELECT current_setting('app.tenant_id', true)").fetchone() in (("",), (None,))

    nobody = db.open_tx(db.Context(None, None, None))
    assert nobody.one("SELECT count(*) FROM assets") == (0,)  # no tenant: no rows
    nobody.close()

    platform = db.open_tx(db.Context(None, None, "platform_admin", bypass=True))
    assert platform.one("SELECT current_user") == ("meridian_platform",)
    assert platform.one("SELECT count(*) FROM assets")[0] >= 1  # allow-all policy for platform staff
    platform.close()

    conn.execute("DELETE FROM tenants WHERE slug = 'pool-test'")
    conn.commit()


def test_pool_survives_a_rolled_back_failure(pooled: Any) -> None:
    tx = db.open_tx(db.Context(None, None, None))
    with pytest.raises(psycopg.errors.UndefinedTable):
        tx.one("SELECT * FROM table_that_does_not_exist")
    tx.close()  # the aborted transaction is rolled back, so the connection is usable again
    again = db.open_tx(db.Context(None, None, None))
    assert again.one("SELECT 1") == (1,)
    again.close()
