"use client";

import { useEffect, useState } from "react";
import { echarts } from "@/components/app/echarts-ref";
import { ChartCard, axis } from "@/components/app/chart-card";
import { DashControls, useRange } from "@/components/app/dash-controls";
import { DataTable } from "@/components/app/data-table";
import { Spark } from "@/components/app/spark";
import { DemoBadge, Disclaimer, ErrorState, PageHeader } from "@/components/app/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { qs } from "@/lib/api";
import { num, pct, title, usd } from "@/lib/app/format";
import { useApi } from "@/lib/app/use-api";

type Chg = { value: number; change: number | null; change_pct: number | null; previous: number | null };
type Summary = {
  mrr: Chg;
  arr: Chg;
  arpa: Chg;
  customers: Chg;
  net_new_mrr: Chg;
  as_of: string;
  month: string;
  cac: number;
  cac_trailing_3m: number;
  ltv: number;
  payback_months: number;
  quick_ratio: number;
  logo_churn_rate: number;
  grr_trailing_12m: number;
  nrr_trailing_12m: number;
  overage_this_month: number;
  overdue_invoices: number;
  overdue_total: number;
};
type Mrr = {
  items: { period: string; mrr: number; arr: number; customers: number; arpa: number }[];
  stack: { dimension: string; series: { value: string; points: { period: string; mrr: number }[] }[] };
  annotations: { date: string; label: string }[];
};
type Moves = {
  items: {
    period: string;
    new_mrr: number;
    expansion_mrr: number;
    contraction_mrr: number;
    churned_mrr: number;
    net_new_mrr: number;
  }[];
};
type Dim = {
  items: { value: string; mrr: number; customers: number; share_pct: number; change_pct: number | null }[];
  total_mrr: number;
};
type Forecast = {
  history: { month: string; mrr: number }[];
  forecast: { month: string; mrr: number; lower_80: number; upper_80: number }[];
  label: string;
  method: string;
};
type Cohorts = {
  items: { cohort: string; customers: number; points: { months_since: number; retention: number }[] }[];
};
type Unit = {
  items: {
    month: string;
    cac: number | null;
    ltv: number | null;
    quick_ratio: number | null;
    payback_months: number | null;
    logo_churn_rate: number | null;
    arpa: number | null;
  }[];
};
type Tenants = {
  items: {
    tenant_id: string;
    tenant: string;
    plan: string;
    region: string;
    industry: string;
    channel: string;
    mrr: number;
  }[];
};
type Filters = { plan?: string; region?: string; industry?: string; channel?: string };

const month = (s: string) => s.slice(0, 7);

function donutData(items: { value: string; mrr: number }[]) {
  const top = items.slice(0, 4);
  const rest = items.slice(4).reduce((s, i) => s + i.mrr, 0);
  return [
    ...top.map((i) => ({ name: title(i.value), key: i.value, value: Math.round(i.mrr) })),
    ...(rest ? [{ name: "Other", key: "", value: Math.round(rest) }] : []),
  ];
}

export default function Revenue() {
  const [range, setRange] = useRange("36m", "month");
  const [f, setF] = useState<Filters>({});
  const [open, setOpen] = useState<Tenants["items"][number] | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [mapReady, setMapReady] = useState(false);
  const flt = qs(f);
  const join = (a: string, b: string) => (a ? `${a}&${b.replace(/^\?/, "")}` : b);
  const rq = qs({ from: range.from, to: range.to, granularity: range.granularity });
  const summary = useApi<Summary>(
    `/platform/revenue/summary${join(flt, qs({ compare: range.compare ? "previous_period" : "previous_period" }))}`.replace(
      "&?",
      "&",
    ),
  );
  const mrr = useApi<Mrr>(`/platform/revenue/mrr${join(rq, qs({ stack: "plan", ...f }))}`.replace("&?", "&"));
  const moves = useApi<Moves>(`/platform/revenue/movements${join(rq, qs(f))}`.replace("&?", "&"));
  const plan = useApi<Dim>("/platform/revenue/dimensions?dimension=plan&compare=previous_period");
  const region = useApi<Dim>("/platform/revenue/dimensions?dimension=region&compare=previous_period");
  const industry = useApi<Dim>("/platform/revenue/dimensions?dimension=industry&compare=previous_period");
  const country = useApi<Dim>("/platform/revenue/dimensions?dimension=country");
  const forecast = useApi<Forecast>(`/platform/revenue/forecast${flt}`);
  const cohorts = useApi<Cohorts>("/platform/revenue/cohorts?max_months=24");
  const unit = useApi<Unit>(`/platform/revenue/unit-economics${qs({ from: range.from, to: range.to })}`);
  const tenants = useApi<Tenants>(
    `/platform/revenue/tenants${join(qs({ limit: 200 }), qs(f))}`.replace("&?", "&"),
  );

  useEffect(() => {
    fetch("/geo/countries.geojson")
      .then((r) => r.json())
      .then((g) => {
        echarts.registerMap("world", g, undefined);
        setMapReady(true);
      })
      .catch(() => undefined);
  }, []);

  const s = summary.data;
  const hist = mrr.data?.items ?? [];
  const pivot = (key: keyof Mrr["items"][number]) => hist.map((h) => h[key] as number);
  const periods = hist.map((h) => month(h.period));
  const series = mrr.data?.stack.series ?? [];
  const events = (mrr.data?.annotations ?? []).filter((a) => periods.includes(month(a.date)));
  const apply = (k: keyof Filters, v?: string) =>
    setF((cur) =>
      v && cur[k] !== v
        ? { ...cur, [k]: v }
        : (() => {
            const rest = { ...cur };
            delete rest[k];
            return rest;
          })(),
    );
  const err = summary.error ?? mrr.error;
  if (err) return <ErrorState error={err} onRetry={() => (summary.reload(), mrr.reload())} />;

  const top10 = [...(tenants.data?.items ?? [])].sort((a, b) => b.mrr - a.mrr).slice(0, 10);
  const total = (tenants.data?.items ?? []).reduce((a, t) => a + t.mrr, 0) || 1;
  let acc = 0;
  const pareto = top10.map((t) => ((acc += t.mrr), (acc / total) * 100));
  const ue = unit.data?.items ?? [];
  const cohortRows = cohorts.data?.items ?? [];
  const maxM = Math.max(0, ...cohortRows.flatMap((c) => c.points.map((p) => p.months_since)));
  const regionItems = region.data?.items ?? [];

  const kpis: { label: string; value: string; delta?: number | null; spark?: number[]; invert?: boolean }[] =
    [
      { label: "MRR", value: usd(s?.mrr.value), delta: s?.mrr.change_pct, spark: pivot("mrr") },
      { label: "ARR", value: usd(s?.arr.value, true), delta: s?.arr.change_pct, spark: pivot("arr") },
      {
        label: "Net new MRR",
        value: usd(s?.net_new_mrr.value),
        delta: s?.net_new_mrr.change_pct,
        spark: moves.data?.items.map((m) => m.net_new_mrr),
      },
      { label: "Net revenue retention", value: pct(s ? s.nrr_trailing_12m * 100 : null), spark: undefined },
      { label: "Gross revenue retention", value: pct(s ? s.grr_trailing_12m * 100 : null) },
      {
        label: "Logo churn",
        value: pct(s ? s.logo_churn_rate * 100 : null, 2),
        spark: ue.map((u) => (u.logo_churn_rate ?? 0) * 100),
        invert: true,
      },
      { label: "ARPA", value: usd(s?.arpa.value), delta: s?.arpa.change_pct, spark: pivot("arpa") },
      {
        label: "Active customers",
        value: num(s?.customers.value),
        delta: s?.customers.change_pct,
        spark: pivot("customers"),
      },
      { label: "Quick ratio", value: num(s?.quick_ratio, 1), spark: ue.map((u) => u.quick_ratio ?? 0) },
      {
        label: "CAC payback",
        value: s ? `${num(s.payback_months, 1)} months` : "n/a",
        spark: ue.map((u) => u.payback_months ?? 0),
        invert: true,
      },
    ];

  return (
    <>
      <PageHeader
        title="Platform revenue"
        description={`Subscription metrics as of ${s ? month(s.month) : "the latest month"}. Selecting a plan, region or industry filters the page.`}
        badge={<DemoBadge label="Demo data, synthetic" />}
        actions={
          Object.keys(f).length ? (
            <Button size="sm" variant="secondary" onClick={() => setF({})}>
              Clear filters:{" "}
              {Object.entries(f)
                .map(([k, v]) => `${k} ${title(String(v))}`)
                .join(", ")}
            </Button>
          ) : null
        }
      />
      <DashControls
        range={range}
        onChange={setRange}
        asOf={s?.as_of}
        granularities={["month"]}
        showCompare={false}
      />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        {kpis.map((k) => (
          <div key={k.label} className="rounded-card border border-line bg-white p-4 shadow-e1">
            <div className="text-caption font-medium uppercase tracking-wide text-slate-600">{k.label}</div>
            <div className="mt-1 text-h4 tabular-nums text-ink">{summary.loading && !s ? "…" : k.value}</div>
            {k.delta != null ? (
              <div className={`text-caption ${k.delta >= 0 !== !!k.invert ? "text-pos" : "text-neg"}`}>
                {k.delta >= 0 ? "+" : ""}
                {num(k.delta, 1)}% vs previous month
              </div>
            ) : (
              <div className="text-caption text-slate-500">Trailing 12 months or latest</div>
            )}
            {k.spark ? <Spark values={k.spark} /> : null}
          </div>
        ))}
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <ChartCard
          className="xl:col-span-2"
          title="MRR over time"
          description="By plan, with the total. Vertical lines mark business events."
          loading={mrr.loading}
          height={320}
          option={{
            legend: { bottom: 0 },
            grid: { left: 64, right: 16, top: 24, bottom: 56 },
            xAxis: { ...axis.x(), data: periods, boundaryGap: false },
            yAxis: axis.y("MRR (USD)"),
            series: [
              ...series.map((sr) => ({
                name: title(sr.value),
                type: "line",
                stack: "mrr",
                areaStyle: { opacity: 0.8 },
                symbol: "none",
                data: sr.points.map((p) => p.mrr),
              })),
              {
                name: "Total",
                type: "line",
                symbol: "none",
                lineStyle: { color: "#0B1B33", width: 2 },
                itemStyle: { color: "#0B1B33" },
                data: hist.map((h) => h.mrr),
                markLine: {
                  symbol: "none",
                  lineStyle: { color: "#6C7A89", type: "dashed" },
                  label: { show: false },
                  data: events.map((a) => ({ xAxis: month(a.date), name: a.label })),
                  tooltip: { show: true, formatter: (p: { name: string }) => p.name },
                },
              },
            ],
          }}
          table={{
            headers: ["Month", ...series.map((x) => title(x.value)), "Total"],
            rows: hist.map((h, i) => [
              month(h.period),
              ...series.map((x) => Math.round(x.points[i]?.mrr ?? 0)),
              Math.round(h.mrr),
            ]),
          }}
        />
        <ChartCard
          title="MRR movements"
          description="New, expansion, contraction and churn per month"
          loading={moves.loading}
          option={{
            legend: { bottom: 0 },
            grid: { left: 64, right: 16, top: 16, bottom: 56 },
            xAxis: { ...axis.x(), data: (moves.data?.items ?? []).map((m) => month(m.period)) },
            yAxis: axis.y("MRR change (USD)"),
            series: [
              ["New", "new_mrr", 1],
              ["Expansion", "expansion_mrr", 1],
              ["Contraction", "contraction_mrr", -1],
              ["Churn", "churned_mrr", -1],
            ]
              .map(([n, k, sign]) => ({
                name: n,
                type: "bar",
                stack: "m",
                data: (moves.data?.items ?? []).map(
                  (m) =>
                    (m[k as keyof Moves["items"][number]] as number) *
                    (sign as number) *
                    (sign === -1 && (m[k as keyof Moves["items"][number]] as number) < 0 ? -1 : 1),
                ),
              }))
              .concat([
                {
                  name: "Net new",
                  type: "line",
                  data: (moves.data?.items ?? []).map((m) => m.net_new_mrr),
                } as never,
              ]),
          }}
          table={{
            headers: ["Month", "New", "Expansion", "Contraction", "Churn", "Net new"],
            rows: (moves.data?.items ?? []).map((m) => [
              month(m.period),
              m.new_mrr,
              m.expansion_mrr,
              -Math.abs(m.contraction_mrr),
              -Math.abs(m.churned_mrr),
              m.net_new_mrr,
            ]),
          }}
        />
        <ChartCard
          title="Revenue mix"
          description="Subscription versus usage overage, latest month. Earlier months are not available from the API."
          loading={summary.loading}
          option={{
            legend: { bottom: 0 },
            grid: { left: 64, right: 16, top: 16, bottom: 56 },
            xAxis: { ...axis.x(), data: [s ? month(s.month) : ""] },
            yAxis: axis.y("USD"),
            series: [
              {
                name: "Subscription",
                type: "bar",
                stack: "r",
                data: [Math.round((s?.mrr.value ?? 0) - (s?.overage_this_month ?? 0))],
              },
              { name: "Overage", type: "bar", stack: "r", data: [Math.round(s?.overage_this_month ?? 0)] },
            ],
          }}
          table={{
            headers: ["Component", "USD"],
            rows: [
              ["Subscription", Math.round((s?.mrr.value ?? 0) - (s?.overage_this_month ?? 0))],
              ["Overage", Math.round(s?.overage_this_month ?? 0)],
            ],
          }}
        />
        <ChartCard
          title="Forecast"
          description={
            forecast.data
              ? `${forecast.data.label}. Method: ${forecast.data.method}. Shaded band is an 80 percent interval.`
              : "Six month projection"
          }
          badge={<Badge tone="warning">Estimate</Badge>}
          loading={forecast.loading}
          option={{
            legend: { bottom: 0 },
            grid: { left: 64, right: 16, top: 16, bottom: 56 },
            xAxis: {
              ...axis.x(),
              data: [
                ...(forecast.data?.history ?? []).slice(-18).map((h) => month(h.month)),
                ...(forecast.data?.forecast ?? []).map((h) => month(h.month)),
              ],
            },
            yAxis: axis.y("MRR (USD)"),
            series: (() => {
              const h = (forecast.data?.history ?? []).slice(-18);
              const fc = forecast.data?.forecast ?? [];
              const pad = h.length;
              const nul = Array(pad).fill(null);
              return [
                {
                  name: "History",
                  type: "line",
                  data: [...h.map((x) => x.mrr), ...Array(fc.length).fill(null)],
                },
                {
                  name: "Forecast",
                  type: "line",
                  lineStyle: { type: "dashed" },
                  data: [
                    ...Array(Math.max(0, pad - 1)).fill(null),
                    h[pad - 1]?.mrr ?? null,
                    ...fc.map((x) => x.mrr),
                  ],
                },
                {
                  name: "Lower 80%",
                  type: "line",
                  stack: "band",
                  symbol: "none",
                  lineStyle: { opacity: 0 },
                  data: [...nul, ...fc.map((x) => x.lower_80)],
                },
                {
                  name: "80% interval",
                  type: "line",
                  stack: "band",
                  symbol: "none",
                  lineStyle: { opacity: 0 },
                  areaStyle: { opacity: 0.18 },
                  data: [...nul, ...fc.map((x) => x.upper_80 - x.lower_80)],
                },
              ];
            })(),
          }}
          table={{
            headers: ["Month", "Forecast", "Lower 80%", "Upper 80%"],
            rows: (forecast.data?.forecast ?? []).map((x) => [
              month(x.month),
              Math.round(x.mrr),
              Math.round(x.lower_80),
              Math.round(x.upper_80),
            ]),
          }}
        />
        <ChartCard
          className="xl:col-span-2"
          title="Cohort retention"
          description="Share of each signup cohort's starting MRR still billed, by months since signup"
          loading={cohorts.loading}
          height={Math.max(260, cohortRows.length * 14 + 80)}
          option={{
            tooltip: {
              position: "top",
              formatter: (p: { value: number[] }) =>
                `Cohort ${month(cohortRows[p.value[1] as number]?.cohort ?? "")}, month ${p.value[0]}: ${num(p.value[2], 0)}%`,
            },
            grid: { left: 70, right: 24, top: 8, bottom: 56 },
            xAxis: {
              type: "category",
              name: "Months since signup",
              nameLocation: "middle",
              nameGap: 28,
              data: Array.from({ length: maxM + 1 }, (_, i) => i),
            },
            yAxis: { type: "category", inverse: true, data: cohortRows.map((c) => month(c.cohort)) },
            visualMap: {
              min: 50,
              max: 150,
              calculable: false,
              orient: "horizontal",
              left: "center",
              bottom: 0,
              inRange: { color: ["#D55E5E", "#FBEFD9", "#2F74D8"] },
            },
            series: [
              {
                type: "heatmap",
                data: cohortRows.flatMap((c, y) =>
                  c.points.map((p) => [p.months_since, y, Math.round(p.retention * 100)]),
                ),
              },
            ],
          }}
          table={{
            headers: ["Cohort", "Customers", "Month 0", "Month 6", "Month 12", "Month 24"],
            rows: cohortRows.map((c) => [
              month(c.cohort),
              c.customers,
              ...[0, 6, 12, 24].map((m) => {
                const p = c.points.find((x) => x.months_since === m);
                return p ? `${Math.round(p.retention * 100)}%` : null;
              }),
            ]),
          }}
        />
        <ChartCard
          title="ARR by region"
          description="Click a bar to filter"
          loading={region.loading}
          onClickPoint={(p) => apply("region", regionItems.find((r) => r.value === p.name)?.value)}
          option={{
            grid: { left: 110, right: 40, top: 8, bottom: 28 },
            xAxis: axis.y("ARR (USD)"),
            yAxis: { type: "category", inverse: true, data: regionItems.map((r) => r.value) },
            tooltip: { trigger: "axis" },
            series: [
              {
                type: "bar",
                data: regionItems.map((r) => Math.round(r.mrr * 12)),
                label: {
                  show: true,
                  position: "right",
                  formatter: (p: { value: number }) => usd(p.value, true),
                },
              },
            ],
          }}
          table={{
            headers: ["Region", "ARR (USD)", "Customers", "Share"],
            rows: regionItems.map((r) => [r.value, Math.round(r.mrr * 12), r.customers, `${r.share_pct}%`]),
          }}
        />
        <ChartCard
          title="ARR by country"
          description="Darker is higher annualized revenue"
          loading={country.loading || !mapReady}
          height={300}
          option={
            mapReady
              ? {
                  tooltip: {
                    trigger: "item",
                    formatter: (p: { name: string; value: number }) =>
                      `${p.name}: ${p.value ? usd(p.value) : "none"}`,
                  },
                  visualMap: {
                    min: 0,
                    max: Math.max(1, ...(country.data?.items ?? []).map((c) => c.mrr * 12)),
                    orient: "horizontal",
                    left: "center",
                    bottom: 0,
                    calculable: false,
                    inRange: { color: ["#E6EFFB", "#2F74D8", "#12305A"] },
                    formatter: (v: number) => usd(v, true),
                  },
                  series: [
                    {
                      type: "map",
                      map: "world",
                      nameProperty: "iso2",
                      roam: false,
                      emphasis: { disabled: false },
                      data: (country.data?.items ?? []).map((c) => ({
                        name: c.value,
                        value: Math.round(c.mrr * 12),
                      })),
                    },
                  ],
                }
              : null
          }
          table={{
            headers: ["Country", "ARR (USD)", "Customers"],
            rows: (country.data?.items ?? []).map((c) => [c.value, Math.round(c.mrr * 12), c.customers]),
          }}
        />
        <ChartCard
          title="Revenue by industry"
          description="Click a slice to filter"
          loading={industry.loading}
          onClickPoint={(p) =>
            apply(
              "industry",
              donutData(industry.data?.items ?? []).find((d) => d.name === p.name)?.key || undefined,
            )
          }
          option={{
            tooltip: { trigger: "item", formatter: "{b}: {c} USD ({d}%)" },
            legend: { bottom: 0 },
            series: [
              {
                type: "pie",
                radius: ["45%", "68%"],
                label: { formatter: "{b}\n{d}%" },
                data: donutData(industry.data?.items ?? []),
              },
            ],
          }}
          table={{
            headers: ["Industry", "MRR (USD)", "Customers", "Share"],
            rows: (industry.data?.items ?? []).map((i) => [
              i.value,
              Math.round(i.mrr),
              i.customers,
              `${i.share_pct}%`,
            ]),
          }}
        />
        <ChartCard
          title="Revenue by plan"
          description="Click a bar to filter"
          loading={plan.loading}
          onClickPoint={(p) =>
            apply("plan", (plan.data?.items ?? []).find((i) => title(i.value) === p.name)?.value)
          }
          option={{
            grid: { left: 90, right: 56, top: 8, bottom: 28 },
            xAxis: axis.y("MRR (USD)"),
            yAxis: {
              type: "category",
              inverse: true,
              data: (plan.data?.items ?? []).map((i) => title(i.value)),
            },
            tooltip: { trigger: "axis" },
            series: [
              {
                type: "bar",
                data: (plan.data?.items ?? []).map((i) => Math.round(i.mrr)),
                label: {
                  show: true,
                  position: "right",
                  formatter: (p: { value: number }) => usd(p.value, true),
                },
              },
            ],
          }}
          table={{
            headers: ["Plan", "MRR (USD)", "Customers", "Share"],
            rows: (plan.data?.items ?? []).map((i) => [
              title(i.value),
              Math.round(i.mrr),
              i.customers,
              `${i.share_pct}%`,
            ]),
          }}
        />
        <ChartCard
          title="Customer concentration"
          description="Top 10 customers by MRR with cumulative share of the filtered total"
          loading={tenants.loading}
          option={{
            legend: { bottom: 0 },
            grid: { left: 64, right: 48, top: 16, bottom: 72 },
            xAxis: {
              ...axis.x(),
              data: top10.map((t) => t.tenant),
              axisLabel: { rotate: 35, width: 90, overflow: "truncate" },
            },
            yAxis: [
              axis.y("MRR (USD)"),
              { ...axis.y("Cumulative share (%)"), max: 100, splitLine: { show: false } },
            ],
            series: [
              { name: "MRR", type: "bar", data: top10.map((t) => Math.round(t.mrr)) },
              {
                name: "Cumulative share",
                type: "line",
                yAxisIndex: 1,
                data: pareto.map((v) => Math.round(v * 10) / 10),
              },
            ],
          }}
          table={{
            headers: ["Customer", "MRR (USD)", "Cumulative share %"],
            rows: top10.map((t, i) => [t.tenant, Math.round(t.mrr), Math.round((pareto[i] ?? 0) * 10) / 10]),
          }}
        />
        <ChartCard
          title="Unit economics"
          description="CAC and LTV in USD, LTV to CAC ratio on the right axis. LTV assumes an 80 percent gross margin."
          loading={unit.loading}
          option={{
            legend: { bottom: 0 },
            grid: { left: 64, right: 48, top: 16, bottom: 56 },
            xAxis: { ...axis.x(), data: ue.map((u) => month(u.month)) },
            yAxis: [axis.y("USD"), { ...axis.y("LTV to CAC"), splitLine: { show: false } }],
            series: [
              { name: "CAC", type: "line", data: ue.map((u) => u.cac) },
              { name: "LTV", type: "line", data: ue.map((u) => u.ltv) },
              {
                name: "LTV to CAC",
                type: "bar",
                yAxisIndex: 1,
                data: ue.map((u) => (u.cac && u.ltv ? Math.round((u.ltv / u.cac) * 10) / 10 : null)),
              },
            ],
          }}
          table={{
            headers: ["Month", "CAC", "LTV", "LTV to CAC", "Payback (months)"],
            rows: ue.map((u) => [
              month(u.month),
              u.cac,
              u.ltv,
              u.cac && u.ltv ? Math.round((u.ltv / u.cac) * 10) / 10 : null,
              u.payback_months,
            ]),
          }}
        />
      </div>

      <h2 className="mb-2 mt-6 text-h4 text-ink">Billing health</h2>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="rounded-card border border-line bg-white p-4">
          <div className="text-caption uppercase text-slate-600">Overdue invoices</div>
          <div className="text-h4 text-danger">{num(s?.overdue_invoices)}</div>
        </div>
        <div className="rounded-card border border-line bg-white p-4">
          <div className="text-caption uppercase text-slate-600">Overdue total</div>
          <div className="text-h4 text-ink">{usd(s?.overdue_total)}</div>
        </div>
        <div className="rounded-card border border-line bg-white p-4">
          <div className="text-caption uppercase text-slate-600">Paid, last 12 months</div>
          <div className="text-h4 text-ink">
            {usd((s as unknown as { paid_last_12_months?: number })?.paid_last_12_months, true)}
          </div>
        </div>
      </div>
      <p className="mt-2 text-caption text-slate-600">
        Per-invoice aging buckets are not exposed by the platform API yet, so only totals are shown.
      </p>

      <h2 className="mb-2 mt-6 text-h4 text-ink">Customers</h2>
      <DataTable
        rows={(tenants.data?.items ?? []).slice(0, showAll ? 500 : 25)}
        rowKey={(t) => t.tenant_id}
        caption="Customers by MRR"
        exportName="customers"
        onRowClick={setOpen}
        columns={[
          { key: "t", header: "Customer", cell: (t) => t.tenant, value: (t) => t.tenant },
          {
            key: "p",
            header: "Plan",
            cell: (t) => <Badge tone="brand">{title(t.plan)}</Badge>,
            value: (t) => t.plan,
          },
          { key: "m", header: "MRR", cell: (t) => usd(t.mrr), value: (t) => t.mrr, align: "right" },
          { key: "r", header: "Region", cell: (t) => t.region, value: (t) => t.region },
          { key: "i", header: "Industry", cell: (t) => title(t.industry), value: (t) => t.industry },
          { key: "c", header: "Channel", cell: (t) => t.channel, value: (t) => t.channel },
        ]}
      />
      {(tenants.data?.items.length ?? 0) > 25 ? (
        <Button className="mt-3" size="sm" variant="secondary" onClick={() => setShowAll((v) => !v)}>
          {showAll ? "Show top 25" : `Show all ${tenants.data?.items.length} customers`}
        </Button>
      ) : null}
      <Dialog open={!!open} onOpenChange={(o) => !o && setOpen(null)}>
        <DialogContent side="right" className="max-w-md">
          <DialogTitle className="text-h4 text-ink">{open?.tenant}</DialogTitle>
          <DialogDescription className="text-small text-slate-600">
            Demo customer. Subscription history, invoices and usage per customer are not exposed by the
            platform API yet.
          </DialogDescription>
          {open ? (
            <dl className="mt-4 grid grid-cols-2 gap-2 text-small">
              <dt className="text-slate-600">Plan</dt>
              <dd>{title(open.plan)}</dd>
              <dt className="text-slate-600">MRR</dt>
              <dd>{usd(open.mrr)}</dd>
              <dt className="text-slate-600">ARR</dt>
              <dd>{usd(open.mrr * 12)}</dd>
              <dt className="text-slate-600">Region</dt>
              <dd>{open.region}</dd>
              <dt className="text-slate-600">Industry</dt>
              <dd>{title(open.industry)}</dd>
              <dt className="text-slate-600">Channel</dt>
              <dd>{open.channel}</dd>
            </dl>
          ) : null}
        </DialogContent>
      </Dialog>
      <div className="mt-6">
        <Disclaimer />
      </div>
    </>
  );
}
