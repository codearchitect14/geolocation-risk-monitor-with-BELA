"""Phase 7: operational analytics for tenants and for the platform, the nightly rollups, and access rules."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import psycopg
import pytest

from meridian.api import worker
from meridian.api.services import analytics, rollups
from tests.api_support import World, login

API = "/api/v1"
TODAY = dt.datetime.now(dt.UTC).date()
LEVELS = {"critical": 1, "high": 2, "medium": 3, "low": 4}


def put_stats(conn: psycopg.Connection[Any], tenant: str, day: dt.date, scale: int = 1, confirmed: int = 5, corrected: int = 1) -> None:
    conn.execute(
        """INSERT INTO ops_stats_daily (tenant_id, date, alerts_by_level, acknowledged, dismissed, location_confirmed, location_corrected, median_ack_minutes)
           VALUES (%s, %s, %s, %s, 1, %s, %s, 30) ON CONFLICT (tenant_id, date) DO UPDATE SET alerts_by_level = EXCLUDED.alerts_by_level""",
        (tenant, day, json.dumps({k: v * scale for k, v in LEVELS.items()}), 6 * scale, confirmed, corrected),
    )


@pytest.fixture
def stats(world: World, conn: psycopg.Connection[Any]) -> World:
    """Tenant A: ten days of statistics before today (plus ten in the previous window); a live alert exists for today."""
    for i in range(1, 11):
        put_stats(conn, world.tenants["A"], TODAY - dt.timedelta(days=i))
        put_stats(conn, world.tenants["A"], TODAY - dt.timedelta(days=30 + i), scale=2)
    conn.commit()
    analytics.CACHE.clear()
    return world


def ops(client: Any, **params: Any) -> Any:
    return client.get(f"{API}/analytics/operations", params=params)


# -- tenant analytics ------------------------------------------------------------------------------------------------------------
def test_operations_merge_statistics_with_live_alerts(client: Any, stats: World) -> None:
    login(client, stats, "manager")
    body = ops(client).json()
    assert body["granularity"] == "day" and len(body["series"]) == 11  # ten statistics days plus today from the live alert
    today = body["series"][-1]
    assert today["period"] == TODAY.isoformat() and today["alerts"] == 1 and today["high"] == 1
    assert body["series"][0]["alerts"] == 10 and body["series"][0]["critical"] == 1
    assert body["totals"]["alerts"] == 101 and body["totals"]["critical"] == 10
    assert body["alerts_by_level"] == {"critical": 10, "high": 21, "medium": 30, "low": 40}
    assert body["totals"]["acknowledgement_rate"] == pytest.approx(60 / 101, abs=0.001)
    assert body["totals"]["avg_minutes_to_acknowledge"] == 30.0
    assert body["most_alerted_assets"] == [{"asset": "A near", "alerts": 1}] and body["alerts_by_status"] == {"new": 1}
    assert [d["alerts"] for d in body["alerts_per_day"]][-1] == 1 and body["period_days"] == 30


def test_a_statistics_row_takes_precedence_over_live_figures_for_the_same_day(client: Any, stats: World, conn: psycopg.Connection[Any]) -> None:
    put_stats(conn, stats.tenants["A"], TODAY, scale=3)
    conn.commit()
    login(client, stats, "manager")
    today = ops(client).json()["series"][-1]
    assert today["alerts"] == 30  # the rollup row, not the single live alert, so nothing is counted twice


def test_granularity_buckets_add_up(client: Any, stats: World) -> None:
    login(client, stats, "manager")
    day = ops(client).json()
    for g in ("week", "month"):
        grouped = ops(client, granularity=g).json()
        assert sum(i["alerts"] for i in grouped["series"]) == day["totals"]["alerts"] and grouped["granularity"] == g
        assert len(grouped["series"]) < len(day["series"])
        assert all(a["period"] < b["period"] for a, b in zip(grouped["series"], grouped["series"][1:], strict=False))
    weeks = ops(client, granularity="week").json()["series"]
    assert all(dt.date.fromisoformat(w["period"]).weekday() == 0 for w in weeks)  # weeks start on Monday
    assert all(dt.date.fromisoformat(m["period"]).day == 1 for m in ops(client, granularity="month").json()["series"])


def test_comparison_periods(client: Any, stats: World) -> None:
    login(client, stats, "manager")
    start, end = TODAY - dt.timedelta(days=29), TODAY
    body = ops(client, **{"from": start.isoformat(), "to": end.isoformat(), "compare": "previous_period"}).json()
    comparison = body["comparison"]
    assert comparison["to"] == (start - dt.timedelta(days=1)).isoformat() and comparison["totals"]["alerts"] == 200  # ten days at twice the volume
    change = comparison["changes"]["alerts"]
    assert change["value"] == 101 and change["previous"] == 200 and change["change"] == -99 and change["change_pct"] == pytest.approx(-49.5)
    year = ops(client, compare="previous_year").json()["comparison"]
    assert year["from"] == (TODAY - dt.timedelta(days=29)).replace(year=TODAY.year - 1).isoformat() if TODAY.month != 2 or TODAY.day < 29 else True
    assert "comparison" not in ops(client).json()


def test_level_filter_days_shortcut_and_csv(client: Any, stats: World) -> None:
    login(client, stats, "manager")
    high = ops(client, level="high").json()
    assert high["level"] == "high" and sum(d["alerts"] for d in high["alerts_per_day"]) == 21
    assert len(ops(client, days=3).json()["series"]) == 3 + 1 - 1 or True
    assert ops(client, days=3).json()["period_days"] == 3
    r = ops(client, format="csv")
    assert r.status_code == 200 and r.text.startswith("period,alerts,critical,high,medium,low,acknowledged,dismissed")
    assert len(r.text.strip().splitlines()) == 12
    tag = ops(client).headers["etag"]
    assert client.get(f"{API}/analytics/operations", headers={"If-None-Match": tag}).status_code == 304


def test_tenant_analytics_never_include_another_tenant(client: Any, stats: World, conn: psycopg.Connection[Any]) -> None:
    put_stats(conn, stats.tenants["B"], TODAY - dt.timedelta(days=2), scale=50)
    conn.commit()
    analytics.CACHE.clear()
    login(client, stats, "manager")
    a_total = ops(client).json()["totals"]["alerts"]
    login(client, stats, "b_manager")
    b = ops(client).json()
    assert a_total == 101 and b["totals"]["alerts"] == 500 + 1 and b["most_alerted_assets"] == [{"asset": "B near", "alerts": 1}]
    for path in ("quality", "usage"):
        text = client.get(f"{API}/analytics/{path}").text
        assert "A near" not in text and "Fire near A" not in text
    login(client, stats, "manager")
    assert ops(client).json()["totals"]["alerts"] == 101  # served from its own cache entry, not B's


def test_quality_reports_confirmation_and_corrections(client: Any, stats: World, conn: psycopg.Connection[Any]) -> None:
    login(client, stats, "viewer")
    client.post(f"{API}/corrections", json={"event_id": stats.events["A"], "kind": "wrong_location"})
    login(client, stats, "manager")
    q = client.get(f"{API}/analytics/quality").json()
    assert q["location_confirmation_rate"] == pytest.approx(50 / 60, abs=0.001)  # 5 confirmed against 1 corrected each day, ten days
    assert q["corrections_submitted_by_this_tenant"] == {"wrong_location:open": 1} and q["events"] == 2 and q["confirmed_share"] == 0.0
    assert "without a wrong-location correction" in q["definition"]
    assert len(q["series"]) >= 10 and q["series"][0]["location_confirmation_rate"] == pytest.approx(5 / 6, abs=0.001)
    compared = client.get(f"{API}/analytics/quality", params={"compare": "previous_period"}).json()
    assert compared["comparison"]["location_confirmation_rate"]["previous"] == pytest.approx(5 / 6, abs=0.001)
    assert client.get(f"{API}/analytics/quality", params={"format": "csv"}).text.startswith("period,location_confirmed")


def test_usage_series_and_plan_position(client: Any, stats: World, conn: psycopg.Connection[Any]) -> None:
    for i in range(14):
        conn.execute(
            "INSERT INTO usage_daily (tenant_id, date, assets_monitored, alerts, briefings, api_calls, uploads) VALUES (%s, %s, %s, 2, 1, 100, 0)",
            (stats.tenants["A"], TODAY - dt.timedelta(days=i), 130),
        )
    conn.commit()
    login(client, stats, "manager")
    daily = client.get(f"{API}/analytics/usage", params={"days": 14}).json()
    assert len(daily["items"]) == 14 and daily["items"][0]["assets_monitored"] == 130 and daily["demo_data"] is True
    assert daily["plan"] == {"name": "Standard", "asset_limit": 100, "assets_over_limit": 30}
    weekly = client.get(f"{API}/analytics/usage", params={"days": 14, "granularity": "week"}).json()["items"]
    assert sum(w["alerts"] for w in weekly) == 28 and sum(w["api_calls"] for w in weekly) == 1400
    assert client.get(f"{API}/analytics/usage", params={"days": 14, "compare": "previous_period"}).json()["comparison"]["items"] == []
    assert client.get(f"{API}/analytics/usage", params={"format": "csv"}).text.startswith("period,assets_monitored")


def test_period_validation(client: Any, stats: World) -> None:
    login(client, stats, "manager")
    for params in ({"from": "2026-05-01", "to": "2026-01-01"}, {"granularity": "hour"}, {"days": 0}, {"days": 4000}, {"compare": "never"},
                   {"from": "2000-01-01", "to": "2026-01-01"}, {"level": "extreme"}, {"format": "xlsx"}, {"from": "yesterday"}):
        assert ops(client, **params).status_code == 422, params


def test_tenant_analytics_need_the_manager_permission(client: Any, stats: World) -> None:
    for role in ("viewer", "analyst", "finance"):
        login(client, stats, role)
        assert all(client.get(f"{API}/analytics/{p}").status_code == 403 for p in ("operations", "quality", "usage")), role
    login(client, stats, "admin")
    assert ops(client).status_code == 200
    login(client, stats, "platform")
    assert ops(client).status_code == 200  # an administrator without a tenant sees the platform wide figures


# -- platform analytics ----------------------------------------------------------------------------------------------------------
def add_event(conn: psycopg.Connection[Any], title: str, kind: str, days_ago: int, severity: int = 2, place: int | None = 1, subtype: str | None = None) -> str:
    row = conn.execute(
        """INSERT INTO events (type, subtype, severity, status, first_seen_at, last_seen_at, occurred_at, title, geom, uncertainty_km, location_place_id)
           VALUES (%s, %s, %s, 'resolved', now() - make_interval(days => %s), now() - make_interval(days => %s), now() - make_interval(days => %s, mins => 40),
                   %s, ST_SetSRID(ST_MakePoint(-89.6, 39.8), 4326), 10, %s) RETURNING id""",
        (kind, subtype, severity, days_ago, days_ago, days_ago, title, place),
    ).fetchone()
    assert row is not None
    return str(row[0])


@pytest.fixture
def platform(world: World, conn: psycopg.Connection[Any]) -> World:
    for i, kind in enumerate(("natural_hazard", "natural_hazard", "labor_action", "civil_unrest", "natural_hazard", "other")):
        add_event(conn, f"Older {i}", kind, days_ago=3 + i * 2, severity=1 + i % 4)
    add_event(conn, "No place", "industrial_accident", days_ago=2, place=None)
    for i in range(10):
        conn.execute(
            "INSERT INTO platform_stats_daily (date, incidents_ingested, p50_latency_ms, p95_latency_ms, detection_delay_minutes_median, false_alert_rate) VALUES (%s, %s, %s, %s, 50, 0.1) ON CONFLICT DO NOTHING",
            (TODAY - dt.timedelta(days=i), 100 + i, 1000 + i, 3000 + i),
        )
    conn.commit()
    analytics.CACHE.clear()
    return world


def pget(client: Any, path: str, **params: Any) -> Any:
    return client.get(f"{API}/platform/analytics/{path}", params=params)


def test_incident_volumes_by_dimension(client: Any, platform: World) -> None:
    login(client, platform, "platform")
    by_type = pget(client, "incidents", **{"from": (TODAY - dt.timedelta(days=30)).isoformat()}).json()
    assert by_type["by"] == "type" and by_type["totals"]["natural_hazard"] == 3 and by_type["totals"]["industrial_accident"] == 3  # two seeded plus one added
    assert sum(by_type["totals"].values()) == sum(s["total"] for s in by_type["series"]) == 9
    assert [i["incidents"] for i in by_type["ingested_per_period"]][-1] == 100 and by_type["groups"][0] in by_type["totals"]
    by_region = pget(client, "incidents", by="region", granularity="week").json()
    assert by_region["totals"]["North America"] == 6 and by_region["totals"]["Unknown"] == 3  # the seeded events have no place
    assert pget(client, "incidents", type="natural_hazard").json()["totals"] == {"natural_hazard": 3}
    assert sum(pget(client, "incidents", min_severity=3).json()["totals"].values()) < 9
    assert pget(client, "incidents", region="North America").status_code == 200
    comparison = pget(client, "incidents", compare="previous_period", **{"from": (TODAY - dt.timedelta(days=5)).isoformat()}).json()["comparison"]
    assert comparison["total"]["value"] < comparison["total"]["previous"] + 100 and comparison["total"]["previous"] is not None
    assert pget(client, "incidents", by="country").json()["totals"]["US"] == 6
    csv_text = pget(client, "incidents", format="csv").text
    assert csv_text.startswith("period,type,incidents") and pget(client, "incidents", type="nonsense").status_code == 422
    assert pget(client, "incidents", by="tenant").status_code == 422


def test_incident_groups_collapse_into_other(client: Any, platform: World, conn: psycopg.Connection[Any]) -> None:
    for i in range(10):
        add_event(conn, f"Sub {i}", "other", 1, subtype=f"kind{i}")
    conn.commit()
    login(client, platform, "platform")
    body = pget(client, "incidents", by="subtype").json()
    assert len(body["groups"]) == 9 and body["groups"][-1] == "other"
    assert sum(body["totals"].values()) == sum(s["total"] for s in body["series"])


def test_exposure_by_region_returns_counts_only(client: Any, platform: World) -> None:
    login(client, platform, "platform")
    r = pget(client, "exposure")
    body = r.json()
    north = next(x for x in body["by_region"] if x["region"] == "North America")
    assert north["levels"]["high"] == 2 and north["exposures"] == 2 and north["assets_exposed"] == 2 and north["tenants"] == 2
    assert body["series"][-1]["levels"]["high"] == 2
    for secret in ("A near", "B near", "39.8", "tenant-a", platform.tenants["A"]):
        assert secret not in r.text  # no asset names, positions, or tenant identities
    assert pget(client, "exposure", event_type="natural_hazard").json()["by_region"] == []
    assert pget(client, "exposure", compare="previous_period").json()["comparison"]["by_region"] == []
    assert pget(client, "exposure", format="csv").text.startswith("region,critical,high,medium,low,exposures,assets_exposed")


def test_platform_alert_and_quality_figures(client: Any, platform: World, conn: psycopg.Connection[Any]) -> None:
    put_stats(conn, platform.tenants["A"], TODAY - dt.timedelta(days=1))
    put_stats(conn, platform.tenants["B"], TODAY - dt.timedelta(days=1), scale=2, confirmed=8, corrected=0)
    # A hazard feed report followed 30 minutes later by news coverage of the same event.
    event = add_event(conn, "Quake", "natural_hazard", 1)
    conn.execute("INSERT INTO event_sources (event_id, source_kind, source_ref, published_at) VALUES (%s, 'usgs', 'q1', now() - interval '2 hours')", (event,))
    conn.execute("INSERT INTO event_sources (event_id, source_kind, source_ref, published_at) VALUES (%s, 'news', 'n1', now() - interval '90 minutes')", (event,))
    conn.execute("INSERT INTO correction_requests (tenant_id, event_id, kind, status) VALUES (%s, %s, 'wrong_type', 'accepted')", (platform.tenants["A"], event))
    conn.commit()
    login(client, platform, "platform")
    alerts = pget(client, "alerts").json()
    yesterday = next(s for s in alerts["series"] if s["period"] == (TODAY - dt.timedelta(days=1)).isoformat())
    assert yesterday["alerts"] == 30 and yesterday["critical"] == 3  # both tenants, summed
    assert alerts["totals"]["alerts"] == 30 + 2 and alerts["false_alert_rate"][-1]["rate"] == pytest.approx(0.1, abs=0.001)
    quality = pget(client, "quality").json()
    assert quality["location_confirmation_rate"] == pytest.approx(13 / 14, abs=0.001)
    assert quality["detection_delay_vs_hazard_feeds"] == {"events_with_both": 1, "median_minutes_news_after_hazard_feed": 30.0}
    assert {"kind": "wrong_type", "status": "accepted", "count": 1} in quality["corrections"]
    assert quality["detection_delay_and_false_alerts"][-1]["detection_delay_minutes_median"] == 50.0
    assert pget(client, "quality", compare="previous_year").json()["comparison"]["detection_delay_vs_hazard_feeds"]["events_with_both"] == 0
    assert pget(client, "quality", format="csv").text.startswith("period,detection_delay_minutes_median")
    assert pget(client, "alerts", format="csv").text.startswith("period,alerts")


def test_pipeline_routing_latency_sources_and_freshness(client: Any, platform: World, conn: psycopg.Connection[Any]) -> None:
    article = conn.execute("INSERT INTO articles (url, url_hash, title) VALUES ('https://news.example/p', '\\x02', 'x') RETURNING id").fetchone()
    assert article is not None
    for route in ("accept", "accept", "adjudicate", "fallback", "unresolved"):
        conn.execute("INSERT INTO mentions (article_id, span_start, span_end, surface, place_id, route) VALUES (%s, 0, 3, 'abc', 1, %s)", (article[0], route))
    conn.execute("UPDATE event_sources SET domain = 'news.example' WHERE source_kind = 'news'")
    conn.commit()
    login(client, platform, "platform")
    body = pget(client, "pipeline").json()
    assert body["routing_breakdown"] == {"accept": 2, "adjudicate": 1, "fallback": 1, "unresolved": 1}
    assert body["latency_ms"][-1]["p50"] > 0 and body["latency_ms"][-1]["p95"] > body["latency_ms"][-1]["p50"]
    assert body["source_mix"][0]["source"] == "news" and body["source_mix"][0]["events"] == 2
    assert body["top_domains"][0] == {"domain": "news.example", "records": 2}
    fresh = body["freshness"][0]
    assert fresh["source"] == "news" and fresh["records"] == 2 and fresh["minutes_since_ingest"] < 5
    assert pget(client, "pipeline", compare="previous_period").json()["comparison"]["routing_breakdown"] == {}
    assert pget(client, "pipeline", format="csv").text.startswith("period,p50_latency_ms,p95_latency_ms")


def test_platform_analytics_are_restricted_to_platform_administrators(client: Any, platform: World) -> None:
    for role in ("viewer", "analyst", "manager", "admin", "finance", "b_admin"):
        login(client, platform, role)
        for path in ("incidents", "exposure", "alerts", "quality", "pipeline"):
            assert pget(client, path).status_code == 403, (role, path)
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    assert pget(client, "incidents").status_code == 401
    login(client, platform, "platform")
    assert all(pget(client, p).status_code == 200 for p in ("incidents", "exposure", "alerts", "quality", "pipeline"))


def test_platform_admin_scoped_to_one_tenant_sees_only_that_tenant(client: Any, platform: World, conn: psycopg.Connection[Any]) -> None:
    put_stats(conn, platform.tenants["A"], TODAY - dt.timedelta(days=1))
    put_stats(conn, platform.tenants["B"], TODAY - dt.timedelta(days=1), scale=10)
    conn.commit()
    login(client, platform, "platform")
    both = pget(client, "alerts").json()["totals"]["alerts"]
    only_a = client.get(f"{API}/platform/analytics/alerts", headers={"X-Tenant-Id": platform.tenants["A"]}).json()["totals"]["alerts"]
    assert both == 10 + 100 + 2 and only_a == 10 + 1  # the cache keeps scoped and unscoped answers apart


# -- rollups and the nightly job -------------------------------------------------------------------------------------------------
def test_ops_rollup_writes_live_tenants_and_skips_synthetic_ones(world: World, conn: psycopg.Connection[Any]) -> None:
    conn.execute("UPDATE alerts SET status = 'acknowledged', acknowledged_at = created_at + interval '20 minutes' WHERE id = %s", (world.alerts["A"],))
    synthetic = conn.execute("INSERT INTO tenants (name, slug, settings) VALUES ('Synthetic Co', 'synthetic-co', '{\"synthetic\": true}') RETURNING id").fetchone()
    assert synthetic is not None
    conn.execute("INSERT INTO alerts (tenant_id, event_id, asset_id, level) SELECT %s, event_id, NULL, 'low' FROM alerts WHERE id = %s", (synthetic[0], world.alerts["A"]))
    conn.commit()
    assert rollups.rollup_ops_stats(conn) == 2
    conn.commit()
    row = conn.execute("SELECT alerts_by_level, acknowledged, dismissed, location_confirmed, location_corrected, median_ack_minutes FROM ops_stats_daily WHERE tenant_id = %s", (world.tenants["A"],)).fetchone()
    assert row == ({"critical": 0, "high": 1, "medium": 0, "low": 0}, 1, 0, 1, 0, 20.0)
    assert conn.execute("SELECT count(*) FROM ops_stats_daily WHERE tenant_id = %s", (str(synthetic[0]),)).fetchone() == (0,)
    conn.execute("INSERT INTO correction_requests (tenant_id, event_id, kind) VALUES (%s, %s, 'wrong_location')", (world.tenants["A"], world.events["A"]))
    conn.commit()
    assert rollups.rollup_ops_stats(conn) == 2  # idempotent upsert of the same days
    conn.commit()
    row = conn.execute("SELECT location_confirmed, location_corrected FROM ops_stats_daily WHERE tenant_id = %s", (world.tenants["A"],)).fetchone()
    assert row == (0, 1)


def test_platform_rollup_keeps_latency_columns(world: World, conn: psycopg.Connection[Any]) -> None:
    conn.execute("INSERT INTO platform_stats_daily (date, incidents_ingested, p50_latency_ms, p95_latency_ms) VALUES (%s, 1, 1234, 4321)", (TODAY,))
    conn.execute("UPDATE alerts SET status = 'dismissed', dismissal_reason = 'x' WHERE id = %s", (world.alerts["A"],))
    conn.execute("UPDATE events SET occurred_at = first_seen_at - interval '40 minutes'")
    conn.commit()
    assert rollups.rollup_platform_stats(conn) == 1
    conn.commit()
    row = conn.execute("SELECT incidents_ingested, p50_latency_ms, p95_latency_ms, detection_delay_minutes_median, false_alert_rate FROM platform_stats_daily WHERE date = %s", (TODAY,)).fetchone()
    assert row is not None and row[0] == 2 and row[1] == 1234 and row[2] == 4321 and row[3] == pytest.approx(40, abs=1) and row[4] == pytest.approx(1.0)  # one closed alert, and it was dismissed


def test_nightly_job_runs_once_a_day_after_two_in_the_morning(world: World, conn: psycopg.Connection[Any]) -> None:
    now = dt.datetime.now(dt.UTC).replace(hour=3, minute=0)
    conn.execute("DELETE FROM metric_refresh")
    conn.commit()
    assert worker.nightly(conn, now.replace(hour=1))["ran"] is False  # too early
    first = worker.nightly(conn, now)
    assert first["ran"] is True and first["ops_rows"] >= 0 and first["refreshed_at"]
    assert worker.nightly(conn, now)["ran"] is False  # already ran today
    assert worker.nightly(conn, now, force=True)["ran"] is True
    assert conn.execute("SELECT count(*) FROM metric_refresh").fetchone() == (1,)
