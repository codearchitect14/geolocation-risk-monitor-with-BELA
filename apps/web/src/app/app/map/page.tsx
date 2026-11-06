"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Bbox, Layers, View } from "@/components/app/app-map";
import { DataTable } from "@/components/app/data-table";
import { Disclaimer, ErrorState, LevelChip, PageHeader, StatusChip } from "@/components/app/states";
import { SeverityBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox, Input, Select } from "@/components/ui/field";
import { Skeleton } from "@/components/ui/misc";
import { qs } from "@/lib/api";
import {
  fetchAll,
  levelFromSeverity,
  toIncidentPoint,
  type AlertItem,
  type AssetItem,
  type EventItem,
  EVENT_TYPES,
} from "@/lib/app/data";
import { ago, km, title, when } from "@/lib/app/format";
import { useApi } from "@/lib/app/use-api";

const AppMap = dynamic(() => import("@/components/app/app-map"), {
  ssr: false,
  loading: () => <Skeleton className="size-full" />,
});
const DAYS: Record<string, number> = { "24h": 1, "7d": 7, "30d": 30 };

function MapPage() {
  const router = useRouter();
  const sp = useSearchParams();
  const get = useCallback((k: string, d = "") => sp.get(k) ?? d, [sp]);
  const [bbox, setBbox] = useState<Bbox | null>(null);
  const [view, setView] = useState<"map" | "list">("map");
  const [sel, setSel] = useState<{ kind: "incident" | "asset"; id: string } | null>(null);
  const [assets, setAssets] = useState<AssetItem[]>([]);
  const [t, setT] = useState(100); // time slider, percent of the window
  const [playing, setPlaying] = useState(false);

  const win = get("window", "7d");
  const from = get("from");
  const to = get("to");
  const layers: Layers = {
    incidents: get("li", "1") === "1",
    assets: get("la", "1") === "1",
    zones: get("lz", "1") === "1",
    density: get("ld") === "1",
  };
  const initial = useRef<View>({
    center: [Number(get("lon", "10")), Number(get("lat", "25"))],
    zoom: Number(get("z", "1.4")),
  });

  const update = useCallback(
    (patch: Record<string, string | undefined>) => {
      const p = new URLSearchParams(sp.toString());
      for (const [k, v] of Object.entries(patch)) {
        if (v) p.set(k, v);
        else p.delete(k);
      }
      router.replace(`/app/map?${p.toString()}`, { scroll: false });
    },
    [router, sp],
  );

  // "Now" is fixed per window choice. Reading the clock on every render would change the request address each time and
  // refetch without end.
  const nowMs = useMemo(() => Date.now(), [win, from, to]); // eslint-disable-line react-hooks/exhaustive-deps
  const sinceMs = win === "custom" && from ? new Date(from).getTime() : nowMs - (DAYS[win] ?? 7) * 86_400_000;
  const untilMs = win === "custom" && to ? new Date(to).getTime() + 86_400_000 : nowMs;
  const path = `/events${qs({
    type: get("type"),
    min_severity: get("sev"),
    status: get("status"),
    since: new Date(sinceMs).toISOString(),
    until: win === "custom" ? new Date(untilMs).toISOString() : undefined,
    bbox: bbox && bbox[2] - bbox[0] < 300 ? bbox.map((n) => n.toFixed(3)).join(",") : undefined,
    limit: 200,
  })}`;
  const events = useApi<{ items: EventItem[] }>(path);
  const zones = useApi<{ items: { id: string; name: string; geometry: GeoJSON.Geometry }[] }>("/zones");
  const alerts = useApi<{ items: AlertItem[] }>("/alerts?limit=200");

  useEffect(() => {
    fetchAll<AssetItem>("/assets?status=active", 5000).then(setAssets, () => undefined);
  }, []);
  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => setT((v) => (v >= 100 ? (setPlaying(false), 100) : v + 2)), 150);
    return () => window.clearInterval(timer);
  }, [playing]);

  const cutoff = sinceMs + ((untilMs - sinceMs) * t) / 100;
  const visible = useMemo(
    () =>
      (events.data?.items ?? []).filter(
        (e) =>
          new Date(e.first_seen_at).getTime() <= cutoff &&
          (get("hazard") === "" || (get("hazard") === "feeds") === (e.type === "natural_hazard")),
      ),
    [events.data, cutoff, get],
  );
  const exposedIds = useMemo(
    () =>
      new Set(
        (alerts.data?.items ?? [])
          .filter((a) => !["dismissed", "resolved"].includes(a.status))
          .flatMap((a) => (a.asset ? [a.asset.id] : [])),
      ),
    [alerts.data],
  );
  const points = useMemo(() => visible.map(toIncidentPoint), [visible]);
  const assetPts = useMemo(
    () =>
      assets
        .filter((a) => a.geometry.type === "Point")
        .map((a) => ({
          id: a.id,
          lon: (a.geometry as GeoJSON.Point).coordinates[0] as number,
          lat: (a.geometry as GeoJSON.Point).coordinates[1] as number,
          label: a.name,
          exposed: exposedIds.has(a.id),
          criticality: a.criticality,
        })),
    [assets, exposedIds],
  );
  const zoneFc = useMemo<GeoJSON.FeatureCollection>(
    () => ({
      type: "FeatureCollection",
      features: (zones.data?.items ?? []).map((z) => ({
        type: "Feature",
        properties: { name: z.name },
        geometry: z.geometry,
      })),
    }),
    [zones.data],
  );
  const selEvent = sel?.kind === "incident" ? visible.find((e) => e.id === sel.id) : undefined;
  const selAsset = sel?.kind === "asset" ? assets.find((a) => a.id === sel.id) : undefined;
  const selAlerts = selAsset ? (alerts.data?.items ?? []).filter((a) => a.asset?.id === selAsset.id) : [];
  const ringsAt =
    selAsset?.geometry.type === "Point"
      ? {
          lon: selAsset.geometry.coordinates[0] as number,
          lat: selAsset.geometry.coordinates[1] as number,
          radiiKm: [25, 50, 100, 250],
        }
      : null;

  const onMove = useCallback(
    (v: View, b: Bbox) => {
      setBbox(b);
      update({ lon: v.center[0].toFixed(3), lat: v.center[1].toFixed(3), z: v.zoom.toFixed(2) });
    },
    [update],
  );

  return (
    <>
      <PageHeader
        title="Map"
        description="Incidents, hazard feeds, assets and watch zones. Markers differ by shape and size as well as color. The view and filters are kept in the address, so you can share it."
        actions={
          <Button
            size="sm"
            variant="secondary"
            aria-pressed={view === "list"}
            onClick={() => setView(view === "map" ? "list" : "map")}
          >
            {view === "map" ? "Show as list" : "Show map"}
          </Button>
        }
      />
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor="m-type" className="mb-1 block text-caption text-slate-600">
            Type
          </label>
          <Select
            id="m-type"
            className="h-9"
            value={get("type")}
            onChange={(e) => update({ type: e.target.value })}
          >
            <option value="">All types</option>
            {EVENT_TYPES.map((t) => (
              <option key={t} value={t}>
                {title(t)}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <label htmlFor="m-sev" className="mb-1 block text-caption text-slate-600">
            Severity
          </label>
          <Select
            id="m-sev"
            className="h-9"
            value={get("sev")}
            onChange={(e) => update({ sev: e.target.value })}
          >
            <option value="">Any</option>
            <option value="2">2 and above</option>
            <option value="3">3 and above</option>
            <option value="4">4 only</option>
          </Select>
        </div>
        <div>
          <label htmlFor="m-status" className="mb-1 block text-caption text-slate-600">
            Status
          </label>
          <Select
            id="m-status"
            className="h-9"
            value={get("status")}
            onChange={(e) => update({ status: e.target.value })}
          >
            <option value="">Any</option>
            <option>new</option>
            <option>developing</option>
            <option>ongoing</option>
          </Select>
        </div>
        <div>
          <label htmlFor="m-src" className="mb-1 block text-caption text-slate-600">
            Source
          </label>
          <Select
            id="m-src"
            className="h-9"
            value={get("hazard")}
            onChange={(e) => update({ hazard: e.target.value })}
          >
            <option value="">News and feeds</option>
            <option value="feeds">Hazard feeds only</option>
            <option value="news">Other reports only</option>
          </Select>
        </div>
        <div>
          <label htmlFor="m-win" className="mb-1 block text-caption text-slate-600">
            Time window
          </label>
          <Select
            id="m-win"
            className="h-9"
            value={win}
            onChange={(e) => {
              setT(100);
              update({ window: e.target.value });
            }}
          >
            <option value="24h">Last 24 hours</option>
            <option value="7d">Last 7 days</option>
            <option value="30d">Last 30 days</option>
            <option value="custom">Custom</option>
          </Select>
        </div>
        {win === "custom" ? (
          <>
            <div>
              <label htmlFor="m-from" className="mb-1 block text-caption text-slate-600">
                From
              </label>
              <Input
                id="m-from"
                type="date"
                className="h-9"
                value={from}
                onChange={(e) => update({ from: e.target.value })}
              />
            </div>
            <div>
              <label htmlFor="m-to" className="mb-1 block text-caption text-slate-600">
                To
              </label>
              <Input
                id="m-to"
                type="date"
                className="h-9"
                value={to}
                onChange={(e) => update({ to: e.target.value })}
              />
            </div>
          </>
        ) : null}
        <fieldset className="flex items-center gap-3 pb-2 text-small">
          <legend className="sr-only">Layers</legend>
          {(
            [
              ["li", "Incidents", layers.incidents],
              ["la", "Assets", layers.assets],
              ["lz", "Zones", layers.zones],
              ["ld", "Density", layers.density],
            ] as const
          ).map(([k, l, on]) => (
            <label key={k} className="flex items-center gap-1.5">
              <Checkbox
                checked={on}
                onChange={(e) =>
                  update({
                    [k]: k === "ld" ? (e.target.checked ? "1" : undefined) : e.target.checked ? "1" : "0",
                  })
                }
              />
              {l}
            </label>
          ))}
        </fieldset>
      </div>

      <div className="mb-3 flex items-center gap-3 rounded-control border border-line bg-white p-2">
        <Button
          size="sm"
          variant="secondary"
          onClick={() => {
            if (t >= 100) setT(0);
            setPlaying((p) => !p);
          }}
        >
          {playing ? "Pause" : "Replay"}
        </Button>
        <label htmlFor="m-slider" className="sr-only">
          Time slider
        </label>
        <input
          id="m-slider"
          type="range"
          min={0}
          max={100}
          value={t}
          onChange={(e) => {
            setPlaying(false);
            setT(Number(e.target.value));
          }}
          className="w-full"
          aria-valuetext={`Showing incidents first seen up to ${when(new Date(cutoff).toISOString())}`}
        />
        <span className="w-44 shrink-0 text-caption text-slate-600">
          Up to {when(new Date(cutoff).toISOString())}
        </span>
      </div>

      {events.error ? <ErrorState error={events.error} onRetry={events.reload} /> : null}
      {view === "map" ? (
        <div className="relative grid gap-4 lg:grid-cols-[1fr_20rem]">
          <div className="h-[calc(100dvh-22rem)] min-h-[420px] overflow-hidden rounded-card border border-line">
            <AppMap
              incidents={points}
              assets={assetPts}
              zones={zoneFc}
              rings={ringsAt}
              layers={layers}
              view={initial.current}
              selected={sel}
              onSelect={(kind, id) => setSel({ kind, id })}
              onMove={onMove}
              label="Map of incidents, assets and watch zones"
              className="size-full"
            />
          </div>
          <aside aria-label="Details" className="rounded-card border border-line bg-white p-4">
            {selEvent ? (
              <div className="space-y-2 text-small">
                <SeverityBadge level={levelFromSeverity(selEvent.severity)} />
                <h2 className="text-h4 text-ink">{selEvent.title}</h2>
                <p className="text-slate-600">
                  {title(selEvent.subtype ?? selEvent.type)}. {selEvent.confirmation_text}. Last update{" "}
                  {ago(selEvent.last_seen_at)}.
                </p>
                <Button asChild size="sm">
                  <Link href={`/app/incidents/${selEvent.id}`}>Open incident</Link>
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setSel(null)}>
                  Clear
                </Button>
              </div>
            ) : selAsset ? (
              <div className="space-y-2 text-small">
                <h2 className="text-h4 text-ink">{selAsset.name}</h2>
                <p className="text-slate-600">
                  {title(selAsset.type)}, criticality {selAsset.criticality}. Rings mark 25, 50, 100 and 250
                  km.
                </p>
                {selAlerts.map((a) => (
                  <p key={a.id}>
                    <LevelChip level={a.level} /> {a.event.title} ({km(a.asset?.distance_km)})
                  </p>
                ))}
                <Button asChild size="sm">
                  <Link href={`/app/assets/${selAsset.id}`}>Open asset</Link>
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setSel(null)}>
                  Clear
                </Button>
              </div>
            ) : (
              <div className="text-small text-slate-600">
                <h2 className="text-h4 text-ink">{visible.length} incidents</h2>
                <p className="mt-1">
                  {assetPts.length} assets, {exposedIds.size} exposed (red outline). Select a marker for
                  details.
                </p>
                <p className="mt-3 text-caption">
                  Severity: ● level 1, ■ level 2, ▲ level 3, ◆ level 4. Dashed teal circles show location
                  uncertainty.
                </p>
              </div>
            )}
          </aside>
        </div>
      ) : (
        <DataTable
          rows={visible}
          rowKey={(e) => e.id}
          caption="Incidents on the map as a table"
          exportName="map-incidents"
          columns={[
            {
              key: "s",
              header: "Severity",
              cell: (e) => <SeverityBadge level={levelFromSeverity(e.severity)} />,
              value: (e) => e.severity,
            },
            { key: "t", header: "Incident", cell: (e) => e.title, value: (e) => e.title },
            { key: "ty", header: "Type", cell: (e) => title(e.subtype ?? e.type), value: (e) => e.type },
            {
              key: "st",
              header: "Status",
              cell: (e) => <StatusChip status={e.status} />,
              value: (e) => e.status,
            },
            {
              key: "u",
              header: "Uncertainty",
              cell: (e) => km(e.uncertainty_km),
              value: (e) => e.uncertainty_km,
              align: "right",
            },
            {
              key: "w",
              header: "First seen",
              cell: (e) => when(e.first_seen_at),
              value: (e) => e.first_seen_at,
            },
          ]}
          onRowClick={(e) => router.push(`/app/incidents/${e.id}`)}
          empty={{
            title: "No incidents in this view",
            body: "Zoom out, widen the time window, or clear a filter.",
          }}
        />
      )}
      <div className="mt-3">
        <Disclaimer />
      </div>
    </>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<Skeleton className="h-[480px] w-full" />}>
      <MapPage />
    </Suspense>
  );
}
