"""Phase 7: revenue endpoints, filters, comparison, caching, CSV export, access, and response time."""

from __future__ import annotations

import time
from typing import Any

import psycopg
import pytest

from meridian.api.routers import revenue
from meridian.api.services import analytics
from tests.api_support import World, login

API = "/api/v1/platform/revenue"
ENDPOINTS = ("summary", "mrr", "movements", "retention", "cohorts", "dimensions", "unit-economics", "forecast", "tenants", "annotations")


def get(client: Any, path: str, **params: Any) -> Any:
    return client.get(f"{API}/{path}", params=params)


def test_summary_matches_the_views_and_compares(client: Any, world: World, business_small: Any, conn: psycopg.Connection[Any]) -> None:
    login(client, world, "finance")
    r = get(client, "summary", compare="previous_period")
    assert r.status_code == 200, r.text
    s = r.json()
    row = conn.execute("SELECT month, mrr, arr, customers, net_new_mrr FROM mrr_monthly ORDER BY month DESC LIMIT 2").fetchall()
    assert s["month"] == row[0][0].isoformat() and s["mrr"]["value"] == pytest.approx(float(row[0][1]), abs=0.01)
    assert s["mrr"]["previous"] == pytest.approx(float(row[1][1]), abs=0.01)
    assert s["mrr"]["change"] == pytest.approx(float(row[0][1] - row[1][1]), abs=0.01)
    assert s["arr"]["value"] == pytest.approx(s["mrr"]["value"] * 12, abs=0.05) and s["customers"]["value"] == row[0][3]
    assert s["net_new_mrr"]["value"] == pytest.approx(float(row[0][4]), abs=0.01)
    assert s["nrr_trailing_12m"] and s["grr_trailing_12m"] and s["grr_trailing_12m"] <= s["nrr_trailing_12m"]
    assert s["quick_ratio"] is not None and s["payback_months"] is not None and s["gross_margin_assumption"] == 0.8
    assert s["demo_data"] is True and s["as_of"]
    yoy = get(client, "summary", compare="previous_year").json()
    assert yoy["mrr"]["previous"] is not None and yoy["mrr"]["previous"] < yoy["mrr"]["value"]
    earlier = get(client, "summary", month="2025-03-17").json()
    assert earlier["month"] == "2025-03-01" and earlier["mrr"]["value"] < s["mrr"]["value"]
    assert get(client, "summary", month="2099-01-01").json()["month"] == s["month"]  # clamped to the latest complete month


def test_filters_narrow_the_figures_and_hide_company_wide_metrics(client: Any, world: World, business_small: Any) -> None:
    login(client, world, "finance")
    everyone = get(client, "summary").json()
    emea = get(client, "summary", region="EMEA").json()
    assert 0 < emea["mrr"]["value"] < everyone["mrr"]["value"] and emea["nrr_trailing_12m"] is None and "company wide" in emea["note"]
    parts = [get(client, "summary", region=r).json()["mrr"]["value"] for r in ("North America", "EMEA", "APAC", "LATAM")]
    seeded = 1800.0  # the two seeded test tenants have no region and are on a plan called standard
    assert sum(parts) + seeded == pytest.approx(everyone["mrr"]["value"], abs=0.1)
    plans = [get(client, "summary", plan=p).json()["mrr"]["value"] for p in ("starter", "professional", "enterprise")]
    assert sum(plans) + seeded == pytest.approx(everyone["mrr"]["value"], abs=0.1)
    nothing = get(client, "summary", industry="no such industry").json()
    assert nothing["mrr"]["value"] == 0 and nothing["customers"]["value"] == 0
    both = get(client, "summary", region="EMEA", plan="enterprise").json()["mrr"]["value"]
    assert both <= emea["mrr"]["value"]


def test_mrr_series_stack_quarter_and_comparison(client: Any, world: World, business_small: Any) -> None:
    login(client, world, "finance")
    r = get(client, "mrr", **{"from": "2024-12-01", "to": "2025-11-30"})
    assert r.status_code == 200
    body = r.json()
    items = body["items"]
    assert len(items) >= 10 and items[0]["period"] == "2024-12-01" and all(i["mrr"] >= 0 for i in items)
    assert items == sorted(items, key=lambda i: i["period"]) and body["annotations"] and body["demo_data"] is True
    stacked = get(client, "mrr", stack="plan", **{"from": "2025-01-01", "to": "2025-06-30"}).json()
    assert stacked["stack"]["dimension"] == "plan"
    series = stacked["stack"]["series"]
    assert {s["value"] for s in series} <= {"starter", "professional", "enterprise"}
    for i, point in enumerate(stacked["items"]):  # the stacked layers add up to the total line
        assert sum(s["points"][i]["mrr"] for s in series) == pytest.approx(point["mrr"], abs=0.05)
    quarterly = get(client, "mrr", granularity="quarter", **{"from": "2025-01-01", "to": "2025-12-31"}).json()["items"]
    monthly = {i["period"]: i for i in get(client, "mrr", **{"from": "2025-01-01", "to": "2025-12-31"}).json()["items"]}
    assert 3 <= len(quarterly) <= 4 and quarterly[0]["period"] == "2025-01-01"
    assert quarterly[0]["mrr"] == monthly["2025-03-01"]["mrr"]  # a quarter shows its last month
    compared = get(client, "mrr", compare="previous_year", **{"from": "2025-06-01", "to": "2025-08-31"}).json()
    assert compared["comparison"]["from"] == "2024-06-01" and len(compared["comparison"]["items"]) == 3
    assert compared["comparison"]["items"][0]["mrr"] < compared["items"][0]["mrr"]
    prior = get(client, "mrr", compare="previous_period", **{"from": "2025-06-01", "to": "2025-08-31"}).json()["comparison"]
    assert prior["from"] == "2025-03-01" and prior["to"] == "2025-05-01"
    stacked_filtered = get(client, "mrr", stack="channel", region="APAC", **{"from": "2025-01-01", "to": "2025-03-31"}).json()
    assert stacked_filtered["stack"]["series"] and stacked_filtered["filters"] == {"region": "APAC"}


def test_movements_add_up_and_quarters_sum(client: Any, world: World, business_small: Any) -> None:
    login(client, world, "finance")
    r = get(client, "movements", **{"from": "2025-01-01", "to": "2025-12-31"}).json()
    items = r["items"]
    for before, now in zip(items, items[1:], strict=False):
        assert now["mrr"] - before["mrr"] == pytest.approx(now["net_new_mrr"], abs=0.02)
        assert now["net_new_mrr"] == pytest.approx(now["new_mrr"] + now["expansion_mrr"] - now["contraction_mrr"] - now["churned_mrr"], abs=0.02)
    quarters = get(client, "movements", granularity="quarter", **{"from": "2025-01-01", "to": "2025-12-31"}).json()["items"]
    assert quarters[0]["new_mrr"] == pytest.approx(sum(i["new_mrr"] for i in items[:3]), abs=0.02)
    assert sum(q["net_new_mrr"] for q in quarters) == pytest.approx(sum(i["net_new_mrr"] for i in items), abs=0.05)
    region = get(client, "movements", region="EMEA", **{"from": "2025-01-01", "to": "2025-12-31"}).json()["items"]
    for before, now in zip(region, region[1:], strict=False):
        assert now["mrr"] - before["mrr"] == pytest.approx(now["net_new_mrr"], abs=0.02)


def test_retention_cohorts_dimensions_unit_economics(client: Any, world: World, business_small: Any) -> None:
    login(client, world, "finance")
    retention = get(client, "retention").json()["items"]
    assert retention and all(0 < i["grr"] <= 1.0001 and i["nrr"] >= i["grr"] for i in retention)
    cohorts = get(client, "cohorts", metric="customers", max_months=12).json()
    first = cohorts["items"][0]
    assert first["points"][0]["months_since"] == 0 and first["points"][0]["retention"] == 1.0
    assert all(p["retention"] <= 1.0 for c in cohorts["items"] for p in c["points"] if c["customers"] > 0)
    mrr_cohorts = get(client, "cohorts", metric="mrr").json()
    assert mrr_cohorts["metric"] == "mrr" and any(p["retention"] > 1 for c in mrr_cohorts["items"] for p in c["points"])  # expansion lifts cohort MRR
    for dim in ("plan", "region", "industry", "channel", "country", "billing_cycle"):
        d = get(client, "dimensions", dimension=dim, compare="previous_year").json()
        assert d["items"] and sum(i["mrr"] for i in d["items"]) == pytest.approx(d["total_mrr"], abs=0.1)
        assert sum(i["share_pct"] for i in d["items"]) == pytest.approx(100, abs=0.2)
        assert [i["mrr"] for i in d["items"]] == sorted((i["mrr"] for i in d["items"]), reverse=True)
    unit = get(client, "unit-economics").json()
    assert unit["assumptions"]["gross_margin"] == 0.8 and unit["items"][-1]["cac_trailing_3m"] > 0
    latest = unit["items"][-1]
    assert latest["payback_months"] == pytest.approx(latest["cac_trailing_3m"] / (latest["arpa"] * 0.8), abs=0.02)


def test_forecast_is_a_labeled_estimate_with_an_interval(client: Any, world: World, business_small: Any) -> None:
    login(client, world, "finance")
    f = get(client, "forecast").json()
    assert f["label"] == "Estimate" and "80 percent" in f["interval"] and len(f["forecast"]) == 6
    last_actual = f["history"][-1]["mrr"]
    for point in f["forecast"]:
        assert point["lower_80"] < point["mrr"] < point["upper_80"]
    assert f["forecast"][0]["month"] > f["history"][-1]["month"] and f["forecast"][-1]["mrr"] > last_actual * 0.9
    widths = [p["upper_80"] - p["lower_80"] for p in f["forecast"]]
    assert widths == sorted(widths)  # uncertainty grows with the horizon
    assert len(get(client, "forecast", horizon=3).json()["forecast"]) == 3
    assert get(client, "forecast", horizon=40).status_code == 422
    assert get(client, "forecast", region="LATAM").status_code in (200, 422)


def test_forecast_needs_enough_history(client: Any, world: World) -> None:
    login(client, world, "finance")
    r = get(client, "forecast")
    assert r.status_code == 422 and r.json()["type"].endswith("not-enough-history")


def test_tenants_annotations_and_csv_exports(client: Any, world: World, business_small: Any, conn: psycopg.Connection[Any]) -> None:
    conn.execute("UPDATE tenants SET name = '=HYPERLINK(\"http://x\")' WHERE id = (SELECT tenant_id FROM tenant_mrr_monthly ORDER BY mrr DESC LIMIT 1)")
    conn.commit()
    login(client, world, "platform")
    tenants = get(client, "tenants", limit=5).json()
    assert len(tenants["items"]) == 5 and tenants["items"] == sorted(tenants["items"], key=lambda t: -t["mrr"])
    assert get(client, "tenants", plan="enterprise").json()["items"][0]["plan"] == "enterprise"
    assert [e["label"] for e in get(client, "annotations").json()["items"]][0].startswith(("New data source", "Product launch", "Model", "Pricing"))
    for path, header in (("summary", "metric,value"), ("mrr", "period,mrr,arr,customers,arpa"), ("movements", "period,new_mrr"), ("retention", "month,nrr,grr"),
                         ("cohorts", "cohort,cohort_customers"), ("dimensions", "plan,mrr,customers"), ("unit-economics", "month,mrr"),
                         ("forecast", "month,mrr_estimate,lower_80,upper_80"), ("tenants", "tenant,plan,mrr")):
        r = get(client, path, format="csv")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and r.text.startswith(header), path
        assert "attachment" in r.headers["content-disposition"] and r.headers["cache-control"] == "private, no-store"
    csv_text = get(client, "tenants", format="csv").text
    assert "'=HYPERLINK" in csv_text and "\n=HYPERLINK" not in csv_text  # formulas are neutralised


def test_validation_errors(client: Any, world: World, business_small: Any) -> None:
    login(client, world, "finance")
    for path, params in (
        ("mrr", {"granularity": "week"}), ("mrr", {"granularity": "day"}), ("mrr", {"compare": "last_decade"}), ("mrr", {"stack": "secret"}),
        ("mrr", {"from": "2025-06-01", "to": "2025-01-01"}), ("mrr", {"from": "not a date"}), ("mrr", {"format": "xml"}),
        ("mrr", {"from": "2001-01-01", "to": "2026-10-01"}), ("dimensions", {"dimension": "tenant"}), ("cohorts", {"metric": "profit"}),
        ("cohorts", {"max_months": 0}), ("tenants", {"limit": 5000}), ("summary", {"plan": "x" * 100}),
    ):
        assert get(client, path, **params).status_code == 422, (path, params)


def test_etag_revalidation_and_private_caching(client: Any, world: World, business_small: Any) -> None:
    login(client, world, "finance")
    first = get(client, "summary")
    tag = first.headers["etag"]
    assert first.headers["cache-control"].startswith("private") and "Cookie" in first.headers["vary"]
    again = client.get(f"{API}/summary", headers={"If-None-Match": tag})
    assert again.status_code == 304 and again.content == b""
    assert client.get(f"{API}/summary", headers={"If-None-Match": '"other"'}).status_code == 200
    assert get(client, "summary", compare="previous_year").headers["etag"] != tag


def test_results_are_cached_until_the_views_are_refreshed(client: Any, world: World, business_small: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    original = revenue.month_series

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(revenue, "month_series", counting)
    analytics.CACHE.clear()
    login(client, world, "finance")
    get(client, "mrr")
    get(client, "mrr")
    get(client, "mrr")
    assert calls["n"] == 1  # one computation served three requests
    get(client, "mrr", stack="plan")
    assert calls["n"] == 2  # different parameters are a different entry
    login(client, world, "platform")
    refreshed = client.post(f"{API}/refresh")
    assert refreshed.status_code == 200 and refreshed.json()["refreshed_at"]
    get(client, "mrr")
    assert calls["n"] == 3  # a refresh makes older results unreachable


def test_only_finance_and_platform_roles_can_read_and_only_platform_can_refresh(client: Any, world: World, business_small: Any) -> None:
    for role in ("viewer", "analyst", "manager", "admin", "b_admin"):
        login(client, world, role)
        for path in ENDPOINTS:
            assert get(client, path).status_code == 403, (role, path)
        assert client.post(f"{API}/refresh").status_code == 403
    login(client, world, "finance")
    assert all(get(client, p).status_code == 200 or p == "forecast" for p in ENDPOINTS)
    assert client.post(f"{API}/refresh").status_code == 403  # finance reads, only the platform refreshes
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    for path in ENDPOINTS:
        assert get(client, path).status_code == 401


def test_revenue_endpoints_answer_within_500_ms_on_seeded_data(client: Any, world: World, business_full: Any) -> None:
    """Exit criterion: revenue endpoints return in under 500 ms on the full 36 month seed (cold, with the cache cleared)."""
    login(client, world, "finance")
    slow = {}
    for path, params in (
        ("summary", {"compare": "previous_year"}), ("mrr", {"stack": "plan", "compare": "previous_year"}), ("mrr", {"stack": "industry", "region": "EMEA"}),
        ("movements", {}), ("retention", {}), ("cohorts", {}), ("dimensions", {"dimension": "country"}), ("unit-economics", {}),
        ("forecast", {}), ("tenants", {}), ("annotations", {}),
    ):
        analytics.CACHE.clear()
        started = time.perf_counter()
        r = get(client, path, **params)
        elapsed = (time.perf_counter() - started) * 1000
        assert r.status_code == 200, (path, r.text)
        if elapsed >= 500:
            slow[f"{path} {params}"] = round(elapsed)
    assert not slow, slow
    # A cached repeat is far quicker still.
    started = time.perf_counter()
    get(client, "mrr", stack="plan", compare="previous_year")
    assert (time.perf_counter() - started) * 1000 < 250
