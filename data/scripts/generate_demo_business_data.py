"""Generate illustrative business history for the demo: tenants, subscriptions, invoices, usage, and platform statistics.

python generate_demo_business_data.py                 write data/synthetic/*.csv (seed 42, 36 months to 2026-10-31)
python generate_demo_business_data.py --months 12     a shorter history
python generate_demo_business_data.py --check         verify the files in data/synthetic

Everything here is synthetic and labeled as such. Company names are invented word combinations and do not refer to real
organisations. The generator uses only random.Random(seed), so two runs with the same arguments produce identical files.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import datetime as dt
import math
import random
import sys
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

SEED = 42
END = dt.date(2026, 10, 31)
MONTHS = 36
NAMESPACE = uuid.UUID("6f1d3a52-8c3e-4a53-9a58-5b8f2d0c7e11")
OUT_DIR = Path(__file__).resolve().parents[1] / "synthetic"

PLANS: dict[str, dict[str, Any]] = {
    "starter": {"name": "Starter", "price": 499, "limit": 50, "unit": 25, "unit_price": 60},
    "professional": {"name": "Professional", "price": 1999, "limit": 500, "unit": 25, "unit_price": 200},
    "enterprise": {"name": "Enterprise", "price": 8000, "limit": 5000, "unit": 25, "unit_price": 400},
}
PLAN_MIX = (("starter", 0.50), ("professional", 0.35), ("enterprise", 0.15))
MONTHLY_CHURN = {"starter": 0.030, "professional": 0.015, "enterprise": 0.006}
EXPANSION_PROBABILITY = 0.04
CONTRACTION_PROBABILITY = 0.010
ANNUAL_SHARE = 0.40
ANNUAL_DISCOUNT = 0.10
PRICE_INCREASE_MONTH = 20
PRICE_INCREASE = 0.10
REGIONS = (("North America", 0.40), ("EMEA", 0.30), ("APAC", 0.25), ("LATAM", 0.05))
COUNTRIES = {
    "North America": ("US", "CA"),
    "EMEA": ("GB", "DE", "FR", "NL", "AE", "ZA", "ES"),
    "APAC": ("SG", "JP", "AU", "IN", "KR"),
    "LATAM": ("BR", "MX", "CL"),
}
INDUSTRIES = (
    "logistics and shipping", "manufacturing", "retail and consumer goods", "energy and utilities", "insurance", "corporate security",
)  # fmt: skip
CHANNELS = (("Paid search", 0.25), ("Content", 0.25), ("Events", 0.15), ("Partners", 0.20), ("Outbound", 0.15))
WORDS_A = (
    "Northgate", "Harbour", "Alder", "Brindle", "Cobalt", "Dunmore", "Elmstead", "Fairmont", "Granite", "Hollow", "Ironbridge", "Juniper",
    "Kestrel", "Lantern", "Meridian", "Nettle", "Orchard", "Pennant", "Quarry", "Ridgeway", "Saltmarsh", "Thornfield", "Upland", "Verity",
    "Westcombe", "Yarrow", "Zephyr", "Amberley", "Bracken", "Copperfield",
)  # fmt: skip
WORDS_B = (
    "Freight", "Logistics", "Foods", "Components", "Energy", "Mutual", "Retail", "Shipping", "Industries", "Textiles", "Chemicals",
    "Distribution", "Marine", "Power", "Packaging", "Assurance", "Metals", "Trading", "Supply", "Motors",
)  # fmt: skip
SUFFIXES = ("Group", "Holdings", "Partners", "Ltd", "Co", "International")
EVENTS = (
    (dt.date(2024, 3, 1), "New data source: weather service alerts"),
    (dt.date(2024, 6, 1), "Product launch: PDF briefings"),
    (dt.date(2024, 9, 1), "Model improvement: event type classifier update"),
    (dt.date(2025, 2, 1), "New data source: port authority notices"),
    (dt.date(2025, 7, 1), "Pricing change: list prices up 10 percent for new customers"),
    (dt.date(2025, 11, 1), "Latency optimization: faster place linking"),
    (dt.date(2026, 4, 1), "Product launch: watch zones by region"),
)

FILES = {
    "plans": ["id", "name", "monthly_price", "asset_limit", "overage_unit_size", "overage_unit_price"],
    "tenants": ["id", "name", "slug", "industry", "region", "country", "created_at", "churned_at", "acquisition_channel"],
    "subscriptions": ["id", "tenant_id", "plan", "billing_cycle", "price", "start", "end", "change_reason"],
    "invoices": ["id", "tenant_id", "period_start", "period_end", "status", "total", "issued_at", "due_at", "paid_at"],
    "invoice_lines": ["id", "invoice_id", "line_type", "description", "amount"],
    "usage_daily": ["tenant_id", "date", "assets_monitored", "alerts", "briefings", "api_calls", "uploads"],
    "ops_stats_daily": [
        "tenant_id", "date", "alerts_by_level", "acknowledged", "dismissed", "location_confirmed", "location_corrected", "median_ack_minutes",
    ],  # fmt: skip
    "platform_stats_daily": [
        "date", "incidents_ingested", "p50_latency_ms", "p95_latency_ms", "detection_delay_minutes_median", "false_alert_rate",
    ],  # fmt: skip
    "marketing_spend": ["month", "channel", "spend"],
    "business_events": ["date", "label"],
}


# -- calendar helpers -----------------------------------------------------------------------------------------------
def month_start(year: int, month: int) -> dt.date:
    return dt.date(year, month, 1)


def add_months(day: dt.date, n: int) -> dt.date:
    index = day.year * 12 + day.month - 1 + n
    return dt.date(index // 12, index % 12 + 1, 1)


def month_end(day: dt.date) -> dt.date:
    return dt.date(day.year, day.month, calendar.monthrange(day.year, day.month)[1])


def month_list(months: int, end: dt.date = END) -> list[dt.date]:
    last = month_start(end.year, end.month)
    return [add_months(last, -(months - 1) + i) for i in range(months)]


def new_id(kind: str, *parts: Any) -> str:
    return str(uuid.uuid5(NAMESPACE, ":".join([kind, *map(str, parts)])))


# -- random helpers -------------------------------------------------------------------------------------------------
def weighted(rng: random.Random, options: tuple[tuple[str, float], ...]) -> str:
    r, total = rng.random(), 0.0
    for value, weight in options:
        total += weight
        if r < total:
            return value
    return options[-1][0]


def poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 30:  # normal approximation keeps large rates fast
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def season_factor(day: dt.date) -> float:
    """Atlantic storm season (August to October) and winter weather (December to February) raise alert volumes."""
    return {8: 1.35, 9: 1.55, 10: 1.40, 12: 1.20, 1: 1.30, 2: 1.20}.get(day.month, 1.0)


def trend(index: int, months: int, start: float, end: float) -> float:
    return start + (end - start) * (index / max(months - 1, 1))


# -- tenants and subscriptions --------------------------------------------------------------------------------------
def tenant_name(rng: random.Random, used: set[str]) -> str:
    for _ in range(200):
        name = f"{rng.choice(WORDS_A)} {rng.choice(WORDS_B)} {rng.choice(SUFFIXES)}"
        if name not in used:
            used.add(name)
            return name
    name = f"{rng.choice(WORDS_A)} {rng.choice(WORDS_B)} {len(used)}"
    used.add(name)
    return name


def list_price(rng: random.Random, plan: str, signup_index: int) -> float:
    if plan == "enterprise":
        base = min(max(math.exp(rng.gauss(math.log(14000), 0.35)), 8000), 25000)
        price = round(base / 100) * 100
    else:
        price = PLANS[plan]["price"]
    if signup_index >= PRICE_INCREASE_MONTH and plan != "enterprise":
        price = round(price * (1 + PRICE_INCREASE))
    return float(price)


def simulate_tenants(rng: random.Random, months: list[dt.date], logo_scale: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tenants: list[dict[str, Any]] = []
    subscriptions: list[dict[str, Any]] = []
    used: set[str] = set()
    n = len(months)
    for i, first in enumerate(months):
        rate = (2 + 5 * i / max(n - 1, 1)) * logo_scale
        for _ in range(poisson(rng, rate)):
            plan = weighted(rng, PLAN_MIX)
            region = weighted(rng, REGIONS)
            tenant_id = new_id("tenant", len(tenants))
            created = first + dt.timedelta(days=rng.randrange(calendar.monthrange(first.year, first.month)[1]))
            name = tenant_name(rng, used)
            cycle = "annual" if rng.random() < ANNUAL_SHARE else "monthly"
            tenant = {
                "id": tenant_id, "name": name, "slug": name.lower().replace(" ", "-"), "industry": rng.choice(INDUSTRIES), "region": region,
                "country": rng.choice(COUNTRIES[region]), "created_at": created, "churned_at": "", "acquisition_channel": weighted(rng, CHANNELS),
                "_plan": plan, "_cycle": cycle, "_start_index": i,
            }  # fmt: skip
            tenants.append(tenant)
            monthly = list_price(rng, plan, i)
            subscriptions += simulate_subscription(rng, tenant, months, i, monthly, created)
    for tenant in tenants:
        last = subscriptions_of(subscriptions, str(tenant["id"]))[-1]  # churned only when the final subscription has ended
        tenant["churned_at"] = last["end"] + dt.timedelta(days=1) if last["end"] else ""
    return tenants, subscriptions


def subscriptions_of(subs: list[dict[str, Any]], tenant_id: str) -> list[dict[str, Any]]:
    return [s for s in subs if s["tenant_id"] == tenant_id]


def sub_row(tenant_id: str, seq: int, plan: str, cycle: str, monthly: float, start: dt.date, reason: str) -> dict[str, Any]:
    amount = monthly if cycle == "monthly" else round(monthly * 12 * (1 - ANNUAL_DISCOUNT), 2)
    return {
        "id": new_id("sub", tenant_id, seq), "tenant_id": tenant_id, "plan": plan, "billing_cycle": cycle, "price": round(amount, 2),
        "start": start, "end": None, "change_reason": reason, "_monthly": monthly,
    }  # fmt: skip


def simulate_subscription(
    rng: random.Random, tenant: dict[str, Any], months: list[dt.date], start_index: int, monthly: float, created: dt.date
) -> list[dict[str, Any]]:
    """Month by month: churn, expansion, contraction, and upgrades. Annual customers change only at their anniversary."""
    plan, cycle = tenant["_plan"], tenant["_cycle"]
    rows = [sub_row(tenant["id"], 0, plan, cycle, monthly, created, "new")]
    for i in range(start_index + 1, len(months)):
        anniversary = cycle == "monthly" or (i - start_index) % 12 == 0
        if not anniversary:
            continue
        scale = 1 if cycle == "monthly" else 12
        previous_end = month_end(add_months(months[i], -1))
        if rng.random() < MONTHLY_CHURN[plan] * scale:
            rows[-1]["end"] = previous_end
            break
        roll = rng.random()
        if roll < EXPANSION_PROBABILITY * scale:
            if plan == "starter" and rng.random() < 0.25:
                plan, monthly, reason = "professional", float(PLANS["professional"]["price"]), "upgrade"
            else:
                monthly, reason = round(monthly * (1 + rng.uniform(0.10, 0.40)), 2), "expansion"
        elif roll < (EXPANSION_PROBABILITY + CONTRACTION_PROBABILITY) * scale:
            monthly, reason = round(monthly * (1 - rng.uniform(0.10, 0.25)), 2), "contraction"
        else:
            continue
        rows[-1]["end"] = previous_end
        rows.append(sub_row(tenant["id"], len(rows), plan, cycle, monthly, months[i], reason))
    return rows


def active_sub(subs: list[dict[str, Any]], on: dt.date) -> dict[str, Any] | None:
    for s in subs:
        if s["start"] <= on and (s["end"] is None or s["end"] >= on):
            return s
    return None


# -- usage, invoices, statistics --------------------------------------------------------------------------------------
def base_assets(rng: random.Random, plan: str) -> float:
    return {"starter": rng.uniform(18, 40), "professional": rng.uniform(150, 380), "enterprise": rng.uniform(1500, 3400)}[plan]


def simulate_usage(rng: random.Random, tenants: list[dict[str, Any]], by_tenant: dict[str, list[dict[str, Any]]], months: list[dt.date], end: dt.date) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    usage: list[dict[str, Any]] = []
    ops: list[dict[str, Any]] = []
    first_day = months[0]
    span = max((end - first_day).days, 1)
    source_lift = [e[0] for e in EVENTS if "data source" in e[1]]
    for tenant in tenants:
        subs = by_tenant[tenant["id"]]
        plan = tenant["_plan"]
        start = tenant["created_at"]
        base = base_assets(rng, plan)
        overshoot = rng.random() < 0.12  # a share of customers outgrow their plan limit and pay overage
        alert_rate = rng.uniform(0.006, 0.02)
        day = start
        last_end = subs[-1]["end"] or end
        while day <= min(last_end, end):
            sub = active_sub(subs, day)
            if sub is None:
                day += dt.timedelta(days=1)
                continue
            age = (day - start).days / 365
            assets = base * (1 + 0.35 * age) * rng.uniform(0.98, 1.02)
            limit = PLANS[sub["plan"]]["limit"]
            if overshoot and age > 0.8:
                assets = max(assets, limit * (1.05 + 0.05 * min(age, 3)))
            assets = min(assets, limit * 1.6) if plan != "enterprise" else min(assets, 6500)
            lift = 1.15 if any(day >= d for d in source_lift) else 1.0
            level_trend = 1.0 - 0.15 * (day - first_day).days / span
            alerts = poisson(rng, assets * alert_rate * season_factor(day) * lift * level_trend / 3)
            weekday = day.weekday() < 5
            usage.append(
                {
                    "tenant_id": tenant["id"], "date": day, "assets_monitored": round(assets), "alerts": alerts,
                    "briefings": 0 if plan == "starter" else (1 if weekday else 0),
                    "api_calls": 0 if plan == "starter" else round(assets * rng.uniform(2, 9) * (3 if plan == "enterprise" else 1)),
                    "uploads": 1 if rng.random() < 0.015 else 0,
                }
            )  # fmt: skip
            ops.append(ops_row(rng, tenant["id"], day, alerts, (day - first_day).days / span))
            day += dt.timedelta(days=1)
    return usage, ops


def ops_row(rng: random.Random, tenant_id: str, day: dt.date, alerts: int, progress: float) -> dict[str, Any]:
    levels = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for _ in range(alerts):
        r = rng.random()
        levels["critical" if r < 0.05 else "high" if r < 0.25 else "medium" if r < 0.70 else "low"] += 1
    ack_share = 0.62 + 0.20 * progress
    acknowledged = sum(1 for _ in range(alerts) if rng.random() < ack_share)
    dismissed = sum(1 for _ in range(alerts - acknowledged) if rng.random() < 0.45)
    confirmed = sum(1 for _ in range(acknowledged) if rng.random() < 0.82 + 0.10 * progress)
    corrected = sum(1 for _ in range(acknowledged - confirmed) if rng.random() < 0.5)
    median = round(rng.lognormvariate(math.log(42 - 18 * progress), 0.35), 1) if acknowledged else None
    return {
        "tenant_id": tenant_id, "date": day, "alerts_by_level": levels, "acknowledged": acknowledged, "dismissed": dismissed,
        "location_confirmed": confirmed, "location_corrected": corrected, "median_ack_minutes": median,
    }  # fmt: skip


def overage_for(plan: str, assets: int) -> float:
    spec = PLANS[plan]
    excess = max(assets - spec["limit"], 0)
    return float(math.ceil(excess / spec["unit"]) * spec["unit_price"])


def simulate_invoices(
    rng: random.Random, tenants: list[dict[str, Any]], by_tenant: dict[str, list[dict[str, Any]]], usage_by_tenant: dict[str, dict[dt.date, int]], months: list[dt.date], end: dt.date
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """One invoice per tenant and month. Monthly customers pay the subscription each month; annual customers pay the year in
    advance at the anniversary and receive an overage only invoice in months with overage. Totals are the sum of the lines."""
    invoices: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    for tenant in tenants:
        subs = by_tenant[tenant["id"]]
        start_index = tenant["_start_index"]
        for i in range(start_index, len(months)):
            first, last = months[i], month_end(months[i])
            sub = active_sub(subs, last)
            if sub is None:
                continue
            assets = usage_by_tenant[tenant["id"]].get(last, 0)
            overage = overage_for(sub["plan"], assets)
            entries: list[tuple[str, str, float]] = []
            period_end = last
            if sub["billing_cycle"] == "monthly" or (i - start_index) % 12 == 0:
                if sub["billing_cycle"] == "annual":
                    period_end = month_end(add_months(first, 11))
                entries.append(("subscription", f"{PLANS[sub['plan']]['name']} plan, {sub['billing_cycle']}", float(sub["price"])))
            if overage > 0:
                entries.append(("overage", f"Overage: {max(assets - PLANS[sub['plan']]['limit'], 0)} assets above the plan limit", overage))
            if not entries:
                continue
            if entries[0][0] == "subscription" and rng.random() < 0.015:
                entries.append(("credit", "Service credit", -round(entries[0][2] * 0.10, 2)))
            invoice_id = new_id("invoice", tenant["id"], first)
            total = round(sum(e[2] for e in entries), 2)
            issued = first
            age_months = (months[-1].year * 12 + months[-1].month) - (first.year * 12 + first.month)
            due = issued + dt.timedelta(days=30)
            if age_months == 0 or age_months == 1 and rng.random() < 0.20:
                status, paid = "open", None
            elif rng.random() < 0.02:
                status, paid = "overdue", None
            else:
                status, paid = "paid", issued + dt.timedelta(days=rng.randrange(5, 36))
                if paid > end:
                    status, paid = "open", None
            if status == "open" and due < end:
                status = "overdue"
            invoices.append(
                {
                    "id": invoice_id, "tenant_id": tenant["id"], "period_start": first, "period_end": period_end, "status": status,
                    "total": total, "issued_at": issued, "due_at": due, "paid_at": paid,
                }
            )  # fmt: skip
            for k, (line_type, description, amount) in enumerate(entries):
                lines.append({"id": new_id("line", invoice_id, k), "invoice_id": invoice_id, "line_type": line_type, "description": description, "amount": amount})
    return invoices, lines


def simulate_platform(rng: random.Random, months: list[dt.date], end: dt.date) -> list[dict[str, Any]]:
    rows = []
    first = months[0]
    span = max((end - first).days, 1)
    optimization = next((e[0] for e in EVENTS if "Latency" in e[1]), end)
    day = first
    while day <= end:
        p = (day - first).days / span
        drop = 0.72 if day >= optimization else 1.0
        p50 = max(rng.gauss(1800 - 600 * p, 60) * drop, 200)
        rows.append(
            {
                "date": day, "incidents_ingested": poisson(rng, (260 + 340 * p) * season_factor(day) * (0.8 if day.weekday() >= 5 else 1.0)),
                "p50_latency_ms": round(p50, 1), "p95_latency_ms": round(p50 * rng.uniform(3.2, 3.9), 1),
                "detection_delay_minutes_median": round(max(rng.gauss(95 - 50 * p, 6), 5), 1),
                "false_alert_rate": round(min(max(rng.gauss(0.18 - 0.11 * p, 0.012), 0.01), 0.5), 4),
            }
        )  # fmt: skip
        day += dt.timedelta(days=1)
    return rows


def simulate_marketing(rng: random.Random, months: list[dt.date]) -> list[dict[str, Any]]:
    rows = []
    for i, m in enumerate(months):
        total = trend(i, len(months), 14000, 52000) * rng.uniform(0.92, 1.08)
        for channel, share in CHANNELS:
            rows.append({"month": m, "channel": channel, "spend": round(total * share * rng.uniform(0.9, 1.1), 2)})
    return rows


# -- assembly ---------------------------------------------------------------------------------------------------------
def generate(seed: int = SEED, months: int = MONTHS, logo_scale: float = 1.0, end: dt.date = END) -> dict[str, list[dict[str, Any]]]:
    rng = random.Random(seed)  # noqa: S311 - synthetic data, not security sensitive
    series = month_list(months, end)
    tenants, subs = simulate_tenants(rng, series, logo_scale)
    by_tenant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in subs:
        by_tenant[s["tenant_id"]].append(s)
    usage, ops = simulate_usage(rng, tenants, by_tenant, series, end)
    usage_by_tenant: dict[str, dict[dt.date, int]] = defaultdict(dict)
    for u in usage:
        usage_by_tenant[u["tenant_id"]][u["date"]] = u["assets_monitored"]
    invoices, lines = simulate_invoices(rng, tenants, by_tenant, usage_by_tenant, series, end)
    plans = [
        {"id": k, "name": v["name"], "monthly_price": v["price"], "asset_limit": v["limit"], "overage_unit_size": v["unit"], "overage_unit_price": v["unit_price"]}
        for k, v in PLANS.items()
    ]
    events = [{"date": d, "label": label} for d, label in EVENTS if series[0] <= d <= end]
    public_tenants = [{k: v for k, v in t.items() if not k.startswith("_")} for t in tenants]
    public_subs = [{k: v for k, v in s.items() if not k.startswith("_")} for s in subs]
    return {
        "plans": plans, "tenants": public_tenants, "subscriptions": public_subs, "invoices": invoices, "invoice_lines": lines,
        "usage_daily": usage, "ops_stats_daily": ops, "platform_stats_daily": simulate_platform(rng, series, end),
        "marketing_spend": simulate_marketing(rng, series), "business_events": events,
    }  # fmt: skip


def cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, dict):
        import json

        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return value


def write_csv(data: dict[str, list[dict[str, Any]]], out: Path) -> dict[str, int]:
    out.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, columns in FILES.items():
        with (out / f"{name}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(columns)
            for row in data[name]:
                writer.writerow([cell(row.get(c)) for c in columns])
        counts[name] = len(data[name])
    return counts


# -- checks -----------------------------------------------------------------------------------------------------------
def month_end_mrr(subs: list[dict[str, Any]], day: dt.date) -> float:
    total = 0.0
    for s in subs:
        if s["start"] <= day and (s["end"] is None or s["end"] >= day):
            total += s["price"] / 12 if s["billing_cycle"] == "annual" else s["price"]
    return total


def verify(data: dict[str, list[dict[str, Any]]], months: int, end: dt.date) -> list[str]:
    """Acceptance checks from the specification. Returns a list of problems (empty when the data is acceptable)."""
    problems: list[str] = []
    series = month_list(months, end)
    mrr = [month_end_mrr(data["subscriptions"], month_end(m)) for m in series]
    if any(v < 0 for v in mrr):
        problems.append("MRR is negative in some month")
    if any(v == 0 for v in mrr[1:]):
        problems.append("MRR drops to zero")
    lines: dict[str, float] = defaultdict(float)
    for line in data["invoice_lines"]:
        lines[line["invoice_id"]] += line["amount"]
    bad = [i["id"] for i in data["invoices"] if abs(i["total"] - lines[i["id"]]) > 0.011]
    if bad:
        problems.append(f"{len(bad)} invoices do not equal the sum of their lines")
    by_tenant = defaultdict(list)
    for s in data["subscriptions"]:
        by_tenant[s["tenant_id"]].append(s)
    for tenant_id, subs in by_tenant.items():
        ordered = sorted(subs, key=lambda s: s["start"])
        for a, b in zip(ordered, ordered[1:], strict=False):
            if a["end"] is None or b["start"] != a["end"] + dt.timedelta(days=1):
                problems.append(f"subscriptions of {tenant_id} overlap or leave a gap")
                break
    return problems


def ending_arr(data: dict[str, list[dict[str, Any]]], end: dt.date) -> float:
    return month_end_mrr(data["subscriptions"], month_end(dt.date(end.year, end.month, 1))) * 12


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--months", type=int, default=MONTHS)
    parser.add_argument("--logo-scale", type=float, default=1.0)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args(argv)
    data = generate(args.seed, args.months, args.logo_scale)
    counts = write_csv(data, args.out)
    problems = verify(data, args.months, END)
    for name, n in counts.items():
        print(f"{name:22s} {n:>8d}")
    print(f"ending ARR (synthetic): {ending_arr(data, END):,.0f} USD")
    for p in problems:
        print("PROBLEM:", p, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
