"""Load the synthetic business history (data/synthetic/*.csv) into PostgreSQL and refresh the metric views.

python -m meridian.business.loader [--dir data/synthetic]

Loading replaces the previous synthetic data: tenants created by the generator carry settings.synthetic = true and are removed
(with their subscriptions, invoices, usage, and statistics) before the files are read again. Tenants and users that were
created in other ways are never touched. All rows are demo data.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import psycopg

from meridian.config import get_settings
from meridian.db import connect

SYNTHETIC = json.dumps({"synthetic": True})


def _rows(path: Path) -> Iterator[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        yield from csv.DictReader(handle)


def _none(value: str) -> str | None:
    return value if value != "" else None


def _copy(
    conn: psycopg.Connection[Any], table: str, columns: list[str], rows: Iterator[dict[str, str]], convert: Callable[[dict[str, str]], list[Any]]
) -> int:
    count = 0
    with conn.cursor() as cur, cur.copy(f"COPY {table} ({', '.join(columns)}) FROM STDIN") as copy:  # noqa: S608 - fixed identifiers
        for row in rows:
            copy.write_row(convert(row))
            count += 1
    return count


def load(conn: psycopg.Connection[Any], directory: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    missing = [n for n in ("tenants", "subscriptions") if not (directory / f"{n}.csv").is_file()]
    if missing:
        raise FileNotFoundError(f"missing {', '.join(missing)} in {directory}; run generate_demo_business_data.py first")
    conn.execute("DELETE FROM tenants WHERE settings->>'synthetic' = 'true'")
    conn.execute("DELETE FROM platform_stats_daily")
    conn.execute("DELETE FROM marketing_spend")
    conn.execute("DELETE FROM business_events")
    for p in _rows(directory / "plans.csv"):
        conn.execute(
            """INSERT INTO plans (id, name, monthly_price, asset_limit, overage_unit_size, overage_unit_price) VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, monthly_price = EXCLUDED.monthly_price, asset_limit = EXCLUDED.asset_limit,
                   overage_unit_size = EXCLUDED.overage_unit_size, overage_unit_price = EXCLUDED.overage_unit_price""",
            (p["id"], p["name"], p["monthly_price"], p["asset_limit"], p["overage_unit_size"], p["overage_unit_price"]),
        )
    counts["plans"] = 3
    counts["tenants"] = _copy(
        conn, "tenants", ["id", "name", "slug", "industry", "region", "country_code", "status", "is_demo", "settings", "created_at", "churned_at", "acquisition_channel"],
        _rows(directory / "tenants.csv"),
        lambda r: [r["id"], r["name"], r["slug"], r["industry"], r["region"], r["country"], "churned" if r["churned_at"] else "active", True, SYNTHETIC, r["created_at"], _none(r["churned_at"]), _none(r["acquisition_channel"])],
    )  # fmt: skip
    simple: list[tuple[str, str, list[str], list[str]]] = [
        ("subscriptions", "subscriptions", ["id", "tenant_id", "plan_id", "billing_cycle", "price", "start_date", "end_date", "change_reason"], ["id", "tenant_id", "plan", "billing_cycle", "price", "start", "end", "change_reason"]),
        ("invoices", "invoices", ["id", "tenant_id", "period_start", "period_end", "status", "total", "issued_at", "due_at", "paid_at"], ["id", "tenant_id", "period_start", "period_end", "status", "total", "issued_at", "due_at", "paid_at"]),
        ("invoice_lines", "invoice_lines", ["id", "invoice_id", "line_type", "description", "amount"], ["id", "invoice_id", "line_type", "description", "amount"]),
        ("usage_daily", "usage_daily", ["tenant_id", "date", "assets_monitored", "alerts", "briefings", "api_calls", "uploads"], ["tenant_id", "date", "assets_monitored", "alerts", "briefings", "api_calls", "uploads"]),
        ("ops_stats_daily", "ops_stats_daily", ["tenant_id", "date", "alerts_by_level", "acknowledged", "dismissed", "location_confirmed", "location_corrected", "median_ack_minutes"], ["tenant_id", "date", "alerts_by_level", "acknowledged", "dismissed", "location_confirmed", "location_corrected", "median_ack_minutes"]),
        ("platform_stats_daily", "platform_stats_daily", ["date", "incidents_ingested", "p50_latency_ms", "p95_latency_ms", "detection_delay_minutes_median", "false_alert_rate"], ["date", "incidents_ingested", "p50_latency_ms", "p95_latency_ms", "detection_delay_minutes_median", "false_alert_rate"]),
        ("marketing_spend", "marketing_spend", ["month", "channel", "spend"], ["month", "channel", "spend"]),
        ("business_events", "business_events", ["date", "label"], ["date", "label"]),
    ]  # fmt: skip
    for name, table, db_columns, csv_columns in simple:
        picks = csv_columns

        def convert(r: dict[str, str], cols: list[str] = picks) -> list[Any]:
            return [_none(r[c]) for c in cols]

        counts[name] = _copy(conn, table, db_columns, _rows(directory / f"{name}.csv"), convert)
    conn.commit()
    conn.execute("SELECT refresh_metrics()")
    conn.commit()
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m meridian.business.loader")
    parser.add_argument("--dir", type=Path, default=get_settings().data_dir / "synthetic")
    args = parser.parse_args(argv)
    conn = connect()
    try:
        counts = load(conn, args.dir)
    finally:
        conn.close()
    for name, n in counts.items():
        print(f"{name:22s} {n:>8d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
