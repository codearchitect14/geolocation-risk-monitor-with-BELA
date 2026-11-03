"""Phase 7: the synthetic business history, its loader, the metric views, and the demo asset generator."""

from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import psycopg
import pytest

import generate_demo_business_data as gen
from meridian.business import assets as demo_assets
from meridian.business import loader
from tests.api_support import World
from tests.business_support import last_complete_month_end


# -- generator -----------------------------------------------------------------------------------------------------------------
def test_generation_is_deterministic(tmp_path: Path) -> None:
    for name in ("a", "b"):
        gen.write_csv(gen.generate(months=12, logo_scale=0.5), tmp_path / name)
    for csv_name in gen.FILES:
        assert (tmp_path / "a" / f"{csv_name}.csv").read_bytes() == (tmp_path / "b" / f"{csv_name}.csv").read_bytes(), csv_name
    other = gen.generate(seed=7, months=12, logo_scale=0.5)
    assert [t["name"] for t in other["tenants"]] != [t["name"] for t in gen.generate(months=12, logo_scale=0.5)["tenants"]]


def test_full_history_meets_the_acceptance_rules() -> None:
    data = gen.generate()
    assert gen.verify(data, gen.MONTHS, gen.END) == []
    arr = gen.ending_arr(data, gen.END)
    assert 5_000_000 <= arr <= 9_000_000  # the specified ending ARR envelope
    names = [t["name"] for t in data["tenants"]]
    assert len(names) == len(set(names)) and all(" " in n for n in names)
    assert min(t["created_at"] for t in data["tenants"]) >= dt.date(2023, 11, 1)
    # Plan mix at signup is roughly 50, 35, and 15 percent; regions roughly 40, 30, 25, and 5 percent.
    first_plans = defaultdict(int)
    for s in data["subscriptions"]:
        if s["change_reason"] == "new":
            first_plans[s["plan"]] += 1
    total = sum(first_plans.values())
    assert 0.40 < first_plans["starter"] / total < 0.60 and 0.08 < first_plans["enterprise"] / total < 0.25
    regions = defaultdict(int)
    for t in data["tenants"]:
        regions[t["region"]] += 1
    assert regions["North America"] > regions["EMEA"] > regions["LATAM"]
    # New logos per month grow from about 2 to about 7.
    per_month = defaultdict(int)
    for t in data["tenants"]:
        per_month[(t["created_at"].year, t["created_at"].month)] += 1
    ordered = [per_month[k] for k in sorted(per_month)]
    assert sum(ordered[:6]) / 6 < sum(ordered[-6:]) / 6


def test_invoices_reconcile_to_subscriptions_plus_overage() -> None:
    data = gen.generate(months=24, logo_scale=0.6)
    subs = defaultdict(list)
    for s in data["subscriptions"]:
        subs[s["tenant_id"]].append(s)
    usage = {(u["tenant_id"], u["date"]): u["assets_monitored"] for u in data["usage_daily"]}
    lines = defaultdict(list)
    for line in data["invoice_lines"]:
        lines[line["invoice_id"]].append(line)
    checked = 0
    for invoice in data["invoices"]:
        parts = lines[invoice["id"]]
        assert abs(invoice["total"] - sum(p["amount"] for p in parts)) < 0.011
        month_end = gen.month_end(invoice["period_start"])
        sub = gen.active_sub(subs[invoice["tenant_id"]], month_end)
        assert sub is not None
        by_type = {p["line_type"]: p["amount"] for p in parts}
        if "subscription" in by_type:
            assert by_type["subscription"] == sub["price"]
        expected_overage = gen.overage_for(sub["plan"], usage.get((invoice["tenant_id"], month_end), 0))
        assert by_type.get("overage", 0.0) == expected_overage
        if "credit" in by_type:
            assert by_type["credit"] < 0
        assert invoice["status"] in {"paid", "open", "overdue"} and (invoice["status"] == "paid") == (invoice["paid_at"] is not None)
        checked += 1
    assert checked > 200
    assert any(i["status"] == "overdue" for i in data["invoices"]) and any(p["line_type"] == "overage" for p in data["invoice_lines"])


def test_subscription_history_is_contiguous_and_consistent() -> None:
    data = gen.generate(months=24, logo_scale=0.6)
    by_tenant = defaultdict(list)
    for s in data["subscriptions"]:
        by_tenant[s["tenant_id"]].append(s)
    assert any(len(v) > 1 for v in by_tenant.values())  # some tenants changed plan or price
    reasons = {s["change_reason"] for s in data["subscriptions"]}
    assert {"new", "expansion"} <= reasons
    churned = {t["id"]: t["churned_at"] for t in data["tenants"] if t["churned_at"]}
    assert churned
    for tenant_id, when in churned.items():
        last = sorted(by_tenant[tenant_id], key=lambda s: s["start"])[-1]
        assert last["end"] is not None and when == last["end"] + dt.timedelta(days=1)
    for s in data["subscriptions"]:
        assert s["price"] > 0 and (s["end"] is None or s["end"] >= s["start"])
        if s["billing_cycle"] == "annual":
            assert s["price"] > 1000 or s["plan"] == "starter"


def test_usage_and_statistics_trends() -> None:
    data = gen.generate(months=24, logo_scale=0.6)
    plat = data["platform_stats_daily"]
    early, late = plat[:90], plat[-90:]
    assert sum(r["detection_delay_minutes_median"] for r in early) / 90 > sum(r["detection_delay_minutes_median"] for r in late) / 90
    assert sum(r["false_alert_rate"] for r in early) / 90 > sum(r["false_alert_rate"] for r in late) / 90
    assert all(r["p95_latency_ms"] > r["p50_latency_ms"] > 0 for r in plat)
    # Storm season months have more alerts per asset than spring months.
    by_month: dict[int, list[float]] = defaultdict(list)
    for u in data["usage_daily"]:
        if u["assets_monitored"]:
            by_month[u["date"].month].append(u["alerts"] / u["assets_monitored"])
    assert sum(by_month[9]) / len(by_month[9]) > sum(by_month[4]) / len(by_month[4])
    for row in data["ops_stats_daily"][:2000]:
        assert row["acknowledged"] + row["dismissed"] <= sum(row["alerts_by_level"].values()) + row["acknowledged"]
        assert row["location_confirmed"] + row["location_corrected"] <= row["acknowledged"]
    assert {e["label"].split(":")[0] for e in data["business_events"]} >= {"Pricing change", "Product launch", "New data source"}


# -- loader and metric views ------------------------------------------------------------------------------------------------------
def load(conn: psycopg.Connection[Any], directory: Path) -> dict[str, int]:
    return loader.load(conn, directory)


def test_loader_replaces_only_synthetic_rows(world: World, conn: psycopg.Connection[Any], small_files: Path) -> None:
    first = load(conn, small_files)
    second = load(conn, small_files)
    assert first == second and first["tenants"] > 20
    row = conn.execute("SELECT count(*) FROM tenants WHERE settings->>'synthetic' = 'true'").fetchone()
    assert row == (first["tenants"],)
    assert conn.execute("SELECT count(*) FROM tenants WHERE id = ANY(%s::uuid[])", (list(world.tenants.values()),)).fetchone() == (2,)
    assert conn.execute("SELECT count(*) FROM subscriptions WHERE tenant_id = ANY(%s::uuid[])", (list(world.tenants.values()),)).fetchone() == (2,)
    assert conn.execute("SELECT count(*) FROM usage_daily").fetchone() == (first["usage_daily"],)
    with pytest.raises(FileNotFoundError):
        loader.load(conn, small_files / "nowhere")


def python_mrr_by_month(directory: Path) -> dict[dt.date, float]:
    """MRR per month computed straight from the CSV, independently of the SQL views."""
    import csv

    subs = list(csv.DictReader((directory / "subscriptions.csv").open()))
    start = min(dt.date.fromisoformat(s["start"]) for s in subs)
    out: dict[dt.date, float] = {}
    month = start.replace(day=1)
    last = last_complete_month_end().replace(day=1)
    while month <= last:
        end = gen.month_end(month)
        total = 0.0
        for s in subs:
            if dt.date.fromisoformat(s["start"]) <= end and (not s["end"] or dt.date.fromisoformat(s["end"]) >= end):
                total += float(s["price"]) / 12 if s["billing_cycle"] == "annual" else float(s["price"])
        out[month] = total
        month = gen.add_months(month, 1)
    return out


def test_mrr_view_matches_an_independent_calculation(world: World, conn: psycopg.Connection[Any], small_files: Path) -> None:
    load(conn, small_files)
    expected = python_mrr_by_month(small_files)
    rows = conn.execute(
        """SELECT m.month, sum(m.mrr), count(*) FROM tenant_mrr_monthly m JOIN tenants t ON t.id = m.tenant_id
            WHERE t.settings->>'synthetic' = 'true' GROUP BY m.month"""
    ).fetchall()
    got = {r[0]: float(r[1]) for r in rows}
    assert set(got) == set(expected) and len(got) >= 24
    for month, value in expected.items():
        assert got[month] == pytest.approx(value, abs=0.05), month
    total = conn.execute("SELECT mrr, arr FROM mrr_monthly ORDER BY month DESC LIMIT 1").fetchone()
    assert total is not None and float(total[1]) == pytest.approx(float(total[0]) * 12, abs=0.05)


def test_movements_add_up_to_the_change_in_mrr_every_month(world: World, conn: psycopg.Connection[Any], full_files: Path) -> None:
    """Exit criterion: the sum of movements equals the MRR delta for every month."""
    load(conn, full_files)
    rows = conn.execute(
        """SELECT month, mrr - COALESCE(lag(mrr) OVER (ORDER BY month), 0) AS delta, net_new_mrr,
                  new_mrr + expansion_mrr - contraction_mrr - churned_mrr AS parts
             FROM mrr_monthly ORDER BY month"""
    ).fetchall()
    assert len(rows) >= 36
    for month, delta, net_new, parts in rows:
        assert abs(delta - net_new) < 0.005 and abs(net_new - parts) < 0.005, month
    per_type = conn.execute("SELECT movement, count(*), sum(amount) FROM mrr_movements GROUP BY 1").fetchall()
    kinds = {r[0]: r for r in per_type}
    assert set(kinds) == {"new", "expansion", "contraction", "churn"}
    assert kinds["new"][2] > 0 and kinds["expansion"][2] > 0 and kinds["contraction"][2] < 0 and kinds["churn"][2] < 0
    # A region slice reconciles as well: its movements add up to the change in that region's MRR.
    row = conn.execute(
        """WITH s AS (SELECT month, sum(mrr) AS mrr FROM tenant_mrr_monthly WHERE region = 'EMEA' GROUP BY month),
                d AS (SELECT month, sum(amount) AS moved FROM mrr_movements WHERE region = 'EMEA' GROUP BY month),
                j AS (SELECT s.month, s.mrr - COALESCE(lag(s.mrr) OVER (ORDER BY s.month), 0) AS delta, COALESCE(d.moved, 0) AS moved
                        FROM s LEFT JOIN d USING (month))
           SELECT count(*) FROM j WHERE abs(delta - moved) > 0.005"""
    ).fetchone()
    assert row == (0,)


def test_retention_cohorts_and_dimensions(world: World, conn: psycopg.Connection[Any], small_files: Path) -> None:
    load(conn, small_files)
    # Net and gross retention for one month, recomputed by hand from tenant level MRR.
    month = conn.execute("SELECT max(month) FROM retention_monthly").fetchone()
    assert month is not None and month[0] is not None
    then = conn.execute("SELECT tenant_id, mrr FROM tenant_mrr_monthly WHERE month = %s::date - interval '12 months'", (month[0],)).fetchall()
    now = dict(conn.execute("SELECT tenant_id, mrr FROM tenant_mrr_monthly WHERE month = %s", (month[0],)).fetchall())
    base = sum(float(m) for _, m in then)
    nrr = sum(float(now.get(t, 0)) for t, _ in then) / base
    grr = sum(min(float(now.get(t, 0)), float(m)) for t, m in then) / base
    stored = conn.execute("SELECT nrr, grr, base_customers FROM retention_monthly WHERE month = %s", (month[0],)).fetchone()
    assert stored is not None and abs(float(stored[0]) - nrr) < 0.0001 and abs(float(stored[1]) - grr) < 0.0001 and stored[2] == len(then)
    assert float(stored[1]) <= 1.0 and float(stored[1]) <= float(stored[0])
    # Cohorts: month zero holds every customer of the cohort, and counts never exceed it.
    bad = conn.execute(
        """SELECT count(*) FROM cohort_retention c WHERE (c.months_since = 0 AND c.customers_active <> c.cohort_customers)
                                                   OR c.customers_active > c.cohort_customers"""
    ).fetchone()
    assert bad == (0,)
    # Every dimension adds up to total MRR.
    for dimension in ("plan", "region", "industry", "channel", "country", "billing_cycle"):
        mismatched = conn.execute(
            """SELECT count(*) FROM (SELECT d.month, sum(d.mrr) AS s, max(m.mrr) AS total FROM revenue_by_dimension d JOIN mrr_monthly m ON m.month = d.month
                                      WHERE d.dimension = %s GROUP BY d.month) x WHERE abs(s - total) > 0.01""",
            (dimension,),
        ).fetchone()
        assert mismatched == (0,), dimension


def test_unit_economics_follow_the_definitions(world: World, conn: psycopg.Connection[Any], small_files: Path) -> None:
    load(conn, small_files)
    r = conn.execute(
        """SELECT u.month, u.arpa, u.logo_churn_rate, u.quick_ratio, u.cac, u.cac_trailing_3m, u.payback_months, u.ltv,
                  m.mrr, m.customers, m.new_customers, m.churned_customers, m.new_mrr, m.expansion_mrr, m.contraction_mrr, m.churned_mrr
             FROM unit_economics_monthly u JOIN mrr_monthly m ON m.month = u.month
            WHERE m.contraction_mrr + m.churned_mrr > 0 AND m.new_customers > 0 ORDER BY u.month DESC LIMIT 1"""
    ).fetchone()
    assert r is not None
    month, arpa, churn, quick, cac, cac3, payback, ltv, mrr, customers, new_c, churned_c, new_mrr, exp, con, churned = r
    assert abs(float(arpa) - float(mrr) / customers) < 0.01
    assert abs(float(quick) - float(new_mrr + exp) / float(con + churned)) < 0.01
    spend = conn.execute("SELECT sum(spend) FROM marketing_spend WHERE month = %s", (month,)).fetchone()
    assert spend is not None and abs(float(cac) - float(spend[0]) / new_c) < 0.01
    spend3 = conn.execute("SELECT sum(spend) FROM marketing_spend WHERE month BETWEEN %s::date - interval '2 months' AND %s", (month, month)).fetchone()
    new3 = conn.execute("SELECT sum(new_customers) FROM mrr_monthly WHERE month BETWEEN %s::date - interval '2 months' AND %s", (month, month)).fetchone()
    assert spend3 is not None and new3 is not None and abs(float(cac3) - float(spend3[0]) / float(new3[0])) < 0.01
    assert abs(float(payback) - float(cac3) / (float(arpa) * 0.8)) < 0.02  # the fixed gross margin assumption
    ch3 = conn.execute("SELECT sum(churned_customers) FROM mrr_monthly WHERE month BETWEEN %s::date - interval '2 months' AND %s", (month, month)).fetchone()
    prev3 = conn.execute(
        "SELECT sum(customers) FROM mrr_monthly WHERE month BETWEEN %s::date - interval '3 months' AND %s::date - interval '1 month'", (month, month)
    ).fetchone()
    assert ch3 is not None and prev3 is not None
    if float(ch3[0]) > 0:
        assert abs(float(ltv) - float(arpa) * 0.8 / (float(ch3[0]) / float(prev3[0]))) / float(ltv) < 0.01
    assert churn is None or 0 <= float(churn) < 1


def test_overage_is_reported_apart_from_mrr(world: World, conn: psycopg.Connection[Any], small_files: Path) -> None:
    load(conn, small_files)
    overage = conn.execute("SELECT sum(overage) FROM overage_monthly").fetchone()
    assert overage is not None and float(overage[0]) > 0
    lines = conn.execute("SELECT sum(amount) FROM invoice_lines WHERE line_type = 'overage'").fetchone()
    assert lines is not None and abs(float(overage[0]) - float(lines[0])) < 0.01
    # MRR counts recurring fees only: it matches subscriptions and ignores invoice overage lines entirely.
    top = conn.execute("SELECT mrr FROM mrr_monthly ORDER BY month DESC LIMIT 1").fetchone()
    assert top is not None
    fees = conn.execute(
        "SELECT sum(CASE WHEN billing_cycle = 'annual' THEN price / 12 ELSE price END) FROM subscriptions WHERE end_date IS NULL"
    ).fetchone()
    assert fees is not None and abs(float(top[0]) - float(fees[0])) < 0.05


def test_metric_views_are_invisible_to_tenant_roles(world: World, conn: psycopg.Connection[Any], small_files: Path) -> None:
    load(conn, small_files)

    def visible(role: str, tenant: str | None) -> int:
        conn.execute("SET LOCAL ROLE meridian_app")
        conn.execute("SELECT set_config('app.role', %s, true), set_config('app.tenant_id', %s, true), set_config('app.bypass', 'off', true)", (role, tenant or ""))
        total = 0
        for view in ("mrr_monthly_v", "tenant_mrr_monthly_v", "mrr_movements_v", "retention_monthly_v", "cohort_retention_v", "revenue_by_dimension_v", "unit_economics_monthly_v", "overage_monthly_v"):
            total += conn.execute(f"SELECT count(*) FROM {view}").fetchone()[0]  # type: ignore[index]  # noqa: S608
        conn.rollback()
        return total

    assert visible("manager", world.tenants["A"]) == 0 and visible("tenant_admin", world.tenants["A"]) == 0 and visible("viewer", world.tenants["A"]) == 0
    assert visible("finance_analyst", None) > 100 and visible("platform_admin", None) > 100
    conn.execute("SET LOCAL ROLE meridian_app")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("SELECT * FROM mrr_monthly")  # the materialized views themselves have no grant
    conn.rollback()


def test_refresh_function_records_a_timestamp(world: World, conn: psycopg.Connection[Any], small_files: Path) -> None:
    load(conn, small_files)
    row = conn.execute("SELECT refreshed_at FROM metric_refresh WHERE name = 'metrics'").fetchone()
    assert row is not None and (dt.datetime.now(dt.UTC) - row[0]).total_seconds() < 60
    conn.execute("DELETE FROM subscriptions WHERE tenant_id = ANY(%s::uuid[])", (list(world.tenants.values()),))
    conn.commit()
    before = conn.execute("SELECT sum(mrr) FROM mrr_monthly WHERE month = last_complete_month()").fetchone()
    conn.execute("SELECT refresh_metrics()")
    conn.commit()
    after = conn.execute("SELECT sum(mrr) FROM mrr_monthly WHERE month = last_complete_month()").fetchone()
    assert before is not None and after is not None and float(before[0]) - float(after[0]) == pytest.approx(1800.0)


# -- demo assets -------------------------------------------------------------------------------------------------------------------
def spots() -> list[demo_assets.Spot]:
    out = []
    n = 1
    for region, countries in (("EMEA", ("NL", "DE", "GB")), ("North America", ("US", "CA")), ("APAC", ("SG", "JP"))):
        for cc in countries:
            for kind in ("city", "seaport", "airport", "industrial"):
                for k in range(8):
                    out.append(demo_assets.Spot(n, f"{cc}{kind[:2]}{k}", kind, cc, region, 10 + n * 0.37 % 60, -20 + n * 0.91 % 100, 12.0))
                    n += 1
    return out


def test_demo_assets_are_deterministic_and_within_limits() -> None:
    tenants = [
        {"id": "00000000-0000-0000-0000-000000000001", "region": "EMEA", "assets": 20, "plan": "starter"},
        {"id": "00000000-0000-0000-0000-000000000002", "region": "North America", "assets": 900, "plan": "enterprise"},
        {"id": "00000000-0000-0000-0000-000000000003", "region": "APAC", "assets": None, "plan": "professional"},
    ]
    a = demo_assets.generate_rows(spots(), tenants)
    b = demo_assets.generate_rows(spots(), tenants)
    assert a == b
    per_tenant: dict[str, int] = defaultdict(int)
    for r in a:
        per_tenant[r["tenant_id"]] += 1
    assert per_tenant == {tenants[0]["id"]: 50, tenants[1]["id"]: 300, tenants[2]["id"]: 220}
    assert {r["type"] for r in a} == {"site", "route", "region"}
    assert all("illustrative" in r["tags"] and 1 <= r["criticality"] <= 5 for r in a)
    for tenant in tenants:
        names = [r["name"] for r in a if r["tenant_id"] == tenant["id"]]
        assert len(names) == len(set(names))
    in_region = [r for r in a if r["tenant_id"] == tenants[0]["id"] and r["country_code"] in ("NL", "DE", "GB")]
    assert len(in_region) / 50 > 0.6  # mostly in the tenant's own region
    for r in a:
        g = r["geometry"]
        assert g["type"] in ("Point", "LineString", "Polygon")
        if g["type"] == "Polygon":
            ring = g["coordinates"][0]
            assert ring[0] == ring[-1] and len(ring) == 25
    assert demo_assets.asset_target(None, "unknown") == 100 and demo_assets.asset_target(10_000, None) == 300
    assert math.isclose(demo_assets.circle(0, 0, 111)[0][0], 1.0, abs_tol=0.01)


def test_demo_assets_load_for_synthetic_tenants_only(world: World, conn: psycopg.Connection[Any], small_files: Path) -> None:
    load(conn, small_files)
    for pid, name, kind in ((501, "Harbourtown", "seaport"), (502, "Midcity", "city"), (503, "Skyfield", "airport"), (504, "Ironworks", "factory")):
        conn.execute(
            """INSERT INTO places (id, geonames_id, name, name_normalized, type, country_code, population, lat, lon, centroid, geom, source, uncertainty_km, location_level)
               OVERRIDING SYSTEM VALUE VALUES (%s, %s, %s, %s, %s, 'NL', 500000, 52, 5, ST_SetSRID(ST_MakePoint(5, 52), 4326), ST_SetSRID(ST_MakePoint(5, 52), 4326), 'geonames', 5, 'city')""",
            (pid, 9500 + pid, name, name.lower(), kind),
        )
    conn.commit()
    found = demo_assets.load_spots(conn)
    assert {s.kind for s in found} == {"city", "seaport", "airport", "industrial"}
    tenants = demo_assets.tenant_inputs(conn)
    assert tenants and all(t["id"] not in world.tenants.values() for t in tenants)
    rows = demo_assets.generate_rows(found, tenants)
    assert demo_assets.load_rows(conn, rows) == len(rows)
    assert demo_assets.load_rows(conn, rows) == len(rows)  # reloading replaces, never duplicates
    count = conn.execute("SELECT count(*) FROM assets WHERE external_id LIKE 'DEMO-%'").fetchone()
    assert count == (len(rows),)
    assert conn.execute("SELECT count(*) FROM assets WHERE tenant_id = ANY(%s::uuid[])", (list(world.tenants.values()),)).fetchone() == (4,)
    sample = conn.execute("SELECT location_source, 'illustrative' = ANY(tags), place_id FROM assets WHERE external_id = 'DEMO-0001' LIMIT 1").fetchone()
    assert sample is not None and sample[0] == "place" and sample[1] is True and sample[2] in (501, 502, 503, 504)
    out = conn.execute("SELECT 1").fetchone()
    assert out == (1,)
