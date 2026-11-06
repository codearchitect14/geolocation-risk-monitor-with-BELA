"use client";

import Link from "next/link";
import { useMemo } from "react";
import dynamic from "next/dynamic";
import { DemoBadge, Disclaimer, ErrorState, Kpi, LevelChip, PageHeader } from "@/components/app/states";
import { ChartCard, axis } from "@/components/app/chart-card";
import { Card } from "@/components/ui/card";
import { EmptyState, Skeleton } from "@/components/ui/misc";
import { ago, minutes, num } from "@/lib/app/format";
import { fetchAll, toIncidentPoint, type AlertItem, type AssetItem, type EventItem } from "@/lib/app/data";
import { useApi } from "@/lib/app/use-api";
import { useEffect, useState } from "react";

const AppMap = dynamic(() => import("@/components/app/app-map"), {
  ssr: false,
  loading: () => <Skeleton className="size-full" />,
});

type Briefing = {
  id: string;
  kind: string;
  period_start: string;
  period_end: string;
  created_at: string;
  summary?: { alerts?: number };
};

export default function Overview() {
  const events = useApi<{ items: EventItem[] }>("/events?limit=200");
  const alerts = useApi<{ items: AlertItem[] }>("/alerts?limit=200");
  const ops = useApi<{
    totals: { median_minutes_to_acknowledge?: number | null };
    median_minutes_to_acknowledge: number | null;
  }>("/analytics/operations?days=30");
  const briefings = useApi<{ items: Briefing[] }>("/briefings?limit=3");
  const [assets, setAssets] = useState<AssetItem[]>();
  const [assetError, setAssetError] = useState<Error>();
  useEffect(() => {
    fetchAll<AssetItem>("/assets", 2000).then(setAssets, setAssetError);
  }, []);

  const stats = useMemo(() => {
    const ev = events.data?.items ?? [];
    const al = alerts.data?.items ?? [];
    const open = al.filter((a) => !["dismissed", "resolved"].includes(a.status));
    const exposedIds = new Set(open.flatMap((a) => (a.asset ? [a.asset.id] : [])));
    const dayAgo = Date.now() - 86_400_000;
    const types = new Map<string, number>();
    ev.forEach((e) => types.set(e.type, (types.get(e.type) ?? 0) + 1));
    const top = new Map<string, { name: string; id: string; score: number; level: string; event: string }>();
    open.forEach((a) => {
      if (!a.asset) return;
      const cur = top.get(a.asset.id);
      if (!cur || a.score > cur.score)
        top.set(a.asset.id, {
          id: a.asset.id,
          name: a.asset.name,
          score: a.score,
          level: a.level,
          event: a.event.title,
        });
    });
    return {
      exposedIds,
      active: ev.filter((e) => e.status !== "closed").length,
      fresh: ev.filter((e) => new Date(e.first_seen_at).getTime() > dayAgo).length,
      critical: open.filter((a) => a.level === "critical").length,
      types: [...types].sort((a, b) => b[1] - a[1]),
      top: [...top.values()].sort((a, b) => b.score - a.score).slice(0, 6),
      open,
    };
  }, [events.data, alerts.data]);

  const points = useMemo(() => (events.data?.items ?? []).map(toIncidentPoint), [events.data]);
  const assetPts = useMemo(
    () =>
      (assets ?? [])
        .filter((a) => a.geometry.type === "Point")
        .map((a) => ({
          id: a.id,
          lon: (a.geometry as GeoJSON.Point).coordinates[0] as number,
          lat: (a.geometry as GeoJSON.Point).coordinates[1] as number,
          label: a.name,
          exposed: stats.exposedIds.has(a.id),
          criticality: a.criticality,
        })),
    [assets, stats.exposedIds],
  );
  const err = events.error ?? alerts.error ?? assetError;
  if (err) return <ErrorState error={err} onRetry={() => (events.reload(), alerts.reload())} />;

  const loading = events.loading || alerts.loading || !assets;
  const median =
    ops.data?.median_minutes_to_acknowledge ?? ops.data?.totals?.median_minutes_to_acknowledge ?? null;
  const typeRows = stats.types.map(([t, n]) => [t.replace(/_/g, " "), n] as [string, number]);

  return (
    <>
      <PageHeader
        title="Overview"
        description="What is happening near your assets right now."
        badge={assets?.some((a) => a.name.includes("(illustrative)")) ? <DemoBadge /> : null}
      />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6" aria-busy={loading}>
        <Kpi
          label="Assets monitored"
          value={loading ? "…" : num(assets?.filter((a) => a.status === "active").length)}
        />
        <Kpi label="Assets exposed" value={loading ? "…" : num(stats.exposedIds.size)} />
        <Kpi label="Active incidents" value={loading ? "…" : num(stats.active)} />
        <Kpi label="New in 24 hours" value={loading ? "…" : num(stats.fresh)} />
        <Kpi
          label="Critical alerts"
          value={loading ? "…" : num(stats.critical)}
          tone={stats.critical ? "danger" : undefined}
        />
        <Kpi label="Median time to acknowledge" value={minutes(median)} hint="Last 30 days" />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card className="self-start overflow-hidden p-0 xl:col-span-2">
          <div className="flex items-center justify-between px-4 py-3">
            <h2 className="text-h4 text-ink">Live map</h2>
            <Link href="/app/map" className="text-small font-medium text-brand-600 underline">
              Open full map
            </Link>
          </div>
          <AppMap
            incidents={points}
            assets={assetPts}
            label="Map of incidents and exposed assets"
            className="h-[380px] w-full"
          />
        </Card>
        <Card>
          <h2 className="text-h4 text-ink">Alert feed</h2>
          {alerts.loading ? (
            <Skeleton className="mt-3 h-40" />
          ) : stats.open.length === 0 ? (
            <EmptyState title="No open alerts">
              Alerts appear here when an incident reaches one of your assets.
            </EmptyState>
          ) : (
            <ul className="mt-3 divide-y divide-line">
              {stats.open.slice(0, 7).map((a) => (
                <li key={a.id} className="py-2 text-small">
                  <div className="flex items-center justify-between gap-2">
                    <LevelChip level={a.level} />
                    <span className="text-caption text-slate-600">{ago(a.created_at)}</span>
                  </div>
                  <Link href={`/app/incidents/${a.event.id}`} className="mt-1 block text-ink hover:underline">
                    {a.event.title}
                  </Link>
                  {a.asset ? (
                    <Link
                      href={`/app/assets/${a.asset.id}`}
                      className="text-caption text-slate-600 hover:underline"
                    >
                      {a.asset.name}, {num(a.asset.distance_km, 1)} km
                    </Link>
                  ) : (
                    <span className="text-caption text-slate-600">Watch zone</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <ChartCard
          title="Incidents by type"
          option={{
            grid: { left: 110, right: 48, top: 8, bottom: 28 },
            xAxis: { ...axis.y("Incidents"), nameLocation: "middle", nameGap: 26 },
            yAxis: { type: "category", data: typeRows.map((r) => r[0]), inverse: true },
            series: [
              { type: "bar", data: typeRows.map((r) => r[1]), label: { show: true, position: "right" } },
            ],
            tooltip: { trigger: "axis" },
          }}
          table={{ headers: ["Type", "Incidents"], rows: typeRows }}
          loading={events.loading}
          height={220}
        />
        <Card>
          <h2 className="text-h4 text-ink">Top exposed assets</h2>
          {stats.top.length === 0 ? (
            <p className="mt-3 text-small text-slate-600">No asset is currently exposed.</p>
          ) : (
            <ol className="mt-3 space-y-2">
              {stats.top.map((t) => (
                <li key={t.id} className="flex items-center justify-between gap-2 text-small">
                  <Link href={`/app/assets/${t.id}`} className="truncate text-ink hover:underline">
                    {t.name}
                  </Link>
                  <span className="flex items-center gap-2">
                    <span className="tabular-nums text-slate-600">{num(t.score, 2)}</span>
                    <LevelChip level={t.level} />
                  </span>
                </li>
              ))}
            </ol>
          )}
        </Card>
        <Card>
          <h2 className="text-h4 text-ink">Recent briefings</h2>
          {briefings.loading ? (
            <Skeleton className="mt-3 h-24" />
          ) : (briefings.data?.items.length ?? 0) === 0 ? (
            <p className="mt-3 text-small text-slate-600">
              No briefings yet.{" "}
              <Link href="/app/briefings" className="font-medium text-brand-600 underline">
                Create one
              </Link>
              .
            </p>
          ) : (
            <ul className="mt-3 space-y-2 text-small">
              {briefings.data?.items.map((b) => (
                <li key={b.id}>
                  <Link href="/app/briefings" className="text-ink hover:underline">
                    {b.kind[0]?.toUpperCase()}
                    {b.kind.slice(1)} briefing
                  </Link>
                  <div className="text-caption text-slate-600">{ago(b.created_at)}</div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      <div className="mt-6">
        <Disclaimer />
      </div>
    </>
  );
}
