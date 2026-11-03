"""Background jobs: webhook delivery, retention purge, and audit chain verification.

Run `python -m meridian.api.worker` for a loop, or `--once` from cron. The work is plain SQL and HTTP, so a Celery deployment can call
the same functions as tasks.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from typing import Any

import psycopg

from meridian.api import db
from meridian.api.security import audit
from meridian.api.services import webhooks

log = logging.getLogger("meridian.worker")
DEFAULT_RETENTION_DAYS = 365
DELIVERY_LOG_DAYS = 30


def purge(conn: psycopg.Connection[Any]) -> dict[str, int]:
    """Delete tenant data older than each tenant's retention setting and expired credentials. The audit log is never purged."""
    counts = dict.fromkeys(("alerts", "uploads", "briefings", "reports", "deliveries", "tokens", "idempotency_keys"), 0)
    for tenant_id, settings in conn.execute("SELECT id, settings FROM tenants").fetchall():
        days = int((settings or {}).get("risk_config", {}).get("retention_days", DEFAULT_RETENTION_DAYS))
        cutoff = "now() - make_interval(days => %s)"
        counts["alerts"] += conn.execute(
            f"DELETE FROM alerts WHERE tenant_id = %s AND status IN ('dismissed', 'resolved') AND updated_at < {cutoff}",  # noqa: S608
            (tenant_id, days),
        ).rowcount
        for table, key in (("uploads", "uploads"), ("briefings", "briefings"), ("reports", "reports")):
            counts[key] += conn.execute(
                f"DELETE FROM {table} WHERE tenant_id = %s AND created_at < {cutoff}", (tenant_id, days)
            ).rowcount  # noqa: S608
    counts["deliveries"] = conn.execute(
        "DELETE FROM webhook_deliveries WHERE created_at < now() - make_interval(days => %s)", (DELIVERY_LOG_DAYS,)
    ).rowcount
    counts["tokens"] = (
        conn.execute("DELETE FROM refresh_tokens WHERE absolute_expires_at < now() - interval '1 day'").rowcount
        + conn.execute("DELETE FROM password_reset_tokens WHERE expires_at < now() - interval '1 day'").rowcount
    )
    counts["idempotency_keys"] = conn.execute(
        "DELETE FROM idempotency_keys WHERE created_at < now() - interval '7 days'"
    ).rowcount
    audit.record(conn, "system.purge", actor_type="system", detail=counts)
    return counts


def verify_audit(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    result = audit.verify(conn)
    if not result["intact"]:
        log.error("audit chain broken at entry %s", result["first_bad_id"])
        audit.record(
            conn, "system.audit_chain_broken", actor_type="system", detail={"first_bad_id": result["first_bad_id"]}
        )
    return result


def run_once() -> dict[str, Any]:
    with db.system_connection() as conn:
        delivered = webhooks.run_due(conn)
        conn.commit()
        return {"webhooks": delivered}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m meridian.api.worker")
    parser.add_argument("--once", action="store_true", help="run each job once and exit")
    parser.add_argument("--interval", type=float, default=5.0, help="seconds between webhook delivery passes")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    last_maintenance = 0.0
    while True:
        print(json.dumps(run_once()))
        if time.monotonic() - last_maintenance > 3600 or args.once:
            with db.system_connection() as conn:
                print(json.dumps({"purge": purge(conn), "audit": verify_audit(conn)}))
                conn.commit()
            last_maintenance = time.monotonic()
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
