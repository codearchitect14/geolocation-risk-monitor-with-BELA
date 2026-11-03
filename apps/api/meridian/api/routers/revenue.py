"""Revenue and unit economics for finance analysts and platform administrators (demo data).

Metric definitions live in SQL (migration 0008) and are described in docs/metrics.md. These endpoints read the materialized views
through finance-scoped views, so a tenant role cannot read them even if a route were exposed by mistake.
"""

from __future__ import annotations

import datetime as dt
import warnings
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel
from statsmodels.tsa.exponential_smoothing.ets import ETSModel

from meridian.api import db
from meridian.api.auth import Principal, audit_action, get_tx, require
from meridian.api.db import Tx
from meridian.api.errors import ProblemError
from meridian.api.security import ratelimit
from meridian.api.services import analytics as an

router = APIRouter(tags=["revenue"])

FILTER_COLUMNS = {"plan": "plan_id", "region": "region", "industry": "industry", "channel": "acquisition_channel"}
DIMENSIONS = ("plan", "region", "industry", "channel", "country", "billing_cycle")
STACK_COLUMNS = {**FILTER_COLUMNS, "country": "country_code", "billing_cycle": "billing_cycle"}
Granularity = Query(default="month", pattern="^(month|quarter)$")
Compare = Query(default="none", pattern="^(none|previous_period|previous_year)$")
Format = Query(default="json", pattern="^(json|csv)$")


class Filters(BaseModel):
    plan: str | None = None
    region: str | None = None
    industry: str | None = None
    channel: str | None = None

    def sql(self, alias: str = "") -> tuple[str, list[Any]]:
        clauses, params = [], []
        for name, column in FILTER_COLUMNS.items():
            value = getattr(self, name)
            if value is not None:
                clauses.append(f"{alias}{column} = %s")
                params.append(value)
        return ("".join(" AND " + c for c in clauses)), params

    def key(self) -> tuple[Any, ...]:
        return tuple(getattr(self, n) for n in FILTER_COLUMNS)

    @property
    def active(self) -> bool:
        return any(v is not None for v in self.key())


def get_filters(
    plan: str | None = Query(default=None, max_length=40),
    region: str | None = Query(default=None, max_length=40),
    industry: str | None = Query(default=None, max_length=60),
    channel: str | None = Query(default=None, max_length=40),
) -> Filters:
    return Filters(plan=plan, region=region, industry=industry, channel=channel)


# -- helpers ------------------------------------------------------------------------------------------------------------
def first_of_month(day: dt.date) -> dt.date:
    return day.replace(day=1)


def add_months(day: dt.date, n: int) -> dt.date:
    index = day.year * 12 + day.month - 1 + n
    return dt.date(index // 12, index % 12 + 1, 1)


def last_month(tx: Tx) -> dt.date:
    row = tx.one("SELECT last_complete_month()")
    assert row is not None
    return row[0]  # type: ignore[no-any-return]


def refreshed_at(tx: Tx) -> dt.datetime | None:
    row = tx.one("SELECT refreshed_at FROM metric_refresh_v WHERE name = 'metrics'")
    return row[0] if row else None


def month_range(tx: Tx, start: dt.date | None, end: dt.date | None, default_months: int = 36) -> tuple[dt.date, dt.date]:
    latest = last_month(tx)
    last = min(first_of_month(end), latest) if end else latest
    first = first_of_month(start) if start else add_months(last, -(default_months - 1))
    if first > last:
        raise ProblemError(422, "from must not be after to.", code="invalid-period")
    if (last.year - first.year) * 12 + last.month - first.month > 119:
        raise ProblemError(422, "The period is longer than ten years.", code="invalid-period")
    return first, last


def month_series(tx: Tx, filters: Filters, first: dt.date, last: dt.date) -> list[dict[str, Any]]:
    where, params = filters.sql()
    rows = tx.all(
        f"""WITH m AS (SELECT generate_series(%s::date, %s::date, interval '1 month')::date AS month),
                 stock AS (SELECT month, sum(mrr) AS mrr, count(*) AS customers FROM tenant_mrr_monthly_v
                            WHERE month BETWEEN %s AND %s{where} GROUP BY month),
                 flow AS (SELECT month,
                                 COALESCE(sum(amount) FILTER (WHERE movement = 'new'), 0) AS new_mrr,
                                 COALESCE(sum(amount) FILTER (WHERE movement = 'expansion'), 0) AS expansion_mrr,
                                 COALESCE(-sum(amount) FILTER (WHERE movement = 'contraction'), 0) AS contraction_mrr,
                                 COALESCE(-sum(amount) FILTER (WHERE movement = 'churn'), 0) AS churned_mrr,
                                 count(*) FILTER (WHERE movement = 'new') AS new_customers,
                                 count(*) FILTER (WHERE movement = 'churn') AS churned_customers
                            FROM mrr_movements_v WHERE month BETWEEN %s AND %s{where} GROUP BY month)
            SELECT m.month, COALESCE(stock.mrr, 0), COALESCE(stock.customers, 0), COALESCE(flow.new_mrr, 0), COALESCE(flow.expansion_mrr, 0),
                   COALESCE(flow.contraction_mrr, 0), COALESCE(flow.churned_mrr, 0), COALESCE(flow.new_customers, 0), COALESCE(flow.churned_customers, 0)
              FROM m LEFT JOIN stock ON stock.month = m.month LEFT JOIN flow ON flow.month = m.month ORDER BY m.month""",  # noqa: S608
        [first, last, first, last, *params, first, last, *params],
    )
    out = []
    for r in rows:
        mrr, customers = float(r[1]), int(r[2])
        new_mrr, exp, con, churn = float(r[3]), float(r[4]), float(r[5]), float(r[6])
        out.append(
            {
                "month": r[0], "mrr": round(mrr, 2), "arr": round(mrr * 12, 2), "customers": customers,
                "arpa": round(mrr / customers, 2) if customers else None,
                "new_mrr": round(new_mrr, 2), "expansion_mrr": round(exp, 2), "contraction_mrr": round(con, 2), "churned_mrr": round(churn, 2),
                "net_new_mrr": round(new_mrr + exp - con - churn, 2), "new_customers": int(r[7]), "churned_customers": int(r[8]),
            }
        )  # fmt: skip
    return out


def group_months(items: list[dict[str, Any]], granularity: str, flows: tuple[str, ...]) -> list[dict[str, Any]]:
    """Quarterly view of a monthly series: flows are summed, stocks are taken at the quarter's last month."""
    if granularity == "month":
        return [{**i, "period": i["month"]} for i in items]
    groups: dict[dt.date, list[dict[str, Any]]] = {}
    for i in items:
        start = dt.date(i["month"].year, 3 * ((i["month"].month - 1) // 3) + 1, 1)
        groups.setdefault(start, []).append(i)
    out = []
    for start, members in groups.items():
        last = dict(members[-1])
        for f in flows:
            last[f] = round(sum(m[f] for m in members), 2)
        last["period"] = start
        out.append(last)
    return out


def shifted(tx: Tx, compare: str, first: dt.date, last: dt.date) -> tuple[dt.date, dt.date] | None:
    if compare == "none":
        return None
    n = (last.year - first.year) * 12 + last.month - first.month + 1
    back = 12 if compare == "previous_year" else n
    return add_months(first, -back), add_months(last, -back)


def scoped(tx: Tx, request: Request, name: str, params: tuple[Any, ...], producer: Any) -> Any:
    return an.CACHE.get_or_compute(("revenue", name, refreshed_at(tx), params), producer)


# -- endpoints ----------------------------------------------------------------------------------------------------------
@router.get("/platform/revenue/summary", summary="Headline revenue metrics for one month, with a comparison (demo data)")
def revenue_summary(
    request: Request,
    month: dt.date | None = Query(default=None, description="Any day in the month; default the latest complete month"),
    compare: str = Compare,
    filters: Filters = Depends(get_filters),
    format: str = Format,
    principal: Principal = Depends(require("revenue.view")),
    tx: Tx = Depends(get_tx),
) -> Response:
    latest = last_month(tx)
    target = min(first_of_month(month), latest) if month else latest

    def build() -> dict[str, Any]:
        series = month_series(tx, filters, add_months(target, -14), target)
        by_month = {s["month"]: s for s in series}
        now = by_month.get(target) or {}
        other = shifted(tx, compare, target, target)
        before = by_month.get(other[0]) if other else None
        row = tx.one("SELECT nrr, grr FROM retention_monthly_v WHERE month = %s", (target,))
        unit = tx.one(
            "SELECT logo_churn_rate, quick_ratio, cac, cac_trailing_3m, payback_months, ltv FROM unit_economics_monthly_v WHERE month = %s", (target,)
        )
        overage = tx.one("SELECT overage FROM overage_monthly_v WHERE month = %s", (target,))
        paid = tx.one("SELECT COALESCE(sum(total), 0) FROM invoices WHERE status = 'paid' AND paid_at > current_date - 365")
        overdue = tx.one("SELECT COALESCE(sum(total), 0), count(*) FROM invoices WHERE status = 'overdue'")
        assert paid and overdue
        unfiltered = not filters.active
        payload: dict[str, Any] = {
            "month": target, "as_of": refreshed_at(tx), "compare": compare, "filters": filters.model_dump(exclude_none=True),
            "mrr": an.change(now.get("mrr"), before.get("mrr") if before else None),
            "arr": an.change(now.get("arr"), before.get("arr") if before else None),
            "customers": an.change(now.get("customers"), before.get("customers") if before else None),
            "arpa": an.change(now.get("arpa"), before.get("arpa") if before else None),
            "net_new_mrr": an.change(now.get("net_new_mrr"), before.get("net_new_mrr") if before else None),
            "new_customers": now.get("new_customers"), "churned_customers": now.get("churned_customers"),
            "overage_this_month": float(overage[0]) if overage and unfiltered else None,
            "nrr_trailing_12m": float(row[0]) if row and unfiltered else None,
            "grr_trailing_12m": float(row[1]) if row and unfiltered else None,
            "logo_churn_rate": float(unit[0]) if unit and unit[0] is not None and unfiltered else None,
            "quick_ratio": float(unit[1]) if unit and unit[1] is not None and unfiltered else None,
            "cac": float(unit[2]) if unit and unit[2] is not None and unfiltered else None,
            "cac_trailing_3m": float(unit[3]) if unit and unit[3] is not None and unfiltered else None,
            "payback_months": float(unit[4]) if unit and unit[4] is not None and unfiltered else None,
            "ltv": float(unit[5]) if unit and unit[5] is not None and unfiltered else None,
            "paid_last_12_months": float(paid[0]), "overdue_total": float(overdue[0]), "overdue_invoices": overdue[1],
            "note": None if unfiltered else "Retention and unit economics are company wide and are not shown with filters.",
            "gross_margin_assumption": 0.8, "demo_data": True,
        }  # fmt: skip
        return payload

    payload = scoped(tx, request, "summary", (target, compare, filters.key()), build)
    rows = [[k, v["value"] if isinstance(v, dict) and "value" in v else v] for k, v in payload.items() if not isinstance(v, dict) or "value" in v]
    return an.respond(request, payload, format, ["metric", "value"], rows, "revenue-summary")


@router.get("/platform/revenue/mrr", summary="MRR over time, optionally stacked by a dimension, with event annotations (demo data)")
def revenue_mrr(
    request: Request,
    start: dt.date | None = Query(default=None, alias="from"),
    end: dt.date | None = Query(default=None, alias="to"),
    granularity: str = Granularity,
    compare: str = Compare,
    stack: str = Query(default="none", pattern="^(none|plan|region|industry|channel|country|billing_cycle)$"),
    filters: Filters = Depends(get_filters),
    format: str = Format,
    principal: Principal = Depends(require("revenue.view")),
    tx: Tx = Depends(get_tx),
) -> Response:
    first, last = month_range(tx, start, end)

    def build() -> dict[str, Any]:
        items = group_months(month_series(tx, filters, first, last), granularity, ("new_mrr", "expansion_mrr", "contraction_mrr", "churned_mrr", "net_new_mrr", "new_customers", "churned_customers"))
        payload: dict[str, Any] = {
            "from": first, "to": last, "granularity": granularity, "as_of": refreshed_at(tx), "filters": filters.model_dump(exclude_none=True),
            "items": [{k: i[k] for k in ("period", "mrr", "arr", "customers", "arpa")} for i in items], "demo_data": True,
        }  # fmt: skip
        if stack != "none":
            payload["stack"] = {"dimension": stack, "series": stacked(tx, stack, filters, first, last, granularity)}
        other = shifted(tx, compare, first, last)
        if other:
            prev = group_months(month_series(tx, filters, *other), granularity, ())
            payload["comparison"] = {
                "from": other[0], "to": other[1],
                "items": [{k: i[k] for k in ("period", "mrr", "customers")} for i in prev],
            }  # fmt: skip
        events = tx.all("SELECT date, label FROM business_events WHERE date BETWEEN %s AND %s ORDER BY date", (first, month_end(last)))
        payload["annotations"] = [{"date": e[0], "label": e[1]} for e in events]
        return payload

    payload = scoped(tx, request, "mrr", (first, last, granularity, compare, stack, filters.key()), build)
    rows = [[i["period"], i["mrr"], i["arr"], i["customers"], i["arpa"]] for i in payload["items"]]
    return an.respond(request, payload, format, ["period", "mrr", "arr", "customers", "arpa"], rows, "mrr")


def month_end(month: dt.date) -> dt.date:
    return add_months(month, 1) - dt.timedelta(days=1)


def stacked(tx: Tx, dimension: str, filters: Filters, first: dt.date, last: dt.date, granularity: str) -> list[dict[str, Any]]:
    column = STACK_COLUMNS[dimension]
    where, params = filters.sql()
    rows = tx.all(
        f"""SELECT month, COALESCE({column}::text, 'Unknown'), sum(mrr)::float8 FROM tenant_mrr_monthly_v
             WHERE month BETWEEN %s AND %s{where} GROUP BY 1, 2 ORDER BY 1, 2""",  # noqa: S608
        [first, last, *params],
    )
    values = sorted({r[1] for r in rows})
    months = sorted({r[0] for r in rows})
    table = {(r[0], r[1]): r[2] for r in rows}
    out = []
    for v in values:
        pts = [{"month": m, "mrr": round(table.get((m, v), 0.0), 2)} for m in months]
        if granularity == "quarter":
            pts = [
                {"period": dt.date(p["month"].year, 3 * ((p["month"].month - 1) // 3) + 1, 1), "mrr": p["mrr"]} for p in pts
            ]
            last_in_quarter = {p["period"]: p for p in pts}  # later months overwrite earlier ones: the quarter-end value
            pts = list(last_in_quarter.values())
        else:
            pts = [{"period": p["month"], "mrr": p["mrr"]} for p in pts]
        out.append({"value": v, "points": pts})
    return out


@router.get("/platform/revenue/movements", summary="New, expansion, contraction, and churned MRR by period (demo data)")
def revenue_movements(
    request: Request,
    start: dt.date | None = Query(default=None, alias="from"),
    end: dt.date | None = Query(default=None, alias="to"),
    granularity: str = Granularity,
    compare: str = Compare,
    filters: Filters = Depends(get_filters),
    format: str = Format,
    principal: Principal = Depends(require("revenue.view")),
    tx: Tx = Depends(get_tx),
) -> Response:
    first, last = month_range(tx, start, end, 12)
    flows = ("new_mrr", "expansion_mrr", "contraction_mrr", "churned_mrr", "net_new_mrr", "new_customers", "churned_customers")

    def build() -> dict[str, Any]:
        items = group_months(month_series(tx, filters, first, last), granularity, flows)
        payload: dict[str, Any] = {
            "from": first, "to": last, "granularity": granularity, "as_of": refreshed_at(tx), "filters": filters.model_dump(exclude_none=True),
            "items": [{k: i[k] for k in ("period", *flows, "mrr")} for i in items], "demo_data": True,
            "note": "With a plan filter, upgrades appear as expansion in the new plan, so movements do not add up to the plan's MRR change.",
        }  # fmt: skip
        other = shifted(tx, compare, first, last)
        if other:
            prev = group_months(month_series(tx, filters, *other), granularity, flows)
            payload["comparison"] = {"from": other[0], "to": other[1], "items": [{k: i[k] for k in ("period", *flows, "mrr")} for i in prev]}
        return payload

    payload = scoped(tx, request, "movements", (first, last, granularity, compare, filters.key()), build)
    cols = ["period", *flows, "mrr"]
    return an.respond(request, payload, format, cols, [[i[c] for c in cols] for i in payload["items"]], "mrr-movements")


@router.get("/platform/revenue/retention", summary="Trailing twelve month net and gross revenue retention (demo data)")
def revenue_retention(
    request: Request,
    start: dt.date | None = Query(default=None, alias="from"),
    end: dt.date | None = Query(default=None, alias="to"),
    format: str = Format,
    principal: Principal = Depends(require("revenue.view")),
    tx: Tx = Depends(get_tx),
) -> Response:
    first, last = month_range(tx, start, end)

    def build() -> dict[str, Any]:
        rows = tx.all(
            """SELECT r.month, r.nrr, r.grr, r.base_customers, u.logo_churn_rate
                 FROM retention_monthly_v r LEFT JOIN unit_economics_monthly_v u ON u.month = r.month
                WHERE r.month BETWEEN %s AND %s ORDER BY r.month""",
            (first, last),
        )
        return {
            "from": first, "to": last, "as_of": refreshed_at(tx), "demo_data": True,
            "items": [
                {"month": r[0], "nrr": float(r[1]), "grr": float(r[2]), "base_customers": r[3], "logo_churn_rate": float(r[4]) if r[4] is not None else None}
                for r in rows
            ],
        }  # fmt: skip

    payload = scoped(tx, request, "retention", (first, last), build)
    rows = [[i["month"], i["nrr"], i["grr"], i["base_customers"], i["logo_churn_rate"]] for i in payload["items"]]
    return an.respond(request, payload, format, ["month", "nrr", "grr", "base_customers", "logo_churn_rate"], rows, "retention")


@router.get("/platform/revenue/cohorts", summary="Cohort retention by month of first subscription (demo data)")
def revenue_cohorts(
    request: Request,
    metric: str = Query(default="mrr", pattern="^(mrr|customers)$"),
    max_months: int = Query(default=24, ge=1, le=60),
    format: str = Format,
    principal: Principal = Depends(require("revenue.view")),
    tx: Tx = Depends(get_tx),
) -> Response:
    def build() -> dict[str, Any]:
        rows = tx.all(
            """SELECT cohort_month, months_since, customers_active, mrr, cohort_customers, cohort_start_mrr FROM cohort_retention_v
                WHERE months_since <= %s ORDER BY cohort_month, months_since""",
            (max_months,),
        )
        cohorts: dict[dt.date, dict[str, Any]] = {}
        for r in rows:
            c = cohorts.setdefault(r[0], {"cohort": r[0], "customers": r[4], "starting_mrr": float(r[5]), "points": []})
            base = float(r[5]) if metric == "mrr" else float(r[4])
            value = float(r[3]) if metric == "mrr" else float(r[2])
            c["points"].append({"months_since": r[1], "customers": r[2], "mrr": float(r[3]), "retention": round(value / base, 4) if base else None})
        return {"metric": metric, "as_of": refreshed_at(tx), "items": list(cohorts.values()), "demo_data": True}

    payload = scoped(tx, request, "cohorts", (metric, max_months), build)
    rows = [[c["cohort"], c["customers"], p["months_since"], p["customers"], p["mrr"], p["retention"]] for c in payload["items"] for p in c["points"]]
    return an.respond(request, payload, format, ["cohort", "cohort_customers", "months_since", "customers_active", "mrr", "retention"], rows, "cohorts")


@router.get("/platform/revenue/dimensions", summary="MRR by plan, region, industry, channel, country, or billing cycle (demo data)")
def revenue_dimensions(
    request: Request,
    dimension: str = Query(default="plan", pattern="^(plan|region|industry|channel|country|billing_cycle)$"),
    month: dt.date | None = None,
    compare: str = Compare,
    format: str = Format,
    principal: Principal = Depends(require("revenue.view")),
    tx: Tx = Depends(get_tx),
) -> Response:
    latest = last_month(tx)
    target = min(first_of_month(month), latest) if month else latest

    def build() -> dict[str, Any]:
        other = shifted(tx, compare, target, target)
        months = [target] + ([other[0]] if other else [])
        rows = tx.all(
            "SELECT month, value, mrr, customers FROM revenue_by_dimension_v WHERE dimension = %s AND month = ANY(%s)", (dimension, months)
        )
        now = {r[1]: (float(r[2]), r[3]) for r in rows if r[0] == target}
        before = {r[1]: (float(r[2]), r[3]) for r in rows if r[0] != target}
        total = sum(v[0] for v in now.values())
        items = [
            {
                "value": k, "mrr": v[0], "customers": v[1], "share_pct": round(v[0] / total * 100, 2) if total else None,
                "previous_mrr": before.get(k, (None, None))[0] if other else None,
                "change_pct": an.change(v[0], before[k][0])["change_pct"] if other and k in before else None,
            }
            for k, v in sorted(now.items(), key=lambda kv: -kv[1][0])
        ]  # fmt: skip
        return {"dimension": dimension, "month": target, "compare": compare, "as_of": refreshed_at(tx), "total_mrr": round(total, 2), "items": items, "demo_data": True}

    payload = scoped(tx, request, "dimensions", (dimension, target, compare), build)
    rows = [[i["value"], i["mrr"], i["customers"], i["share_pct"], i["previous_mrr"], i["change_pct"]] for i in payload["items"]]
    return an.respond(request, payload, format, [dimension, "mrr", "customers", "share_pct", "previous_mrr", "change_pct"], rows, f"mrr-by-{dimension}")


@router.get("/platform/revenue/unit-economics", summary="ARPA, churn, quick ratio, CAC, payback, and LTV by month (demo data)")
def revenue_unit_economics(
    request: Request,
    start: dt.date | None = Query(default=None, alias="from"),
    end: dt.date | None = Query(default=None, alias="to"),
    format: str = Format,
    principal: Principal = Depends(require("revenue.view")),
    tx: Tx = Depends(get_tx),
) -> Response:
    first, last = month_range(tx, start, end, 24)

    def build() -> dict[str, Any]:
        rows = tx.all(
            """SELECT month, mrr, customers, arpa, logo_churn_rate, quick_ratio, marketing_spend, cac, cac_trailing_3m, payback_months, ltv
                 FROM unit_economics_monthly_v WHERE month BETWEEN %s AND %s ORDER BY month""",
            (first, last),
        )
        names = ("month", "mrr", "customers", "arpa", "logo_churn_rate", "quick_ratio", "marketing_spend", "cac", "cac_trailing_3m", "payback_months", "ltv")
        items = [{n: (float(v) if n != "month" and n != "customers" and v is not None else v) for n, v in zip(names, r, strict=True)} for r in rows]
        return {
            "from": first, "to": last, "as_of": refreshed_at(tx), "items": items, "demo_data": True,
            "assumptions": {"gross_margin": 0.8, "gross_margin_note": "Fixed assumption used for payback and LTV (shown in tooltips)."},
        }  # fmt: skip

    payload = scoped(tx, request, "unit", (first, last), build)
    cols = ["month", "mrr", "customers", "arpa", "logo_churn_rate", "quick_ratio", "marketing_spend", "cac", "cac_trailing_3m", "payback_months", "ltv"]
    return an.respond(request, payload, format, cols, [[i[c] for c in cols] for i in payload["items"]], "unit-economics")


@router.get("/platform/revenue/forecast", summary="Six month MRR projection with an 80 percent interval (an estimate, demo data)")
def revenue_forecast(
    request: Request,
    horizon: int = Query(default=6, ge=1, le=12),
    filters: Filters = Depends(get_filters),
    format: str = Format,
    principal: Principal = Depends(require("revenue.view")),
    tx: Tx = Depends(get_tx),
) -> Response:
    latest = last_month(tx)

    def build() -> dict[str, Any]:
        history = month_series(tx, filters, add_months(latest, -35), latest)
        values = [h["mrr"] for h in history if h["mrr"] > 0]
        if len(values) < 18:
            raise ProblemError(422, "At least 18 months of history are needed for a forecast.", code="not-enough-history")
        index = pd.PeriodIndex([h["month"] for h in history if h["mrr"] > 0], freq="M")
        series = pd.Series(values, index=index)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = ETSModel(series, error="add", trend="add", damped_trend=True).fit(disp=False)
            frame = model.get_prediction(start=len(series), end=len(series) + horizon - 1).summary_frame(alpha=0.2)
        projection = [
            {"month": add_months(latest, i + 1), "mrr": round(float(r["mean"]), 2), "lower_80": round(float(r["pi_lower"]), 2), "upper_80": round(float(r["pi_upper"]), 2)}
            for i, (_, r) in enumerate(frame.iterrows())
        ]  # fmt: skip
        return {
            "label": "Estimate", "method": "Exponential smoothing (additive error, damped additive trend) fitted to monthly MRR",
            "interval": "80 percent prediction interval", "history_months": len(values), "as_of": refreshed_at(tx),
            "filters": filters.model_dump(exclude_none=True), "demo_data": True,
            "history": [{"month": h["month"], "mrr": h["mrr"]} for h in history], "forecast": projection,
        }  # fmt: skip

    payload = scoped(tx, request, "forecast", (latest, horizon, filters.key()), build)
    rows = [[f["month"], f["mrr"], f["lower_80"], f["upper_80"]] for f in payload["forecast"]]
    return an.respond(request, payload, format, ["month", "mrr_estimate", "lower_80", "upper_80"], rows, "mrr-forecast")


@router.get("/platform/revenue/tenants", summary="Current MRR by tenant (demo data)")
def revenue_tenants(
    request: Request,
    filters: Filters = Depends(get_filters),
    limit: int = Query(default=100, ge=1, le=500),
    format: str = Format,
    principal: Principal = Depends(require("revenue.view")),
    tx: Tx = Depends(get_tx),
) -> Response:
    latest = last_month(tx)

    def build() -> dict[str, Any]:
        where, params = filters.sql("m.")
        rows = tx.all(
            f"""SELECT m.tenant_id, t.name, m.plan_id, m.mrr, m.region, m.industry, m.acquisition_channel
                  FROM tenant_mrr_monthly_v m JOIN tenants t ON t.id = m.tenant_id WHERE m.month = %s{where}
                 ORDER BY m.mrr DESC, t.name LIMIT %s""",  # noqa: S608
            [latest, *params, limit],
        )
        return {
            "month": latest, "as_of": refreshed_at(tx), "demo_data": True,
            "items": [{"tenant_id": str(r[0]), "tenant": r[1], "plan": r[2], "mrr": float(r[3]), "region": r[4], "industry": r[5], "channel": r[6]} for r in rows],
        }  # fmt: skip

    payload = scoped(tx, request, "tenants", (latest, limit, filters.key()), build)
    cols = ["tenant", "plan", "mrr", "region", "industry", "channel"]
    return an.respond(request, payload, format, cols, [[i["tenant"], i["plan"], i["mrr"], i["region"], i["industry"], i["channel"]] for i in payload["items"]], "revenue-by-tenant")


@router.get("/platform/revenue/annotations", summary="Business events for chart annotations (demo data)")
def revenue_annotations(
    principal: Principal = Depends(require("revenue.view")), tx: Tx = Depends(get_tx)
) -> dict[str, Any]:
    rows = tx.all("SELECT date, label FROM business_events ORDER BY date")
    return {"items": [{"date": r[0], "label": r[1]} for r in rows], "demo_data": True}


@router.post("/platform/revenue/refresh", summary="Refresh the revenue metric views now")
def refresh(
    request: Request, principal: Principal = Depends(require("platform.manage")), tx: Tx = Depends(get_tx)
) -> dict[str, Any]:
    ratelimit.check(f"metrics-refresh:{principal.user_id}", 10, 3600, detail="Metrics were refreshed too often. Try again later.")
    audit_action(tx, request, principal, "metrics.refresh")
    tx.commit()
    with db.system_connection() as conn:
        stamp = conn.execute("SELECT refresh_metrics()").fetchone()
        conn.commit()
    an.CACHE.clear()
    assert stamp is not None
    return {"refreshed_at": stamp[0]}
