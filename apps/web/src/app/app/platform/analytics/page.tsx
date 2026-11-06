"use client";

import { ChartCard, axis } from "@/components/app/chart-card";
import { DashControls, useRange } from "@/components/app/dash-controls";
import { DataTable } from "@/components/app/data-table";
import { Disclaimer, ErrorState, Kpi, PageHeader } from "@/components/app/states";
import { evalRows } from "@/content/eval";
import { qs } from "@/lib/api";
import { ago, minutes, num, pct, title } from "@/lib/app/format";
import { useApi } from "@/lib/app/use-api";

type Pipeline = {
  freshness: {
    source: string;
    latest_ingested_at: string | null;
    minutes_since_ingest: number | null;
    records: number;
  }[];
  latency_ms: { period: string; p50: number; p95: number }[];
  routing_breakdown: Record<string, number>;
  source_mix: { source: string; events: number; records: number }[];
};
type Quality = {
  location_confirmation: { period: string; location_confirmed: number; location_corrected: number }[];
  detection_delay_and_false_alerts: {
    period: string;
    detection_delay_minutes_median: number | null;
    false_alert_rate: number | null;
  }[];
  detection_delay_vs_hazard_feeds: {
    events_with_both: number;
    median_minutes_news_after_hazard_feed: number | null;
  };
  location_confirmation_rate: number | null;
};
type Incidents = {
  groups: string[];
  series: { period: string; counts: Record<string, number>; total: number }[];
  totals: Record<string, number>;
};
type Exposure = {
  by_region: { region: string; assets_exposed: number; exposures: number; tenants: number }[];
};
type Alerts = {
  totals: { alerts: number; dismissed: number; avg_minutes_to_acknowledge: number | null };
  false_alert_rate: { period: string; rate: number | null }[];
};

const ROUTES: Record<string, string> = {
  accept: "Accepted by BELA",
  fallback: "Gazetteer fallback",
  adjudicate: "LLM adjudication",
  unresolved: "Unresolved",
};
const num1 = (s: string) => parseFloat(s.replace("%", ""));

export default function PlatformAnalytics() {
  const [range, setRange] = useRange("90d", "week");
  const q = qs({ from: range.from, to: range.to, granularity: range.granularity });
  const pipe = useApi<Pipeline>(`/platform/analytics/pipeline${q}`);
  const qual = useApi<Quality>(`/platform/analytics/quality${q}`);
  const inc = useApi<Incidents>(
    `/platform/analytics/incidents${qs({ from: range.from, to: range.to, granularity: range.granularity, by: "type" })}`,
  );
  const exp = useApi<Exposure>(`/platform/analytics/exposure${q}`);
  const al = useApi<Alerts>(`/platform/analytics/alerts${q}`);
  const err = pipe.error ?? qual.error ?? inc.error;
  if (err) return <ErrorState error={err} onRetry={() => (pipe.reload(), qual.reload(), inc.reload())} />;

  const route = pipe.data?.routing_breakdown ?? {};
  const routeNames = Object.keys(route).filter((k) => route[k]);
  const lat = pipe.data?.latency_ms ?? [];
  const delay = (qual.data?.detection_delay_and_false_alerts ?? []).filter(
    (d) => d.detection_delay_minutes_median != null,
  );
  const mix = (pipe.data?.source_mix ?? []).slice(0, 5);

  return (
    <>
      <PageHeader
        title="Pipeline analytics"
        description="How well the location pipeline and alerting work across all organisations. Counts only; no organisation's asset locations appear here."
      />
      <DashControls range={range} onChange={setRange} showCompare={false} />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi
          label="Location confirmation rate"
          value={pct(
            qual.data?.location_confirmation_rate != null ? qual.data.location_confirmation_rate * 100 : null,
          )}
          hint="Reviewer confirmed of reviewed"
        />
        <Kpi label="Alerts raised" value={num(al.data?.totals.alerts)} />
        <Kpi
          label="False alert rate"
          value={pct(
            al.data && al.data.totals.alerts
              ? (al.data.totals.dismissed / al.data.totals.alerts) * 100
              : null,
          )}
          hint="Dismissed as not relevant or wrong"
        />
        <Kpi
          label="Median news delay after feed"
          value={minutes(qual.data?.detection_delay_vs_hazard_feeds.median_minutes_news_after_hazard_feed)}
          hint={`${qual.data?.detection_delay_vs_hazard_feeds.events_with_both ?? 0} events seen by both`}
        />
      </div>
      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <ChartCard
          title="Hybrid versus baselines"
          description="Share of test locations within 25 km and 161 km (evaluation test split)"
          option={{
            legend: { bottom: 0 },
            grid: { left: 48, right: 16, top: 16, bottom: 56 },
            xAxis: { ...axis.x(), data: evalRows.map((r) => r.id), axisLabel: { interval: 0 } },
            yAxis: { ...axis.y("Accuracy (%)"), max: 100 },
            series: [
              { name: "Within 25 km", type: "bar", data: evalRows.map((r) => num1(r.acc25)) },
              { name: "Within 161 km", type: "bar", data: evalRows.map((r) => num1(r.acc161)) },
            ],
          }}
          table={{
            headers: ["System", "Description", "Within 25 km", "Within 161 km"],
            rows: evalRows.map((r) => [r.id, r.name, r.acc25, r.acc161]),
          }}
        />
        <ChartCard
          title="Routing breakdown"
          description="Where each place mention was resolved"
          loading={pipe.loading}
          option={{
            tooltip: { trigger: "item" },
            series: [
              {
                type: "sankey",
                left: 8,
                right: 120,
                top: 8,
                bottom: 8,
                data: [{ name: "Mentions" }, ...routeNames.map((k) => ({ name: ROUTES[k] ?? title(k) }))],
                links: routeNames.map((k) => ({
                  source: "Mentions",
                  target: ROUTES[k] ?? title(k),
                  value: route[k],
                })),
                label: { color: "inherit" },
              },
            ],
          }}
          table={{
            headers: ["Route", "Mentions"],
            rows: routeNames.map((k) => [ROUTES[k] ?? title(k), route[k] ?? 0]),
          }}
        />
        <ChartCard
          title="Detection delay"
          description="Median minutes between the hazard feed and the first news report"
          loading={qual.loading}
          empty="No events were seen by both a hazard feed and the news in this period."
          option={{
            grid: { left: 56, right: 16, top: 16, bottom: 40 },
            xAxis: { ...axis.x(), data: delay.map((d) => d.period) },
            yAxis: axis.y("Minutes"),
            series: [{ type: "line", data: delay.map((d) => d.detection_delay_minutes_median) }],
          }}
          table={{
            headers: ["Period", "Median minutes"],
            rows: delay.map((d) => [d.period, d.detection_delay_minutes_median]),
          }}
        />
        <ChartCard
          title="Latency"
          description="Location pipeline latency per passage (ms)"
          loading={pipe.loading}
          option={{
            legend: { bottom: 0 },
            grid: { left: 56, right: 16, top: 16, bottom: 56 },
            xAxis: { ...axis.x(), data: lat.map((l) => l.period) },
            yAxis: axis.y("Milliseconds"),
            series: [
              { name: "p50", type: "line", data: lat.map((l) => l.p50) },
              { name: "p95", type: "line", data: lat.map((l) => l.p95) },
            ],
          }}
          table={{
            headers: ["Period", "p50 (ms)", "p95 (ms)"],
            rows: lat.map((l) => [l.period, l.p50, l.p95]),
          }}
        />
        <ChartCard
          title="Incident volume by type"
          loading={inc.loading}
          option={{
            legend: { bottom: 0 },
            grid: { left: 48, right: 16, top: 16, bottom: 56 },
            xAxis: { ...axis.x(), data: (inc.data?.series ?? []).map((s) => s.period) },
            yAxis: axis.y("Incidents"),
            series: (inc.data?.groups ?? []).map((g) => ({
              name: title(g),
              type: "bar",
              stack: "i",
              data: (inc.data?.series ?? []).map((s) => s.counts[g] ?? 0),
            })),
          }}
          table={{
            headers: ["Period", ...(inc.data?.groups ?? []).map(title)],
            rows: (inc.data?.series ?? []).map((s) => [
              s.period,
              ...(inc.data?.groups ?? []).map((g) => s.counts[g] ?? 0),
            ]),
          }}
        />
        <ChartCard
          title="Source mix"
          description="Incidents by source"
          loading={pipe.loading}
          option={{
            tooltip: { trigger: "item" },
            legend: { bottom: 0 },
            series: [
              {
                type: "pie",
                radius: ["45%", "70%"],
                data: mix.map((m) => ({ name: m.source, value: m.events })),
              },
            ],
          }}
          table={{
            headers: ["Source", "Incidents", "Records"],
            rows: mix.map((m) => [m.source, m.events, m.records]),
          }}
        />
        <ChartCard
          title="Exposure by region"
          description="Assets exposed, counted across organisations"
          loading={exp.loading}
          option={{
            grid: { left: 110, right: 40, top: 8, bottom: 28 },
            xAxis: axis.y("Assets exposed"),
            yAxis: {
              type: "category",
              inverse: true,
              data: (exp.data?.by_region ?? []).slice(0, 10).map((r) => r.region),
            },
            tooltip: { trigger: "axis" },
            series: [
              { type: "bar", data: (exp.data?.by_region ?? []).slice(0, 10).map((r) => r.assets_exposed) },
            ],
          }}
          table={{
            headers: ["Region", "Assets exposed", "Exposures", "Organisations"],
            rows: (exp.data?.by_region ?? []).map((r) => [
              r.region,
              r.assets_exposed,
              r.exposures,
              r.tenants,
            ]),
          }}
        />
      </div>
      <h2 className="mb-2 mt-6 text-h4 text-ink">Data freshness</h2>
      <DataTable
        rows={pipe.data?.freshness ?? []}
        rowKey={(f) => f.source}
        caption="Feed freshness"
        exportName="platform-freshness"
        columns={[
          { key: "s", header: "Source", cell: (f) => f.source, value: (f) => f.source },
          {
            key: "r",
            header: "Records",
            cell: (f) => num(f.records),
            value: (f) => f.records,
            align: "right",
          },
          {
            key: "l",
            header: "Last ingest",
            cell: (f) => (f.latest_ingested_at ? ago(f.latest_ingested_at) : "none"),
            value: (f) => f.latest_ingested_at,
          },
        ]}
      />
      <p className="mt-3 text-caption text-slate-600">
        Language mix is not exposed by the analytics API yet and is not shown.
      </p>
      <div className="mt-4">
        <Disclaimer />
      </div>
    </>
  );
}
