"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { use, useMemo, useState } from "react";
import { ScoreComponents, type Components } from "@/components/app/exposure-bits";
import {
  Disclaimer,
  ErrorState,
  LevelChip,
  LoadingRows,
  PageHeader,
  StatusChip,
} from "@/components/app/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/field";
import { Breadcrumbs, Skeleton } from "@/components/ui/misc";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import { api, ApiError } from "@/lib/api";
import { centroid, toIncidentPoint, type AlertItem, type AssetItem, type EventItem } from "@/lib/app/data";
import { km, num, title, when } from "@/lib/app/format";
import { atLeast, useSession } from "@/lib/app/session";
import { useApi } from "@/lib/app/use-api";

const AppMap = dynamic(() => import("@/components/app/app-map"), {
  ssr: false,
  loading: () => <Skeleton className="size-full" />,
});

type Exposure = {
  event_id: string;
  title: string;
  type: string;
  subtype: string | null;
  severity: number;
  event_status: string;
  last_seen_at: string;
  distance_km: number;
  score: number;
  level: string;
  components: Components;
  computed_at: string;
};

export default function AssetDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { me } = useSession();
  const toast = useToast();
  const asset = useApi<AssetItem>(`/assets/${id}`);
  const exposure = useApi<{ exposures: Exposure[] }>(`/assets/${id}/exposure`);
  const alerts = useApi<{ items: AlertItem[] }>(`/alerts?asset_id=${id}&limit=100`);
  const events = useApi<{ items: EventItem[] }>("/events?limit=200");
  const [maint, setMaint] = useState<{ start: string; end: string; reason?: string }[] | null>(null);
  const canWrite = atLeast(me.role, "manager");
  const a = asset.data;

  const [lon, lat] = a ? centroid(a.geometry) : [0, 0];
  const exposed = useMemo(() => exposure.data?.exposures ?? [], [exposure.data]);
  const nearby = useMemo(() => {
    const ids = new Set(exposed.map((x) => x.event_id));
    return (events.data?.items ?? []).filter((e) => ids.has(e.id)).map(toIncidentPoint);
  }, [events.data, exposed]);
  const worst = exposed.length ? exposed.reduce((m, x) => (x.score > m.score ? x : m)) : null;

  if (asset.error) return <ErrorState error={asset.error} onRetry={asset.reload} />;
  if (!a) return <LoadingRows rows={6} />;

  async function save(patch: Record<string, unknown>, msg: string) {
    try {
      await api(`/assets/${id}`, { method: "PATCH", body: patch });
      toast(msg);
      asset.reload();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "The change could not be saved.", "error");
    }
  }
  const windows = maint ?? a.maintenance_windows;

  const timeline = [
    ...exposed.map((x) => ({
      at: x.computed_at,
      text: `Exposure to ${x.title} (${km(x.distance_km)}, ${x.level})`,
    })),
    ...(alerts.data?.items ?? []).map((al) => ({
      at: al.created_at,
      text: `Alert ${al.level}, ${al.status}: ${al.event.title}`,
    })),
  ].sort((p, q) => q.at.localeCompare(p.at));

  return (
    <>
      <Breadcrumbs items={[{ label: "Assets", href: "/app/assets" }, { label: a.name }]} />
      <PageHeader
        title={a.name}
        description={`${title(a.type)}, criticality ${a.criticality} of 5. ${lat.toFixed(4)}, ${lon.toFixed(4)}${a.location_uncertainty_km ? ` (location accurate to about ${a.location_uncertainty_km} km)` : ""}.`}
        badge={worst ? <LevelChip level={worst.level} /> : <Badge tone="success">Not exposed</Badge>}
      />
      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="timeline">Timeline</TabsTrigger>
          <TabsTrigger value="map">Map</TabsTrigger>
          <TabsTrigger value="settings">Settings</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="mt-4 space-y-4">
          {exposure.error ? (
            <ErrorState error={exposure.error} onRetry={exposure.reload} />
          ) : exposed.length === 0 ? (
            <Card>
              <p className="text-small text-slate-600">
                No current incident is close enough to affect this asset.
              </p>
            </Card>
          ) : (
            exposed.map((x) => (
              <Card key={x.event_id}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Link
                    href={`/app/incidents/${x.event_id}`}
                    className="font-medium text-ink hover:underline"
                  >
                    {x.title}
                  </Link>
                  <span className="flex items-center gap-3 text-small text-slate-600">
                    {km(x.distance_km)} away, score {num(x.score, 2)} <LevelChip level={x.level} />
                  </span>
                </div>
                <h3 className="mb-2 mt-3 text-caption font-medium uppercase tracking-wide text-slate-600">
                  Score components
                </h3>
                <ScoreComponents components={x.components} />
              </Card>
            ))
          )}
          <div className="flex flex-wrap gap-2">
            {a.tags.map((t) => (
              <Badge key={t}>{t}</Badge>
            ))}
          </div>
        </TabsContent>

        <TabsContent value="timeline" className="mt-4">
          <Card>
            {timeline.length === 0 ? (
              <p className="text-small text-slate-600">No incidents or alerts for this asset yet.</p>
            ) : (
              <ol className="space-y-3 border-l border-line pl-4">
                {timeline.map((t, i) => (
                  <li key={i} className="relative text-small">
                    <span
                      className="absolute -left-[21px] top-1.5 size-2.5 rounded-full bg-brand-500"
                      aria-hidden="true"
                    />
                    <div className="text-caption text-slate-600">{when(t.at)}</div>
                    {t.text}
                  </li>
                ))}
              </ol>
            )}
          </Card>
        </TabsContent>

        <TabsContent value="map" className="mt-4">
          <Card className="overflow-hidden p-0">
            <AppMap
              incidents={nearby}
              assets={[
                {
                  id: a.id,
                  lon,
                  lat,
                  label: a.name,
                  exposed: exposed.length > 0,
                  criticality: a.criticality,
                },
              ]}
              rings={{ lon, lat, radiiKm: [25, 50, 100, 250] }}
              fit={[lon - 3, lat - 2.2, lon + 3, lat + 2.2]}
              label={`Map around ${a.name} with distance rings`}
              className="h-[460px] w-full"
            />
            <p className="px-4 py-2 text-caption text-slate-600">
              Dashed rings mark 25, 50, 100 and 250 km from the asset. Incidents shown are those currently
              affecting it.
            </p>
          </Card>
        </TabsContent>

        <TabsContent value="settings" className="mt-4 grid gap-4 lg:grid-cols-2">
          <Card>
            <h2 className="text-h4 text-ink">Details</h2>
            <form
              className="mt-3 space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                const d = new FormData(e.currentTarget);
                void save(
                  {
                    name: d.get("name"),
                    criticality: Number(d.get("criticality")),
                    tags: String(d.get("tags") ?? "")
                      .split(",")
                      .map((s) => s.trim())
                      .filter(Boolean),
                  },
                  "Asset saved.",
                );
              }}
            >
              <Field label="Name" htmlFor="a-name">
                <Input id="a-name" name="name" defaultValue={a.name} disabled={!canWrite} />
              </Field>
              <Field label="Criticality" htmlFor="a-crit">
                <Select id="a-crit" name="criticality" defaultValue={a.criticality} disabled={!canWrite}>
                  {[1, 2, 3, 4, 5].map((n) => (
                    <option key={n}>{n}</option>
                  ))}
                </Select>
              </Field>
              <Field label="Tags (comma separated)" htmlFor="a-tags">
                <Input id="a-tags" name="tags" defaultValue={a.tags.join(", ")} disabled={!canWrite} />
              </Field>
              {canWrite ? (
                <Button type="submit">Save</Button>
              ) : (
                <p className="text-caption text-slate-600">Managers can edit assets.</p>
              )}
            </form>
          </Card>
          <Card>
            <h2 className="text-h4 text-ink">Maintenance windows</h2>
            <p className="text-caption text-slate-600">
              Alerts are held while a window is open and resume afterwards.
            </p>
            <ul className="mt-3 space-y-2 text-small">
              {windows.length === 0 ? (
                <li className="text-slate-600">No windows.</li>
              ) : (
                windows.map((w, i) => (
                  <li key={i} className="flex items-center justify-between gap-2">
                    {when(w.start)} to {when(w.end)}
                    {w.reason ? ` (${w.reason})` : ""}
                    {canWrite ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() =>
                          void save(
                            { maintenance_windows: windows.filter((_, j) => j !== i) },
                            "Window removed.",
                          )
                        }
                      >
                        Remove
                      </Button>
                    ) : null}
                  </li>
                ))
              )}
            </ul>
            {canWrite ? (
              <form
                className="mt-3 grid gap-2 sm:grid-cols-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  const d = new FormData(e.currentTarget);
                  const w = {
                    start: new Date(String(d.get("s"))).toISOString(),
                    end: new Date(String(d.get("e"))).toISOString(),
                    reason: String(d.get("r") ?? ""),
                  };
                  setMaint([...windows, w]);
                  void save({ maintenance_windows: [...windows, w] }, "Window added.");
                  e.currentTarget.reset();
                }}
              >
                <Field label="Start" htmlFor="m-s">
                  <Input id="m-s" name="s" type="datetime-local" required />
                </Field>
                <Field label="End" htmlFor="m-e">
                  <Input id="m-e" name="e" type="datetime-local" required />
                </Field>
                <Field label="Reason" htmlFor="m-r" className="sm:col-span-2">
                  <Input id="m-r" name="r" maxLength={80} />
                </Field>
                <Button type="submit" variant="secondary" size="sm">
                  Add window
                </Button>
              </form>
            ) : null}
          </Card>
          {canWrite ? (
            <Card className="lg:col-span-2">
              <h2 className="text-h4 text-ink">Danger zone</h2>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  variant="secondary"
                  onClick={() =>
                    void save(
                      { status: a.status === "active" ? "archived" : "active" },
                      a.status === "active" ? "Asset archived." : "Asset restored.",
                    )
                  }
                >
                  {a.status === "active" ? "Archive asset" : "Restore asset"}
                </Button>
                <Button
                  variant="destructive"
                  onClick={async () => {
                    if (!window.confirm(`Delete ${a.name} permanently? This cannot be undone.`)) return;
                    try {
                      await api(`/assets/${id}`, { method: "DELETE" });
                      window.location.href = "/app/assets";
                    } catch {
                      toast("The asset could not be deleted.", "error");
                    }
                  }}
                >
                  Delete asset
                </Button>
              </div>
              <p className="mt-2 text-caption text-slate-600">
                Status: <StatusChip status={a.status} />
              </p>
            </Card>
          ) : null}
        </TabsContent>
      </Tabs>
      <div className="mt-6">
        <Disclaimer />
      </div>
    </>
  );
}
