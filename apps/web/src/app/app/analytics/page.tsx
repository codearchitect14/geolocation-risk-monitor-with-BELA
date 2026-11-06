"use client";

import { useMemo } from "react";
import { ChartCard, axis } from "@/components/app/chart-card";
import { DashControls, useRange } from "@/components/app/dash-controls";
import { DemoBadge, Disclaimer, ErrorState, Kpi, PageHeader, StatusChip } from "@/components/app/states";
import { DataTable } from "@/components/app/data-table";
import { qs } from "@/lib/api";
import type { AlertItem, EventItem } from "@/lib/app/data";
import { ago, minutes, num, pct, title } from "@/lib/app/format";
import { useApi } from "@/lib/app/use-api";

type Ops = {
  series: {
    period: string;
    critical: number;
    high: number;
    medium: number;
    low: number;
    alerts: number;
    acknowledged: number;
    dismissed: number;
    avg_minutes_to_acknowledge: number | null;
  }[];
  totals: {
    alerts: number;
    critical: number;
    high: number;
    medium: number;
    low: number;
    acknowledged: number;
    dismissed: number;
    avg_minutes_to_acknowledge: number | null;
    acknowledgement_rate: number | null;
    location_confirmation_rate: number | null;
  };
  median_minutes_to_acknowledge: number | null;
  previous?: { totals: Ops["totals"] } | null;
  most_alerted_assets: { asset_id: string; name: string; alerts: number }[];
  alerts_by_status: Record<string, number>;
};
type Quality = {
  series: {
    period: string;
    location_confirmed: number;
    location_corrected: number;
    location_confirmation_rate: number | null;
  }[];
  location_confirmation_rate: number | null;
  events: number;
  confirmed_share: number;
};
type Source = {
  kind: string;
  name: string;
  freshness: string;
  last_record_at: string | null;
  records_total: number;
};

const PERIOD = { day: "day", week: "week", month: "month" } as const;

export default function Analytics() {
  const [range, setRange] = useRange("30d", "day");
  const q = qs({
    from: range.from,
    to: range.to,
    granularity: range.granularity,
    compare: range.compare ? "previous" : undefined,
  });
  const ops = useApi<Ops>(`/analytics/operations${q}`);
  const quality = useApi<Quality>(`/analytics/quality${q}`);
  const events = useApi<{ items: EventItem[] }>(
    `/events${qs({ since: new Date(range.from).toISOString(), limit: 200 })}`,
  );
  const alerts = useApi<{ items: AlertItem[] }>("/alerts?limit=200");
  const sources = useApi<{ items: Source[] }>("/sources");

  const volume = useMemo(() => {
    const bucket = (iso: string) => {
      const d = new Date(iso);
      if (range.granularity === "month") return iso.slice(0, 7);
      if (range.granularity === "week") {
        const day = (d.getUTCDay() + 6) % 7;
        return new Date(d.getTime() - day * 86_400_000).toISOString().slice(0, 10);
      }
      return iso.slice(0, 10);
    };
    const types = new Set<string>();
    const map = new Map<string, Map<string, number>>();
    (events.data?.items ?? []).forEach((e) => {
      const b = bucket(e.first_seen_at);
      types.add(e.type);
      const m = map.get(b) ?? new Map();
      m.set(e.type, (m.get(e.type) ?? 0) + 1);
      map.set(b, m);
    });
    const periods = [...map.keys()].sort();
    return { periods, types: [...types], map };
  }, [events.data, range.granularity]);

  const t = ops.data?.totals;
  const prev = ops.data?.previous?.totals;
  const delta = (cur?: number | null, old?: number | null) =>
    cur != null && old != null
      ? `${cur >= old ? "+" : ""}${num(cur - old, 1)} vs previous period`
      : undefined;
  const sourceMix = useMemo(() => {
    const m = new Map<string, number>();
    (events.data?.items ?? []).forEach((e) =>
      m.set(e.source_count > 0 ? e.type : "other", (m.get(e.type) ?? 0) + 1),
    );
    return [...m].sort((a, b) => b[1] - a[1]).slice(0, 5);
  }, [events.data]);

  const top = useMemo(() => {
    const m = new Map<string, { name: string; score: number; level: string }>();
    (alerts.data?.items ?? []).forEach((a) => {
      if (!a.asset) return;
      const c = m.get(a.asset.id);
      if (!c || a.score > c.score) m.set(a.asset.id, { name: a.asset.name, score: a.score, level: a.level });
    });
    return [...m.entries()]
      .map(([id, v]) => ({ id, ...v }))
      .sort((a, b) => b.score - a.score)
      .slice(0, 10);
  }, [alerts.data]);
  const err = ops.error ?? quality.error;
  if (err) return <ErrorState error={err} onRetry={() => (ops.reload(), quality.reload())} />;
  const ser = ops.data?.series ?? [];

  return (
    <>
      <PageHeader
        title="Analytics"
        description="Operational view of incidents, alerts and how your team responds."
        badge={
          alerts.data?.items.some((a) => a.asset?.name.includes("(illustrative)")) ? (
            <DemoBadge label="Illustrative assets" />
          ) : null
        }
      />
      <DashControls range={range} onChange={setRange} />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
        <Kpi
          label="Incidents in period"
          value={num(events.data?.items.length)}
          hint={events.data?.items.length === 200 ? "First 200 shown" : undefined}
        />
        <Kpi label="Alerts" value={num(t?.alerts)} hint={delta(t?.alerts, prev?.alerts)} />
        <Kpi
          label="Critical and high"
          value={num((t?.critical ?? 0) + (t?.high ?? 0))}
          hint={t ? `${t.critical} critical, ${t.high} high` : undefined}
        />
        <Kpi
          label="Median time to acknowledge"
          value={minutes(ops.data?.median_minutes_to_acknowledge)}
          hint={delta(ops.data?.median_minutes_to_acknowledge, undefined)}
        />
        <Kpi
          label="Location confirmation"
          value={pct(
            quality.data?.location_confirmation_rate != null
              ? quality.data.location_confirmation_rate * 100
              : null,
          )}
          hint="Reviewer confirmed of reviewed"
        />
        <Kpi
          label="Dismissed share"
          value={pct(t && t.alerts ? (t.dismissed / t.alerts) * 100 : null)}
          hint="Proxy for false alerts"
        />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <ChartCard
          title="Incident volume"
          description="Incidents first seen, by type"
          loading={events.loading}
          error={events.error}
          option={{
            legend: { bottom: 0 },
            grid: { left: 48, right: 16, top: 16, bottom: 56 },
            xAxis: { ...axis.x(PERIOD[range.granularity]), data: volume.periods },
            yAxis: axis.y("Incidents"),
            series: volume.types.map((ty) => ({
              name: title(ty),
              type: "bar",
              stack: "v",
              data: volume.periods.map((p) => volume.map.get(p)?.get(ty) ?? 0),
            })),
          }}
          table={{
            headers: ["Period", ...volume.types.map(title)],
            rows: volume.periods.map((p) => [
              p,
              ...volume.types.map((ty) => volume.map.get(p)?.get(ty) ?? 0),
            ]),
          }}
        />
        <ChartCard
          title="Alerts by level"
          loading={ops.loading}
          option={{
            legend: { bottom: 0 },
            grid: { left: 48, right: 16, top: 16, bottom: 56 },
            xAxis: {
              ...axis.x(PERIOD[range.granularity]),
              data: ser.map((s) => s.period),
              boundaryGap: false,
            },
            yAxis: axis.y("Alerts"),
            series: (["critical", "high", "medium", "low"] as const).map((l, i) => ({
              name: title(l),
              type: "line",
              stack: "a",
              areaStyle: {},
              symbol: "none",
              color: ["#8E1B1B", "#D55E5E", "#E69F00", "#7AA6D8"][i],
              data: ser.map((s) => s[l]),
            })),
          }}
          table={{
            headers: ["Period", "Critical", "High", "Medium", "Low"],
            rows: ser.map((s) => [s.period, s.critical, s.high, s.medium, s.low]),
          }}
        />
        <ChartCard
          title="Alert response"
          description="Acknowledged and dismissed alerts, with average minutes to acknowledge"
          loading={ops.loading}
          option={{
            legend: { bottom: 0 },
            grid: { left: 48, right: 56, top: 16, bottom: 56 },
            xAxis: { ...axis.x(PERIOD[range.granularity]), data: ser.map((s) => s.period) },
            yAxis: [axis.y("Alerts"), { ...axis.y("Minutes"), splitLine: { show: false } }],
            series: [
              { name: "Acknowledged", type: "bar", data: ser.map((s) => s.acknowledged) },
              { name: "Dismissed", type: "bar", data: ser.map((s) => s.dismissed) },
              {
                name: "Avg minutes to acknowledge",
                type: "line",
                yAxisIndex: 1,
                data: ser.map((s) => s.avg_minutes_to_acknowledge),
              },
            ],
          }}
          table={{
            headers: ["Period", "Acknowledged", "Dismissed", "Avg minutes"],
            rows: ser.map((s) => [
              s.period,
              s.acknowledged,
              s.dismissed,
              s.avg_minutes_to_acknowledge != null ? Math.round(s.avg_minutes_to_acknowledge) : null,
            ]),
          }}
        />
        <ChartCard
          title="Location accuracy trend"
          description="Reviewer confirmed versus corrected locations"
          loading={quality.loading}
          empty="No locations have been reviewed in this period."
          option={{
            legend: { bottom: 0 },
            grid: { left: 48, right: 16, top: 16, bottom: 56 },
            xAxis: {
              ...axis.x(PERIOD[range.granularity]),
              data: (quality.data?.series ?? []).map((s) => s.period),
            },
            yAxis: axis.y("Locations reviewed"),
            series: [
              {
                name: "Confirmed",
                type: "line",
                data: (quality.data?.series ?? []).map((s) => s.location_confirmed),
              },
              {
                name: "Corrected",
                type: "line",
                data: (quality.data?.series ?? []).map((s) => s.location_corrected),
              },
            ],
          }}
          table={{
            headers: ["Period", "Confirmed", "Corrected"],
            rows: (quality.data?.series ?? [])
              .filter((s) => s.location_confirmed + s.location_corrected > 0)
              .map((s) => [s.period, s.location_confirmed, s.location_corrected]),
          }}
        />
        <ChartCard
          title="Incident types"
          description="Share of incidents in the period"
          loading={events.loading}
          option={{
            tooltip: { trigger: "item" },
            legend: { bottom: 0 },
            series: [
              {
                type: "pie",
                radius: ["45%", "70%"],
                label: { formatter: "{b}: {c}" },
                data: sourceMix.map(([n, v]) => ({ name: title(n), value: v })),
              },
            ],
          }}
          table={{ headers: ["Type", "Incidents"], rows: sourceMix.map(([n, v]) => [title(n), v]) }}
        />
        <div>
          <h2 className="mb-2 text-h4 text-ink">Top exposed assets</h2>
          <DataTable
            rows={top}
            rowKey={(r) => r.id}
            caption="Top exposed assets"
            exportName="top-exposed-assets"
            empty={{ title: "No exposed assets", body: "Assets appear here when an incident reaches them." }}
            columns={[
              { key: "n", header: "Asset", cell: (r) => r.name, value: (r) => r.name },
              {
                key: "s",
                header: "Score",
                cell: (r) => r.score.toFixed(2),
                value: (r) => r.score,
                align: "right",
              },
              { key: "l", header: "Level", cell: (r) => r.level, value: (r) => r.level },
            ]}
          />
        </div>
      </div>
      <h2 className="mb-2 mt-6 text-h4 text-ink">Data freshness</h2>
      <DataTable
        rows={sources.data?.items ?? []}
        rowKey={(s) => s.kind}
        caption="Feed freshness"
        exportName="data-freshness"
        columns={[
          { key: "n", header: "Feed", cell: (s) => s.name, value: (s) => s.name },
          {
            key: "f",
            header: "Status",
            cell: (s) => <StatusChip status={s.freshness} />,
            value: (s) => s.freshness,
          },
          {
            key: "l",
            header: "Last record",
            cell: (s) => (s.last_record_at ? ago(s.last_record_at) : "none"),
            value: (s) => s.last_record_at,
          },
        ]}
      />
      <div className="mt-4">
        <Disclaimer />
      </div>
    </>
  );
}
