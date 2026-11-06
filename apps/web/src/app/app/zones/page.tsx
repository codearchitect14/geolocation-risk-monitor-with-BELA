"use client";

import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import type { Drawn } from "@/components/app/app-map";
import { DataTable } from "@/components/app/data-table";
import { Disclaimer, ErrorState, LoadingRows, PageHeader } from "@/components/app/states";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Checkbox, Field, Input, Select } from "@/components/ui/field";
import { Skeleton } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, qs } from "@/lib/api";
import type { EventItem } from "@/lib/app/data";
import { title, LEVELS } from "@/lib/app/format";
import { atLeast, useSession } from "@/lib/app/session";
import { useApi } from "@/lib/app/use-api";

const AppMap = dynamic(() => import("@/components/app/app-map"), {
  ssr: false,
  loading: () => <Skeleton className="size-full" />,
});

type Zone = {
  id: string;
  name: string;
  geometry: GeoJSON.Polygon;
  rules?: { event_types: string[]; min_level: string; min_severity: number };
};
type Place = {
  id: number;
  name: string;
  type: string;
  country_code: string | null;
  admin1_name?: string | null;
};

function bboxOf(g: GeoJSON.Polygon): string {
  const pts = g.coordinates[0] as number[][];
  const xs = pts.map((p) => p[0] as number);
  const ys = pts.map((p) => p[1] as number);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]
    .map((n) => n.toFixed(3))
    .join(",");
}

export default function Zones() {
  const { me } = useSession();
  const toast = useToast();
  const canManage = atLeast(me.role, "manager");
  const res = useApi<{ items: Zone[] }>("/zones");
  const [draw, setDraw] = useState<"polygon" | "circle" | null>(null);
  const [shape, setShape] = useState<Drawn | null>(null);
  const [region, setRegion] = useState<Place | null>(null);
  const [q, setQ] = useState("");
  const [places, setPlaces] = useState<Place[]>([]);
  const [testing, setTesting] = useState<{ zone: Zone; count: number | null } | null>(null);
  const fc = useMemo<GeoJSON.FeatureCollection>(
    () => ({
      type: "FeatureCollection",
      features: (res.data?.items ?? []).map((z) => ({
        type: "Feature",
        properties: { name: z.name },
        geometry: z.geometry,
      })),
    }),
    [res.data],
  );

  async function searchPlaces(term: string) {
    setQ(term);
    if (term.trim().length < 2) return setPlaces([]);
    try {
      setPlaces((await api<{ items: Place[] }>(`/places/search${qs({ q: term, limit: 6 })}`)).items);
    } catch {
      setPlaces([]);
    }
  }
  async function create(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    const rules = {
      event_types: d.getAll("types"),
      min_level: d.get("min_level"),
      min_severity: Number(d.get("min_severity") || 1),
      quiet_hours: null,
    };
    const body: Record<string, unknown> = { name: d.get("name"), rules };
    if (region) body.region_place_id = region.id;
    else if (shape && "circle" in shape) body.circle = shape.circle;
    else if (shape) body.geometry = shape.geometry;
    try {
      await api("/zones", { method: "POST", body });
      toast("Watch zone created.");
      setShape(null);
      setRegion(null);
      res.reload();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "The zone could not be saved.", "error");
    }
  }
  async function test(z: Zone) {
    setTesting({ zone: z, count: null });
    try {
      const since = new Date(Date.now() - 30 * 86_400_000).toISOString();
      const ev = await api<{ items: EventItem[] }>(
        `/events${qs({ bbox: bboxOf(z.geometry), since, min_severity: z.rules?.min_severity, limit: 200 })}`,
      );
      const types = z.rules?.event_types ?? [];
      setTesting({ zone: z, count: ev.items.filter((e) => !types.length || types.includes(e.type)).length });
    } catch {
      setTesting(null);
      toast("The test could not run.", "error");
    }
  }

  if (res.error) return <ErrorState error={res.error} onRetry={res.reload} />;
  return (
    <>
      <PageHeader
        title="Watch zones"
        description="Areas you care about even where you have no asset. A rule decides which incidents inside a zone raise an alert."
      />
      <div className="grid gap-4 xl:grid-cols-[1fr_24rem]">
        <div className="h-[460px] overflow-hidden rounded-card border border-line">
          <AppMap
            zones={fc}
            layers={{ incidents: false, assets: false, zones: true, density: false }}
            draw={canManage ? draw : null}
            onDraw={(s) => {
              setShape(s);
              setDraw(null);
            }}
            label="Watch zones. Use the draw buttons to add one."
            className="size-full"
          />
        </div>
        {canManage ? (
          <form onSubmit={create} className="space-y-3 rounded-card border border-line bg-white p-4">
            <h2 className="text-h4 text-ink">New zone</h2>
            <div className="flex flex-wrap gap-2" role="group" aria-label="Draw tools">
              <Button
                type="button"
                size="sm"
                variant={draw === "polygon" ? "primary" : "secondary"}
                aria-pressed={draw === "polygon"}
                onClick={() => {
                  setRegion(null);
                  setDraw(draw === "polygon" ? null : "polygon");
                }}
              >
                Draw polygon
              </Button>
              <Button
                type="button"
                size="sm"
                variant={draw === "circle" ? "primary" : "secondary"}
                aria-pressed={draw === "circle"}
                onClick={() => {
                  setRegion(null);
                  setDraw(draw === "circle" ? null : "circle");
                }}
              >
                Draw circle
              </Button>
            </div>
            <p className="text-caption text-slate-600" role="status">
              {draw === "polygon"
                ? "Click to add corners; double click or press Enter to finish."
                : draw === "circle"
                  ? "Click the center, then click the edge."
                  : region
                    ? `Region: ${region.name}`
                    : shape
                      ? "circle" in shape
                        ? `Circle of ${shape.circle.radius_km} km drawn.`
                        : "Polygon drawn."
                      : "Draw a shape, or choose a region below."}
            </p>
            <Field label="Or select a region by name" htmlFor="z-region">
              <Input
                id="z-region"
                value={q}
                onChange={(e) => void searchPlaces(e.target.value)}
                autoComplete="off"
              />
            </Field>
            {places.length ? (
              <ul className="max-h-32 overflow-y-auto rounded-control border border-line text-small">
                {places.map((p) => (
                  <li key={p.id}>
                    <button
                      type="button"
                      className="w-full px-3 py-1.5 text-left hover:bg-slate-100"
                      onClick={() => {
                        setRegion(p);
                        setShape(null);
                        setPlaces([]);
                        setQ(p.name);
                      }}
                    >
                      {p.name}, {p.admin1_name ?? ""} {p.country_code} ({p.type})
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
            <Field label="Name" htmlFor="z-name">
              <Input id="z-name" name="name" required maxLength={80} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Minimum level" htmlFor="z-level">
                <Select id="z-level" name="min_level" defaultValue="medium">
                  {LEVELS.map((l) => (
                    <option key={l}>{l}</option>
                  ))}
                </Select>
              </Field>
              <Field label="Minimum severity" htmlFor="z-sev">
                <Input id="z-sev" name="min_severity" type="number" min={1} max={4} defaultValue={1} />
              </Field>
            </div>
            <fieldset>
              <legend className="mb-1 text-small font-medium text-ink">Types (none means all)</legend>
              <div className="flex flex-wrap gap-3 text-small">
                {["natural_hazard", "conflict", "civil_unrest", "infrastructure", "health"].map((t) => (
                  <label key={t} className="flex items-center gap-1.5">
                    <Checkbox name="types" value={t} />
                    {title(t)}
                  </label>
                ))}
              </div>
            </fieldset>
            <Button type="submit" disabled={!shape && !region}>
              Create zone
            </Button>
          </form>
        ) : (
          <p className="text-small text-slate-600">Managers can create and edit zones.</p>
        )}
      </div>
      <div className="mt-6">
        {res.loading && !res.data ? (
          <LoadingRows rows={3} />
        ) : (
          <DataTable
            rows={res.data?.items ?? []}
            rowKey={(z) => z.id}
            caption="Watch zones"
            exportName="zones"
            empty={{
              title: "No watch zones",
              body: "Draw a polygon or circle on the map, or choose a region by name.",
            }}
            columns={[
              { key: "n", header: "Name", cell: (z) => z.name, value: (z) => z.name },
              {
                key: "l",
                header: "Minimum level",
                cell: (z) => z.rules?.min_level ?? "medium",
                value: (z) => z.rules?.min_level,
              },
              {
                key: "t",
                header: "Types",
                cell: (z) =>
                  z.rules?.event_types.length ? z.rules.event_types.map(title).join(", ") : "All",
              },
              {
                key: "a",
                header: "Actions",
                cell: (z) => (
                  <span className="flex gap-1">
                    <Button size="sm" variant="ghost" onClick={() => void test(z)}>
                      Test on last 30 days
                    </Button>
                    {canManage ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={async () => {
                          if (!window.confirm(`Delete the zone "${z.name}"?`)) return;
                          await api(`/zones/${z.id}`, { method: "DELETE" }).then(
                            () => res.reload(),
                            () => toast("The zone could not be deleted.", "error"),
                          );
                        }}
                      >
                        Delete
                      </Button>
                    ) : null}
                  </span>
                ),
              },
            ]}
          />
        )}
      </div>
      <Dialog open={!!testing} onOpenChange={(o) => !o && setTesting(null)}>
        <DialogContent>
          <DialogTitle className="text-h4 text-ink">Test rule: {testing?.zone.name}</DialogTitle>
          <DialogDescription className="text-small text-slate-600">
            Counts incidents of the last 30 days that match the type and severity rule inside the bounding box
            of the zone. This is an approximation of what would have alerted.
          </DialogDescription>
          <p className="mt-4 text-h3 text-ink">
            {testing?.count === null ? "Counting" : `${testing?.count} incidents`}
          </p>
        </DialogContent>
      </Dialog>
      <div className="mt-4">
        <Disclaimer />
      </div>
    </>
  );
}
