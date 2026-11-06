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
import { Badge, SeverityBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Field, Select, Textarea, Checkbox } from "@/components/ui/field";
import { Breadcrumbs, Skeleton } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, download } from "@/lib/api";
import { atLeast, useSession } from "@/lib/app/session";
import { centroid, levelFromSeverity, type EventItem } from "@/lib/app/data";
import { ago, km, num, title, when } from "@/lib/app/format";
import { useApi } from "@/lib/app/use-api";

const AppMap = dynamic(() => import("@/components/app/app-map"), {
  ssr: false,
  loading: () => <Skeleton className="size-full" />,
});

type Candidate = {
  rank: number;
  place_id: number;
  name: string;
  type: string;
  country_code: string | null;
  bela_score: number | null;
  gazetteer_score: number | null;
  context_score: number | null;
  blink_score: number | null;
  llm_label: string | null;
};
type Detail = EventItem & {
  sources: {
    kind: string;
    url: string;
    published_at: string | null;
    snippet: string | null;
    reliability: number;
  }[];
  timeline: {
    at: string;
    kind: string;
    source_kind?: string;
    url?: string;
    snippet?: string | null;
    update_type?: string;
    detail?: Record<string, unknown>;
  }[];
  location: {
    geometry: GeoJSON.Geometry;
    uncertainty_km: number;
    level: string;
    confidence: number;
    place: { name: string; type: string; country_code: string; admin1: string | null } | null;
  } | null;
  linked_places: { id: number; name: string; mentions: number; is_event_location: boolean }[];
  location_candidates: {
    surface: string;
    route: string;
    decision: string;
    chosen_place_id: number | null;
    candidates: Candidate[];
  }[];
  exposures: {
    asset_id: string;
    asset_name: string;
    distance_km: number;
    score: number;
    level: string;
    components: Components;
  }[];
  similar_past_incidents: {
    id: string;
    title: string;
    severity: number;
    first_seen_at: string;
    distance_km: number;
  }[];
};

const fmt = (n: number | null) => (n === null ? "n/a" : num(n, 2));

/** Wrap every place name found in the evidence text so the reader can see what the system linked. */
function Highlighted({ text, names }: { text: string; names: string[] }) {
  const uniq = [...new Set(names.filter((n) => n.length > 2))].map((n) =>
    n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"),
  );
  if (!uniq.length) return <>{text}</>;
  const parts = text.split(new RegExp(`(${uniq.join("|")})`, "gi"));
  return (
    <>
      {parts.map((p, i) =>
        i % 2 ? (
          <mark key={i} className="rounded bg-brand-100 px-0.5 text-ink">
            {p}
          </mark>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  );
}

function Correction({ eventId }: { eventId: string }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    setBusy(true);
    try {
      await api("/corrections", {
        method: "POST",
        body: {
          event_id: eventId,
          kind: d.get("kind"),
          note: d.get("note"),
          suggested_place: d.get("place") || null,
          suggested_type: d.get("stype") || null,
          consent_for_gold: d.get("consent") === "on",
        },
      });
      toast("Thank you. The correction was sent for review.");
      setOpen(false);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "The correction could not be sent.", "error");
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="secondary" size="sm">
          Request a correction
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogTitle className="text-h4 text-ink">Request a correction</DialogTitle>
        <DialogDescription className="text-small text-slate-600">
          Tell us what is wrong. A reviewer checks every request.
        </DialogDescription>
        <form onSubmit={submit} className="mt-4 space-y-3">
          <Field label="What is wrong" htmlFor="c-kind">
            <Select id="c-kind" name="kind" required>
              <option value="wrong_location">Wrong location</option>
              <option value="wrong_type">Wrong type</option>
              <option value="duplicate">Duplicate of another incident</option>
            </Select>
          </Field>
          <Field label="Suggested place (optional)" htmlFor="c-place">
            <input
              id="c-place"
              name="place"
              className="h-11 w-full rounded-control border border-slate-300 bg-white px-3"
            />
          </Field>
          <Field label="Suggested type (optional)" htmlFor="c-stype">
            <input
              id="c-stype"
              name="stype"
              className="h-11 w-full rounded-control border border-slate-300 bg-white px-3"
            />
          </Field>
          <Field label="Note" htmlFor="c-note">
            <Textarea id="c-note" name="note" required minLength={3} maxLength={1000} />
          </Field>
          <label className="flex items-start gap-2 text-small">
            <Checkbox name="consent" /> You may use this correction to improve location models.
          </label>
          <Button type="submit" disabled={busy}>
            {busy ? "Sending" : "Send correction"}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function IncidentDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { me } = useSession();
  const res = useApi<Detail>(`/events/${id}`);
  const toast = useToast();
  const d = res.data;
  const point = useMemo(() => {
    if (!d?.location) return [];
    const [lon, lat] = centroid(d.location.geometry);
    return [
      {
        id: d.id,
        lon,
        lat,
        level: levelFromSeverity(d.severity),
        label: d.title,
        type: d.type,
        uncertaintyKm: d.location.uncertainty_km || undefined,
        area: d.location.geometry.type === "Point" ? undefined : d.location.geometry,
      },
    ];
  }, [d]);
  if (res.error) return <ErrorState error={res.error} onRetry={res.reload} />;
  if (!d) return <LoadingRows rows={8} />;
  const names = d.linked_places.map((p) => p.name);

  async function report() {
    try {
      const r = await api<{ id: string }>(`/reports/incident/${id}`, { method: "POST" });
      await download(`/reports/${r.id}?format=pdf`, `incident-${id.slice(0, 8)}.pdf`);
      toast("The incident report was created and downloaded.");
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "The report could not be created.", "error");
    }
  }

  return (
    <>
      <Breadcrumbs
        items={[{ label: "Incidents", href: "/app/incidents" }, { label: d.title.slice(0, 60) }]}
      />
      <PageHeader
        title={d.title}
        description={`${title(d.subtype ?? d.type)}. First seen ${when(d.first_seen_at)}, last update ${ago(d.last_seen_at)}.`}
        actions={
          <>
            {atLeast(me.role, "analyst") ? (
              <Button size="sm" variant="secondary" onClick={report}>
                Create incident report
              </Button>
            ) : null}
            <Correction eventId={id} />
          </>
        }
      />
      <div className="mb-4 flex flex-wrap gap-2">
        <SeverityBadge level={levelFromSeverity(d.severity)} />
        <StatusChip status={d.status} />
        <Badge tone={d.confirmation === "unconfirmed" ? "warning" : "success"}>{d.confirmation_text}</Badge>
        {d.reduced_confidence ? <Badge tone="warning">Reduced confidence</Badge> : null}
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="overflow-hidden p-0 xl:col-span-2">
          <AppMap
            incidents={point}
            fit={
              point[0] ? [point[0].lon - 2, point[0].lat - 1.5, point[0].lon + 2, point[0].lat + 1.5] : null
            }
            label="Incident location with uncertainty circle"
            className="h-[360px] w-full"
          />
          <p className="px-4 py-2 text-caption text-slate-600">
            {d.location?.place
              ? `Located at ${d.location.place.name}${d.location.place.admin1 ? `, ${d.location.place.admin1}` : ""}, ${d.location.place.country_code}. `
              : ""}
            Uncertainty {km(d.location?.uncertainty_km)}, location level {d.location?.level ?? "n/a"},
            confidence {fmt(d.location?.confidence ?? null)}. Dashed circle shows the uncertainty radius.
          </p>
        </Card>
        <Card>
          <h2 className="text-h4 text-ink">Update timeline</h2>
          <ol className="mt-3 space-y-3 border-l border-line pl-4">
            {d.timeline.map((t, i) => (
              <li key={i} className="relative text-small">
                <span
                  className="absolute -left-[21px] top-1.5 size-2.5 rounded-full bg-brand-500"
                  aria-hidden="true"
                />
                <div className="text-caption text-slate-600">{when(t.at)}</div>
                <div className="text-ink">
                  {t.kind === "source"
                    ? `Report from ${t.source_kind}`
                    : `Pipeline: ${(t.update_type ?? "update").replace(/_/g, " ")}`}
                </div>
              </li>
            ))}
          </ol>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <h2 className="text-h4 text-ink">Evidence and sources</h2>
          <p className="text-caption text-slate-600">
            Text from reports is untrusted and shown as plain text. Place names the system linked are
            highlighted.
          </p>
          {d.summary ? (
            <p className="mt-3 whitespace-pre-line text-small text-slate-700">
              <Highlighted text={d.summary} names={names} />
            </p>
          ) : null}
          <ul className="mt-3 divide-y divide-line">
            {d.sources.map((s, i) => (
              <li key={i} className="py-2 text-small">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Badge tone="neutral">{s.kind}</Badge>
                  <span className="text-caption text-slate-600">
                    {s.published_at ? when(s.published_at) : "no date"}, reliability {num(s.reliability, 2)}
                  </span>
                </div>
                {s.snippet ? (
                  <p className="mt-1 text-slate-700">
                    <Highlighted text={s.snippet} names={names} />
                  </p>
                ) : null}
                <a
                  href={s.url}
                  target="_blank"
                  rel="noopener noreferrer nofollow"
                  className="break-all text-caption font-medium text-brand-600 underline"
                >
                  {s.url}
                </a>
              </li>
            ))}
          </ul>
        </Card>

        <Card>
          <h2 className="text-h4 text-ink">Location transparency</h2>
          <p className="text-caption text-slate-600">
            How the location was chosen. Decision:{" "}
            {d.location?.place
              ? `${d.location.place.name} (${d.location.level})`
              : d.location
                ? `${d.location.level} geometry from the source feed`
                : "no location"}
            .
          </p>
          {d.location_candidates.length === 0 ? (
            <p className="mt-3 text-small text-slate-600">
              This incident came from a structured hazard feed with a published geometry, so no place had to
              be inferred from text.
            </p>
          ) : (
            d.location_candidates.map((m, i) => (
              <div key={i} className="mt-3 rounded-control border border-line p-3">
                <div className="flex flex-wrap items-center justify-between gap-2 text-small">
                  <span className="font-medium text-ink">Mention: “{m.surface}”</span>
                  <Badge tone="neutral">route: {m.route}</Badge>
                </div>
                <div
                  className="overflow-x-auto"
                  tabIndex={0}
                  role="region"
                  aria-label={`Candidates for ${m.surface}`}
                >
                  <table className="mt-2 w-full text-caption">
                    <caption className="sr-only">Candidates considered for {m.surface}</caption>
                    <thead className="text-left text-slate-600">
                      <tr>
                        <th scope="col">Candidate</th>
                        <th scope="col">BELA</th>
                        <th scope="col">Gazetteer</th>
                        <th scope="col">Context</th>
                        <th scope="col">Re-rank</th>
                        <th scope="col">LLM</th>
                      </tr>
                    </thead>
                    <tbody>
                      {m.candidates.map((c) => (
                        <tr
                          key={c.place_id}
                          className={c.place_id === m.chosen_place_id ? "font-semibold text-ink" : ""}
                        >
                          <td>
                            {c.name}
                            {c.country_code ? `, ${c.country_code}` : ""}
                            {c.place_id === m.chosen_place_id ? " (chosen)" : ""}
                          </td>
                          <td className="tabular-nums">{fmt(c.bela_score)}</td>
                          <td className="tabular-nums">{fmt(c.gazetteer_score)}</td>
                          <td className="tabular-nums">{fmt(c.context_score)}</td>
                          <td className="tabular-nums">{fmt(c.blink_score)}</td>
                          <td>{c.llm_label ?? "n/a"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="mt-1 text-caption text-slate-600">Final decision: {m.decision}</p>
              </div>
            ))
          )}
        </Card>
      </div>

      <Card className="mt-4">
        <h2 className="text-h4 text-ink">Affected assets</h2>
        {d.exposures.length === 0 ? (
          <p className="mt-2 text-small text-slate-600">
            No asset of your organisation is currently exposed to this incident.
          </p>
        ) : (
          <div className="mt-3 space-y-3">
            {d.exposures.map((x) => (
              <details key={x.asset_id} className="rounded-control border border-line p-3">
                <summary className="flex cursor-pointer flex-wrap items-center justify-between gap-2 text-small">
                  <Link href={`/app/assets/${x.asset_id}`} className="font-medium text-ink hover:underline">
                    {x.asset_name}
                  </Link>
                  <span className="flex items-center gap-3">
                    <span className="tabular-nums text-slate-600">
                      {km(x.distance_km)}, score {num(x.score, 2)}
                    </span>
                    <LevelChip level={x.level} />
                  </span>
                </summary>
                <div className="mt-3">
                  <ScoreComponents components={x.components} />
                </div>
              </details>
            ))}
          </div>
        )}
      </Card>

      <Card className="mt-4">
        <h2 className="text-h4 text-ink">Similar past incidents</h2>
        {d.similar_past_incidents.length === 0 ? (
          <p className="mt-2 text-small text-slate-600">
            None of the same type within 100 km in the previous year.
          </p>
        ) : (
          <ul className="mt-2 space-y-1 text-small">
            {d.similar_past_incidents.map((s) => (
              <li key={s.id}>
                <Link href={`/app/incidents/${s.id}`} className="text-ink hover:underline">
                  {s.title}
                </Link>{" "}
                <span className="text-caption text-slate-600">
                  {when(s.first_seen_at)}, {km(s.distance_km)} away
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <div className="mt-4">
        <Disclaimer />
      </div>
    </>
  );
}
