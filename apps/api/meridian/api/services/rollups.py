"""Nightly rollups of live data into the daily statistics tables, and the metric view refresh.

`ops_stats_daily` and `platform_stats_daily` hold one row per day so that analytics stay fast over long periods. The demo data
loader fills them for synthetic tenants; these jobs fill them for real activity. Synthetic tenants (settings.synthetic) are skipped.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import psycopg


def rollup_ops_stats(conn: psycopg.Connection[Any], days: int = 3, today: dt.date | None = None) -> int:
    """Recompute the last `days` days (including today) of per tenant alert statistics from the alert tables."""
    today = today or dt.datetime.now(dt.UTC).date()
    start = today - dt.timedelta(days=days - 1)
    cur = conn.execute(
        """INSERT INTO ops_stats_daily (tenant_id, date, alerts_by_level, acknowledged, dismissed, location_confirmed, location_corrected, median_ack_minutes)
           SELECT a.tenant_id, a.created_at::date,
                  jsonb_build_object('critical', count(*) FILTER (WHERE a.level = 'critical'), 'high', count(*) FILTER (WHERE a.level = 'high'),
                                     'medium', count(*) FILTER (WHERE a.level = 'medium'), 'low', count(*) FILTER (WHERE a.level = 'low')),
                  count(*) FILTER (WHERE a.acknowledged_at IS NOT NULL), count(*) FILTER (WHERE a.status = 'dismissed'),
                  count(*) FILTER (WHERE a.acknowledged_at IS NOT NULL AND NOT EXISTS (
                      SELECT 1 FROM correction_requests c WHERE c.event_id = a.event_id AND c.tenant_id = a.tenant_id AND c.kind = 'wrong_location')),
                  count(*) FILTER (WHERE a.acknowledged_at IS NOT NULL AND EXISTS (
                      SELECT 1 FROM correction_requests c WHERE c.event_id = a.event_id AND c.tenant_id = a.tenant_id AND c.kind = 'wrong_location')),
                  (percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM (a.acknowledged_at - a.created_at)) / 60)
                      FILTER (WHERE a.acknowledged_at IS NOT NULL))::real
             FROM alerts a JOIN tenants t ON t.id = a.tenant_id
            WHERE a.created_at::date BETWEEN %s AND %s AND COALESCE(t.settings->>'synthetic', 'false') <> 'true'
            GROUP BY a.tenant_id, a.created_at::date
           ON CONFLICT (tenant_id, date) DO UPDATE SET alerts_by_level = EXCLUDED.alerts_by_level, acknowledged = EXCLUDED.acknowledged,
               dismissed = EXCLUDED.dismissed, location_confirmed = EXCLUDED.location_confirmed, location_corrected = EXCLUDED.location_corrected,
               median_ack_minutes = EXCLUDED.median_ack_minutes""",
        (start, today),
    )
    return cur.rowcount


def rollup_platform_stats(conn: psycopg.Connection[Any], days: int = 3, today: dt.date | None = None) -> int:
    """Incidents ingested, median detection delay, and false alert rate for the last days. Latency columns are not touched."""
    today = today or dt.datetime.now(dt.UTC).date()
    start = today - dt.timedelta(days=days - 1)
    cur = conn.execute(
        """INSERT INTO platform_stats_daily (date, incidents_ingested, detection_delay_minutes_median, false_alert_rate)
           SELECT d.day, d.incidents, d.delay,
                  (SELECT count(*) FILTER (WHERE a.status = 'dismissed')::real / NULLIF(count(*) FILTER (WHERE a.status IN ('dismissed', 'resolved')), 0)
                     FROM alerts a WHERE a.created_at::date = d.day)
             FROM (SELECT e.first_seen_at::date AS day, count(*)::int AS incidents,
                          (percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM (e.first_seen_at - e.occurred_at)) / 60)
                              FILTER (WHERE e.occurred_at IS NOT NULL AND e.occurred_at <= e.first_seen_at))::real AS delay
                     FROM events e WHERE e.first_seen_at::date BETWEEN %s AND %s GROUP BY 1) d
           ON CONFLICT (date) DO UPDATE SET incidents_ingested = EXCLUDED.incidents_ingested,
               detection_delay_minutes_median = EXCLUDED.detection_delay_minutes_median, false_alert_rate = EXCLUDED.false_alert_rate""",
        (start, today),
    )
    return cur.rowcount


def refresh_metrics(conn: psycopg.Connection[Any]) -> dt.datetime:
    row = conn.execute("SELECT refresh_metrics()").fetchone()
    assert row is not None
    stamp: dt.datetime = row[0]
    return stamp
