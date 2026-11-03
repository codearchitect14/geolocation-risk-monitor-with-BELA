"""Background jobs: webhook delivery, retention purge, and audit chain verification.

Run `python -m meridian.api.worker` for a loop, or `--once` from cron. The work is plain SQL and HTTP, so a Celery deployment can call
the same functions as tasks.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
import time
from typing import Any

import psycopg

from meridian.api import db
from meridian.api.security import audit
from meridian.api.services import briefings, lifecycle, webhooks

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


def generate_briefings(
    conn: psycopg.Connection[Any], now: dt.datetime | None = None, mailer: Any = None, writer: Any = None
) -> dict[str, int]:
    """Create the daily briefing for the previous UTC day (from 06:00 UTC) and the weekly one for the previous Monday to
    Sunday (on Mondays) for tenants that turned them on. A unique index makes the job safe to repeat."""
    from meridian.api.services import briefings, reports
    from meridian.api.services.mailer import get_mailer

    now = now or dt.datetime.now(dt.UTC)
    created = {"daily": 0, "weekly": 0, "emailed": 0}
    if now.hour < 6:
        return created
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    periods = {"daily": (today - dt.timedelta(days=1), today)}
    if today.weekday() == 0:
        periods["weekly"] = (today - dt.timedelta(days=7), today)
    for tenant_id, settings in conn.execute("SELECT id, settings FROM tenants WHERE status = 'active'").fetchall():
        config = (settings or {}).get("risk_config", {})
        for kind, (start, end) in periods.items():
            if not config.get(f"{kind}_briefing"):
                continue
            tx = db.open_tx(db.Context(str(tenant_id), None, "manager"))
            try:
                evidence = briefings.build_evidence(tx, start, end)
                narrative, version = briefings.narrative_for(evidence, writer)
                row = tx.one(
                    """INSERT INTO briefings (tenant_id, kind, period_start, period_end, evidence, narrative, model_version)
                       VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
                       RETURNING id, kind, period_start, period_end, evidence, narrative, model_version, created_at""",
                    (str(tenant_id), kind, start, end, json.dumps(evidence, default=str), narrative, version),
                )
                tx.commit()
                if row is None:
                    continue
                created[kind] += 1
                if config.get("briefing_email"):
                    created["emailed"] += _email_briefing(tx, row, mailer or get_mailer(), reports)
            finally:
                tx.close()
    return created


def _email_briefing(tx: db.Tx, row: tuple[Any, ...], mailer: Any, reports: Any) -> int:
    from meridian.api.services import render

    view = {"id": str(row[0]), "kind": row[1], "evidence": row[4], "narrative": row[5], "created_at": row[7]}
    document = reports.briefing_html(view)
    pdf = render.html_to_pdf(document)
    attachment = ("briefing.pdf", pdf, "application/pdf") if pdf else ("briefing.html", document.encode(), "text/html")
    sent = 0
    for (email,) in tx.all("SELECT email FROM users WHERE status = 'active' AND notify_email AND tenant_id IS NOT NULL"):
        mailer.send(email, f"{row[1].capitalize()} briefing", (row[5] or "") + "\n", [attachment])
        sent += 1
    tx.execute("UPDATE briefings SET delivered_at = now() WHERE id = %s", (str(row[0]),))
    tx.commit()
    return sent


def run_once() -> dict[str, Any]:
    with db.system_connection() as conn:
        delivered = webhooks.run_due(conn)
        conn.commit()
        escalated = lifecycle.escalate_due(conn)
        briefing_counts = generate_briefings(conn, writer=briefings.local_model_writer())
        return {"webhooks": delivered, "escalated": len(escalated), "briefings": briefing_counts}


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
