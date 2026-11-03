"""Operational analytics.

Tenant endpoints (`/analytics/*`) are scoped by Row Level Security to the caller's tenant. Platform endpoints
(`/platform/analytics/*`) aggregate across tenants and return counts, never asset locations or names.

Daily alert statistics come from `ops_stats_daily` (written by the nightly rollup for live tenants, and by the demo data loader).
For a tenant and date without a statistics row the same figures are computed from the live alert tables, so today is never empty.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response

from meridian.api.auth import Principal, get_tx, require
from meridian.api.db import Tx
from meridian.api.routers.common import EVENT_TYPES
from meridian.api.services import analytics as an

router = APIRouter(tags=["analytics"])
Granularity = Query(default="day", pattern="^(day|week|month)$")
Compare = Query(default="none", pattern="^(none|previous_period|previous_year)$")
Format = Query(default="json", pattern="^(json|csv)$")
LEVELS = ("critical", "high", "medium", "low")

# One row per date: statistics when present for a tenant and date, otherwise computed from the alert tables.
DAILY_OPS = """
WITH stats AS (
    SELECT tenant_id, date, COALESCE((alerts_by_level->>'critical')::int, 0) AS critical, COALESCE((alerts_by_level->>'high')::int, 0) AS high,
           COALESCE((alerts_by_level->>'medium')::int, 0) AS medium, COALESCE((alerts_by_level->>'low')::int, 0) AS low,
           acknowledged, dismissed, location_confirmed, location_corrected, median_ack_minutes
      FROM ops_stats_daily WHERE date BETWEEN %(start)s AND %(end)s
), live AS (
    SELECT a.tenant_id, a.created_at::date AS date,
           count(*) FILTER (WHERE a.level = 'critical')::int AS critical, count(*) FILTER (WHERE a.level = 'high')::int AS high,
           count(*) FILTER (WHERE a.level = 'medium')::int AS medium, count(*) FILTER (WHERE a.level = 'low')::int AS low,
           count(*) FILTER (WHERE a.acknowledged_at IS NOT NULL)::int AS acknowledged,
           count(*) FILTER (WHERE a.status = 'dismissed')::int AS dismissed,
           count(*) FILTER (WHERE a.acknowledged_at IS NOT NULL AND NOT EXISTS (
               SELECT 1 FROM correction_requests c WHERE c.event_id = a.event_id AND c.tenant_id = a.tenant_id AND c.kind = 'wrong_location'))::int AS location_confirmed,
           count(*) FILTER (WHERE a.acknowledged_at IS NOT NULL AND EXISTS (
               SELECT 1 FROM correction_requests c WHERE c.event_id = a.event_id AND c.tenant_id = a.tenant_id AND c.kind = 'wrong_location'))::int AS location_corrected,
           (percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM (a.acknowledged_at - a.created_at)) / 60)
               FILTER (WHERE a.acknowledged_at IS NOT NULL))::real AS median_ack_minutes
      FROM alerts a WHERE a.created_at::date BETWEEN %(start)s AND %(end)s GROUP BY 1, 2
), merged AS (
    SELECT * FROM stats
    UNION ALL SELECT * FROM live l WHERE NOT EXISTS (SELECT 1 FROM stats s WHERE s.tenant_id = l.tenant_id AND s.date = l.date)
)
SELECT {bucket} AS period, sum(critical)::int, sum(high)::int, sum(medium)::int, sum(low)::int, sum(acknowledged)::int, sum(dismissed)::int,
       sum(location_confirmed)::int, sum(location_corrected)::int,
       (sum(median_ack_minutes * acknowledged) FILTER (WHERE median_ack_minutes IS NOT NULL) / NULLIF(sum(acknowledged) FILTER (WHERE median_ack_minutes IS NOT NULL), 0))::float8
  FROM merged GROUP BY 1 ORDER BY 1
"""


def ops_series(tx: Tx, period: an.Period) -> list[dict[str, Any]]:
    # The bucket expression is built from a validated granularity and a fixed column name.
    rows = tx.all(DAILY_OPS.format(bucket=an.bucket(period.granularity, "date")), {"start": period.start, "end": period.end})
    out = []
    for r in rows:
        total = sum(r[1:5])
        confirmed_base = r[7] + r[8]
        out.append(
            {
                "period": r[0], "alerts": total, "critical": r[1], "high": r[2], "medium": r[3], "low": r[4], "acknowledged": r[5], "dismissed": r[6],
                "acknowledgement_rate": round(r[5] / total, 4) if total else None,
                "location_confirmed": r[7], "location_corrected": r[8],
                "location_confirmation_rate": round(r[7] / confirmed_base, 4) if confirmed_base else None,
                "avg_minutes_to_acknowledge": round(r[9], 1) if r[9] is not None else None,
            }
        )  # fmt: skip
    return out


def totals(series: list[dict[str, Any]]) -> dict[str, Any]:
    t = {k: sum(i[k] for i in series) for k in ("alerts", "critical", "high", "medium", "low", "acknowledged", "dismissed", "location_confirmed", "location_corrected")}
    weighted = [(i["avg_minutes_to_acknowledge"], i["acknowledged"]) for i in series if i["avg_minutes_to_acknowledge"] is not None and i["acknowledged"]]
    base = sum(w for _, w in weighted)
    t["avg_minutes_to_acknowledge"] = round(sum(v * w for v, w in weighted) / base, 1) if base else None
    t["acknowledgement_rate"] = round(t["acknowledged"] / t["alerts"], 4) if t["alerts"] else None
    c = t["location_confirmed"] + t["location_corrected"]
    t["location_confirmation_rate"] = round(t["location_confirmed"] / c, 4) if c else None
    return t


def kpi_changes(now: dict[str, Any], before: dict[str, Any]) -> dict[str, Any]:
    return {k: an.change(now[k], before[k]) for k in ("alerts", "acknowledged", "dismissed", "acknowledgement_rate", "avg_minutes_to_acknowledge", "location_confirmation_rate")}


def scope_of(principal: Principal) -> str:
    return principal.tenant_id or "platform"


# -- tenant endpoints -----------------------------------------------------------------------------------------------------
@router.get("/analytics/operations", summary="Alert volumes, acknowledgement, and response times for this tenant")
def operations(
    request: Request,
    start: dt.date | None = Query(default=None, alias="from"),
    end: dt.date | None = Query(default=None, alias="to"),
    days: int | None = Query(default=None, ge=1, le=365, description="Shortcut for the last n days when from is not given"),
    granularity: str = Granularity,
    compare: str = Compare,
    level: str | None = Query(default=None, pattern="^(critical|high|medium|low)$"),
    format: str = Format,
    principal: Principal = Depends(require("rules.manage")),
    tx: Tx = Depends(get_tx),
) -> Response:
    period = an.parse_period(start, end, granularity, days or 30)

    def build() -> dict[str, Any]:
        series = ops_series(tx, period)
        t = totals(series)
        by_status = {r[0]: r[1] for r in tx.all("SELECT status, count(*) FROM alerts WHERE created_at::date BETWEEN %s AND %s GROUP BY 1", (period.start, period.end))}
        assets = tx.all(
            """SELECT s.name, count(*) FROM alerts a JOIN assets s ON s.id = a.asset_id
                WHERE a.created_at::date BETWEEN %s AND %s AND (%s::text IS NULL OR a.level = %s) GROUP BY s.name ORDER BY 2 DESC, 1 LIMIT 10""",
            (period.start, period.end, level, level),
        )
        payload: dict[str, Any] = {
            "from": period.start, "to": period.end, "granularity": granularity, "period_days": period.days,
            "series": series, "totals": t,
            "alerts_by_level": {k: t[k] for k in LEVELS}, "alerts_by_status": by_status,
            "alerts_per_day": [{"date": i["period"], "alerts": i[level] if level else i["alerts"]} for i in series],
            "median_minutes_to_acknowledge": t["avg_minutes_to_acknowledge"],
            "most_alerted_assets": [{"asset": r[0], "alerts": r[1]} for r in assets],
        }  # fmt: skip
        if level:
            payload["level"] = level
        other = an.comparison_period(period, compare)
        if other:
            prev = ops_series(tx, other)
            payload["comparison"] = {"from": other.start, "to": other.end, "series": prev, "totals": totals(prev), "changes": kpi_changes(t, totals(prev))}
        return payload

    payload = an.CACHE.get_or_compute(("ops", scope_of(principal), period, compare, level), build)
    cols = ["period", "alerts", *LEVELS, "acknowledged", "dismissed", "acknowledgement_rate", "avg_minutes_to_acknowledge"]
    return an.respond(request, payload, format, cols, [[i[c] for c in cols] for i in payload["series"]], "operations")


@router.get("/analytics/quality", summary="Location confirmation, corrections, and event confirmation for this tenant")
def quality(
    request: Request,
    start: dt.date | None = Query(default=None, alias="from"),
    end: dt.date | None = Query(default=None, alias="to"),
    days: int | None = Query(default=None, ge=1, le=365),
    granularity: str = Granularity,
    compare: str = Compare,
    format: str = Format,
    principal: Principal = Depends(require("rules.manage")),
    tx: Tx = Depends(get_tx),
) -> Response:
    period = an.parse_period(start, end, granularity, days or 30)

    def build() -> dict[str, Any]:
        series = ops_series(tx, period)
        t = totals(series)
        conf = {r[0]: r[1] for r in tx.all("SELECT confirmation, count(*) FROM events WHERE last_seen_at::date BETWEEN %s AND %s GROUP BY 1", (period.start, period.end))}
        events = sum(conf.values())
        corrections = {
            f"{r[0]}:{r[1]}": r[2]
            for r in tx.all("SELECT kind, status, count(*) FROM correction_requests WHERE created_at::date BETWEEN %s AND %s GROUP BY 1, 2", (period.start, period.end))
        }
        payload: dict[str, Any] = {
            "from": period.start, "to": period.end, "granularity": granularity, "period_days": period.days,
            "series": [{k: i[k] for k in ("period", "location_confirmed", "location_corrected", "location_confirmation_rate")} for i in series],
            "location_confirmation_rate": t["location_confirmation_rate"],
            "events": events, "confirmed_share": round(conf.get("confirmed", 0) / events, 3) if events else None,
            "corrections_submitted_by_this_tenant": corrections,
            "definition": "Location confirmation rate: alerts acknowledged without a wrong-location correction, as a share of acknowledged alerts that were confirmed or corrected.",
        }  # fmt: skip
        other = an.comparison_period(period, compare)
        if other:
            prev = totals(ops_series(tx, other))
            payload["comparison"] = {"from": other.start, "to": other.end, "location_confirmation_rate": an.change(t["location_confirmation_rate"], prev["location_confirmation_rate"])}
        return payload

    payload = an.CACHE.get_or_compute(("quality", scope_of(principal), period, compare), build)
    cols = ["period", "location_confirmed", "location_corrected", "location_confirmation_rate"]
    return an.respond(request, payload, format, cols, [[i[c] for c in cols] for i in payload["series"]], "quality")


@router.get("/analytics/usage", summary="Usage for this tenant against its plan (demo data)")
def usage(
    request: Request,
    start: dt.date | None = Query(default=None, alias="from"),
    end: dt.date | None = Query(default=None, alias="to"),
    days: int | None = Query(default=None, ge=1, le=365),
    granularity: str = Granularity,
    compare: str = Compare,
    format: str = Format,
    principal: Principal = Depends(require("rules.manage")),
    tx: Tx = Depends(get_tx),
) -> Response:
    period = an.parse_period(start, end, granularity, days or 30)

    def series(p: an.Period) -> list[dict[str, Any]]:
        rows = tx.all(
            f"""SELECT {an.bucket(p.granularity, 'date')}, round(avg(assets_monitored))::int, sum(alerts)::int, sum(briefings)::int, sum(api_calls)::bigint, sum(uploads)::int
                  FROM usage_daily WHERE date BETWEEN %s AND %s GROUP BY 1 ORDER BY 1""",  # noqa: S608
            (p.start, p.end),
        )
        return [{"period": r[0], "date": r[0], "assets_monitored": r[1], "alerts": r[2], "briefings": r[3], "api_calls": r[4], "uploads": r[5]} for r in rows]

    def build() -> dict[str, Any]:
        items = series(period)
        plan = tx.one(
            """SELECT p.name, p.asset_limit, p.overage_unit_size FROM subscriptions s JOIN plans p ON p.id = s.plan_id
                WHERE s.end_date IS NULL OR s.end_date >= current_date ORDER BY s.start_date DESC LIMIT 1"""
        )
        latest = items[-1]["assets_monitored"] if items else None
        payload: dict[str, Any] = {
            "from": period.start, "to": period.end, "granularity": granularity, "items": items, "demo_data": True,
            "plan": {"name": plan[0], "asset_limit": plan[1], "assets_over_limit": max((latest or 0) - plan[1], 0)} if plan else None,
        }  # fmt: skip
        other = an.comparison_period(period, compare)
        if other:
            payload["comparison"] = {"from": other.start, "to": other.end, "items": series(other)}
        return payload

    payload = an.CACHE.get_or_compute(("usage", scope_of(principal), period, compare), build)
    cols = ["period", "assets_monitored", "alerts", "briefings", "api_calls", "uploads"]
    return an.respond(request, payload, format, cols, [[i[c] for c in cols] for i in payload["items"]], "usage")


# -- platform endpoints ---------------------------------------------------------------------------------------------------
PLATFORM = "platform.manage"
GROUPS = {"type": "e.type", "subtype": "COALESCE(e.subtype, 'unspecified')", "region": "region_of_country(p.country_code)", "country": "COALESCE(p.country_code, 'unknown')"}


def top_groups(rows: list[tuple[Any, ...]], keep: int = 8) -> tuple[list[str], dict[tuple[Any, str], int]]:
    totals_by: dict[str, int] = {}
    for _, g, n in rows:
        totals_by[g] = totals_by.get(g, 0) + n
    names = [g for g, _ in sorted(totals_by.items(), key=lambda kv: -kv[1])[:keep]]
    cells: dict[tuple[Any, str], int] = {}
    for p, g, n in rows:
        key = (p, g if g in names else "other")
        cells[key] = cells.get(key, 0) + n
    if any(g not in names for g in totals_by):
        names.append("other")
    return names, cells


@router.get("/platform/analytics/incidents", summary="Incident volumes by type, subtype, region, or country")
def incidents(
    request: Request,
    start: dt.date | None = Query(default=None, alias="from"),
    end: dt.date | None = Query(default=None, alias="to"),
    granularity: str = Granularity,
    compare: str = Compare,
    by: str = Query(default="type", pattern="^(type|subtype|region|country)$"),
    type: str | None = Query(default=None, description="Filter to one event type"),
    region: str | None = Query(default=None, max_length=40),
    min_severity: int = Query(default=1, ge=1, le=4),
    format: str = Format,
    principal: Principal = Depends(require(PLATFORM)),
    tx: Tx = Depends(get_tx),
) -> Response:
    period = an.parse_period(start, end, granularity, 90)
    if type is not None and type not in EVENT_TYPES:
        from meridian.api.errors import ProblemError

        raise ProblemError(422, "Unknown event type.", code="invalid-type")

    def counts(p: an.Period) -> list[tuple[Any, ...]]:
        return tx.all(
            f"""SELECT {an.bucket(p.granularity, 'e.first_seen_at::date')}, {GROUPS[by]}, count(*)::int
                  FROM events e LEFT JOIN places p ON p.id = e.location_place_id
                 WHERE e.first_seen_at::date BETWEEN %s AND %s AND e.severity >= %s AND (%s::text IS NULL OR e.type = %s)
                   AND (%s::text IS NULL OR region_of_country(p.country_code) = %s)
                 GROUP BY 1, 2 ORDER BY 1, 2""",  # noqa: S608
            (p.start, p.end, min_severity, type, type, region, region),
        )

    def build() -> dict[str, Any]:
        rows = counts(period)
        names, cells = top_groups(rows)
        periods = sorted({r[0] for r in rows})
        payload: dict[str, Any] = {
            "from": period.start, "to": period.end, "granularity": granularity, "by": by, "groups": names,
            "series": [{"period": p, "counts": {g: cells.get((p, g), 0) for g in names}, "total": sum(cells.get((p, g), 0) for g in names)} for p in periods],
            "totals": {g: sum(cells.get((p, g), 0) for p in periods) for g in names},
        }  # fmt: skip
        ingested = tx.all(f"SELECT {an.bucket(period.granularity, 'date')}, sum(incidents_ingested)::int FROM platform_stats_daily WHERE date BETWEEN %s AND %s GROUP BY 1 ORDER BY 1", (period.start, period.end))  # noqa: S608
        payload["ingested_per_period"] = [{"period": r[0], "incidents": r[1]} for r in ingested]
        other = an.comparison_period(period, compare)
        if other:
            prev_rows = counts(other)
            prev_total = sum(r[2] for r in prev_rows)
            now_total = sum(payload["totals"].values())
            payload["comparison"] = {"from": other.start, "to": other.end, "total": an.change(now_total, prev_total)}
        return payload

    payload = an.CACHE.get_or_compute(("p-incidents", scope_of(principal), period, compare, by, type, region, min_severity), build)
    rows = [[s["period"], g, s["counts"][g]] for s in payload["series"] for g in payload["groups"]]
    return an.respond(request, payload, format, ["period", by, "incidents"], rows, "incidents")


@router.get("/platform/analytics/exposure", summary="Exposure by region and level (counts only, no asset locations)")
def exposure(
    request: Request,
    start: dt.date | None = Query(default=None, alias="from"),
    end: dt.date | None = Query(default=None, alias="to"),
    granularity: str = Granularity,
    compare: str = Compare,
    event_type: str | None = Query(default=None, max_length=40),
    format: str = Format,
    principal: Principal = Depends(require(PLATFORM)),
    tx: Tx = Depends(get_tx),
) -> Response:
    period = an.parse_period(start, end, granularity, 30)

    def regions(p: an.Period) -> list[dict[str, Any]]:
        rows = tx.all(
            """SELECT region_of_country(a.country_code), x.level, count(*)::int, count(DISTINCT x.asset_id)::int, count(DISTINCT x.tenant_id)::int
                 FROM exposures x JOIN assets a ON a.id = x.asset_id JOIN events e ON e.id = x.event_id
                WHERE x.computed_at::date BETWEEN %s AND %s AND (%s::text IS NULL OR e.type = %s) GROUP BY 1, 2""",
            (p.start, p.end, event_type, event_type),
        )
        table: dict[str, dict[str, Any]] = {}
        for r in rows:
            e = table.setdefault(r[0], {"region": r[0], "levels": dict.fromkeys(LEVELS, 0), "exposures": 0, "assets_exposed": 0, "tenants": 0})
            e["levels"][r[1]] = r[2]
            e["exposures"] += r[2]
            e["assets_exposed"] += r[3]
            e["tenants"] = max(e["tenants"], r[4])
        return sorted(table.values(), key=lambda e: -e["exposures"])

    def build() -> dict[str, Any]:
        by_region = regions(period)
        series = tx.all(
            f"""SELECT {an.bucket(period.granularity, 'x.computed_at::date')}, x.level, count(*)::int FROM exposures x JOIN events e ON e.id = x.event_id
                 WHERE x.computed_at::date BETWEEN %s AND %s AND (%s::text IS NULL OR e.type = %s) GROUP BY 1, 2 ORDER BY 1""",  # noqa: S608
            (period.start, period.end, event_type, event_type),
        )
        buckets: dict[Any, dict[str, int]] = {}
        for p, lvl, n in series:
            buckets.setdefault(p, dict.fromkeys(LEVELS, 0))[lvl] = n
        payload: dict[str, Any] = {
            "from": period.start, "to": period.end, "granularity": granularity, "by_region": by_region,
            "series": [{"period": p, "levels": v, "total": sum(v.values())} for p, v in sorted(buckets.items())],
        }  # fmt: skip
        other = an.comparison_period(period, compare)
        if other:
            prev = regions(other)
            payload["comparison"] = {"from": other.start, "to": other.end, "by_region": prev}
        return payload

    payload = an.CACHE.get_or_compute(("p-exposure", scope_of(principal), period, compare, event_type), build)
    rows = [[r["region"], *[r["levels"][level] for level in LEVELS], r["exposures"], r["assets_exposed"]] for r in payload["by_region"]]
    return an.respond(request, payload, format, ["region", *LEVELS, "exposures", "assets_exposed"], rows, "exposure-by-region")


@router.get("/platform/analytics/alerts", summary="Alert levels over time, acknowledgement time, and dismissal rate across tenants")
def platform_alerts(
    request: Request,
    start: dt.date | None = Query(default=None, alias="from"),
    end: dt.date | None = Query(default=None, alias="to"),
    granularity: str = Granularity,
    compare: str = Compare,
    format: str = Format,
    principal: Principal = Depends(require(PLATFORM)),
    tx: Tx = Depends(get_tx),
) -> Response:
    period = an.parse_period(start, end, granularity, 90)

    def build() -> dict[str, Any]:
        series = ops_series(tx, period)
        t = totals(series)
        false_rate = tx.all(
            f"""SELECT {an.bucket(period.granularity, 'date')}, (sum(false_alert_rate * incidents_ingested) / NULLIF(sum(incidents_ingested), 0))::float8
                  FROM platform_stats_daily WHERE date BETWEEN %s AND %s GROUP BY 1 ORDER BY 1""",  # noqa: S608
            (period.start, period.end),
        )
        payload: dict[str, Any] = {
            "from": period.start, "to": period.end, "granularity": granularity, "series": series, "totals": t,
            "false_alert_rate": [{"period": r[0], "rate": round(r[1], 4) if r[1] is not None else None} for r in false_rate],
            "definition": "False alert rate comes from reviewer feedback on alerts that were not real disruptions, weighted by incidents ingested.",
        }  # fmt: skip
        other = an.comparison_period(period, compare)
        if other:
            prev = totals(ops_series(tx, other))
            payload["comparison"] = {"from": other.start, "to": other.end, "totals": prev, "changes": kpi_changes(t, prev)}
        return payload

    payload = an.CACHE.get_or_compute(("p-alerts", scope_of(principal), period, compare), build)
    cols = ["period", "alerts", *LEVELS, "acknowledged", "dismissed", "acknowledgement_rate", "avg_minutes_to_acknowledge"]
    return an.respond(request, payload, format, cols, [[i[c] for c in cols] for i in payload["series"]], "platform-alerts")


@router.get("/platform/analytics/quality", summary="Location confirmation, false alerts, detection delay, and corrections")
def platform_quality(
    request: Request,
    start: dt.date | None = Query(default=None, alias="from"),
    end: dt.date | None = Query(default=None, alias="to"),
    granularity: str = Granularity,
    compare: str = Compare,
    format: str = Format,
    principal: Principal = Depends(require(PLATFORM)),
    tx: Tx = Depends(get_tx),
) -> Response:
    period = an.parse_period(start, end, granularity, 90)

    def delay_vs_hazard(p: an.Period) -> dict[str, Any]:
        row = tx.one(
            """SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM (n.t - h.t)) / 60), count(*)
                 FROM (SELECT event_id, min(published_at) AS t FROM event_sources WHERE source_kind IN ('usgs', 'nws', 'firms') GROUP BY 1) h
                 JOIN (SELECT event_id, min(published_at) AS t FROM event_sources WHERE source_kind = 'news' GROUP BY 1) n ON n.event_id = h.event_id
                 JOIN events e ON e.id = h.event_id WHERE e.first_seen_at::date BETWEEN %s AND %s""",
            (p.start, p.end),
        )
        assert row is not None
        return {"events_with_both": row[1], "median_minutes_news_after_hazard_feed": round(float(row[0]), 1) if row[0] is not None else None}

    def build() -> dict[str, Any]:
        series = ops_series(tx, period)
        t = totals(series)
        delay = tx.all(
            f"""SELECT {an.bucket(period.granularity, 'date')}, avg(detection_delay_minutes_median)::float8, avg(false_alert_rate)::float8
                  FROM platform_stats_daily WHERE date BETWEEN %s AND %s GROUP BY 1 ORDER BY 1""",  # noqa: S608
            (period.start, period.end),
        )
        corrections = tx.all(
            "SELECT kind, status, count(*)::int FROM correction_requests WHERE created_at::date BETWEEN %s AND %s GROUP BY 1, 2 ORDER BY 1, 2", (period.start, period.end)
        )
        payload: dict[str, Any] = {
            "from": period.start, "to": period.end, "granularity": granularity,
            "location_confirmation": [{k: i[k] for k in ("period", "location_confirmed", "location_corrected", "location_confirmation_rate")} for i in series],
            "location_confirmation_rate": t["location_confirmation_rate"],
            "detection_delay_and_false_alerts": [
                {"period": r[0], "detection_delay_minutes_median": round(r[1], 1) if r[1] is not None else None, "false_alert_rate": round(r[2], 4) if r[2] is not None else None}
                for r in delay
            ],
            "detection_delay_vs_hazard_feeds": delay_vs_hazard(period),
            "corrections": [{"kind": c[0], "status": c[1], "count": c[2]} for c in corrections],
        }  # fmt: skip
        other = an.comparison_period(period, compare)
        if other:
            prev = totals(ops_series(tx, other))
            payload["comparison"] = {"from": other.start, "to": other.end, "location_confirmation_rate": an.change(t["location_confirmation_rate"], prev["location_confirmation_rate"]), "detection_delay_vs_hazard_feeds": delay_vs_hazard(other)}
        return payload

    payload = an.CACHE.get_or_compute(("p-quality", scope_of(principal), period, compare), build)
    rows = [[d["period"], d["detection_delay_minutes_median"], d["false_alert_rate"]] for d in payload["detection_delay_and_false_alerts"]]
    return an.respond(request, payload, format, ["period", "detection_delay_minutes_median", "false_alert_rate"], rows, "platform-quality")


@router.get("/platform/analytics/pipeline", summary="Routing breakdown, latency, source mix, and freshness")
def pipeline(
    request: Request,
    start: dt.date | None = Query(default=None, alias="from"),
    end: dt.date | None = Query(default=None, alias="to"),
    granularity: str = Granularity,
    compare: str = Compare,
    format: str = Format,
    principal: Principal = Depends(require(PLATFORM)),
    tx: Tx = Depends(get_tx),
) -> Response:
    period = an.parse_period(start, end, granularity, 30)

    def routing(p: an.Period) -> dict[str, int]:
        return {r[0] or "none": r[1] for r in tx.all("SELECT route, count(*)::int FROM mentions WHERE created_at::date BETWEEN %s AND %s GROUP BY 1", (p.start, p.end))}

    def build() -> dict[str, Any]:
        latency = tx.all(
            f"""SELECT {an.bucket(period.granularity, 'date')}, avg(p50_latency_ms)::float8, avg(p95_latency_ms)::float8
                  FROM platform_stats_daily WHERE date BETWEEN %s AND %s AND p50_latency_ms IS NOT NULL GROUP BY 1 ORDER BY 1""",  # noqa: S608
            (period.start, period.end),
        )
        mix = tx.all(
            """SELECT source_kind, count(*)::int, count(DISTINCT event_id)::int FROM event_sources
                WHERE COALESCE(published_at, created_at)::date BETWEEN %s AND %s GROUP BY 1 ORDER BY 2 DESC""",
            (period.start, period.end),
        )
        domains = tx.all(
            """SELECT domain, count(*)::int FROM event_sources WHERE domain IS NOT NULL AND COALESCE(published_at, created_at)::date BETWEEN %s AND %s
                GROUP BY 1 ORDER BY 2 DESC LIMIT 10""",
            (period.start, period.end),
        )
        fresh = tx.all(
            """SELECT source_kind, max(published_at), max(created_at), count(*)::int FROM event_sources GROUP BY 1 ORDER BY 1"""
        )
        now = dt.datetime.now(dt.UTC)
        route_now = routing(period)
        payload: dict[str, Any] = {
            "from": period.start, "to": period.end, "granularity": granularity, "routing_breakdown": route_now,
            "latency_ms": [{"period": r[0], "p50": round(r[1], 1), "p95": round(r[2], 1)} for r in latency],
            "source_mix": [{"source": r[0], "records": r[1], "events": r[2]} for r in mix],
            "top_domains": [{"domain": r[0], "records": r[1]} for r in domains],
            "freshness": [
                {"source": r[0], "latest_published_at": r[1], "latest_ingested_at": r[2], "records": r[3], "minutes_since_ingest": round((now - r[2]).total_seconds() / 60, 1) if r[2] else None}
                for r in fresh
            ],
        }  # fmt: skip
        other = an.comparison_period(period, compare)
        if other:
            payload["comparison"] = {"from": other.start, "to": other.end, "routing_breakdown": routing(other)}
        return payload

    payload = an.CACHE.get_or_compute(("p-pipeline", scope_of(principal), period, compare, dt.datetime.now(dt.UTC).strftime("%Y%m%d%H%M")), build)
    rows = [[i["period"], i["p50"], i["p95"]] for i in payload["latency_ms"]]
    return an.respond(request, payload, format, ["period", "p50_latency_ms", "p95_latency_ms"], rows, "pipeline-latency")
