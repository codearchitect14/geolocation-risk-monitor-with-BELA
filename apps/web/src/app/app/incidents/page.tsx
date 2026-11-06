"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { DataTable, type Column } from "@/components/app/data-table";
import { Disclaimer, ErrorState, LoadingRows, PageHeader, StatusChip } from "@/components/app/states";
import { SavedViews } from "@/components/app/saved-views";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Input, Select } from "@/components/ui/field";
import { qs } from "@/lib/api";
import { EVENT_TYPES, levelFromSeverity, type EventItem } from "@/lib/app/data";
import { ago, title, when } from "@/lib/app/format";
import { useApi } from "@/lib/app/use-api";
import { SeverityBadge } from "@/components/ui/badge";

const WINDOWS: Record<string, number> = { "24h": 1, "7d": 7, "30d": 30, all: 0 };

export default function Incidents() {
  const [f, setF] = useState<Record<string, string>>({
    type: "",
    severity: "",
    status: "",
    confirmation: "",
    window: "7d",
    q: "",
  });
  const [open, setOpen] = useState<EventItem | null>(null);
  // Fixed per window choice: reading the clock on every render would change the request address and refetch without end.
  const since = useMemo(
    () =>
      WINDOWS[f.window as string]
        ? new Date(Date.now() - (WINDOWS[f.window as string] as number) * 86_400_000).toISOString()
        : undefined,
    [f.window],
  );
  const path = `/events${qs({ type: f.type, min_severity: f.severity, status: f.status, confirmation: f.confirmation, since, limit: 200 })}`;
  const res = useApi<{ items: EventItem[] }>(path);
  const rows = useMemo(() => {
    const q = (f.q ?? "").toLowerCase();
    return (res.data?.items ?? []).filter((e) => !q || e.title.toLowerCase().includes(q));
  }, [res.data, f.q]);
  const set = (k: string, v: string) => setF((s) => ({ ...s, [k]: v }));

  const columns: Column<EventItem>[] = [
    {
      key: "sev",
      header: "Severity",
      cell: (e) => <SeverityBadge level={levelFromSeverity(e.severity)} />,
      value: (e) => e.severity,
    },
    { key: "title", header: "Incident", cell: (e) => e.title, value: (e) => e.title, className: "max-w-xl" },
    {
      key: "type",
      header: "Type",
      cell: (e) => title(e.subtype ?? e.type),
      value: (e) => e.subtype ?? e.type,
    },
    {
      key: "status",
      header: "Status",
      cell: (e) => <StatusChip status={e.status} />,
      value: (e) => e.status,
    },
    {
      key: "conf",
      header: "Confirmation",
      cell: (e) => (
        <Badge tone={e.confirmation === "unconfirmed" ? "warning" : "success"}>{e.confirmation_text}</Badge>
      ),
      value: (e) => e.confirmation,
    },
    {
      key: "src",
      header: "Sources",
      cell: (e) => e.source_count,
      value: (e) => e.source_count,
      align: "right",
    },
    { key: "seen", header: "Last update", cell: (e) => ago(e.last_seen_at), value: (e) => e.last_seen_at },
  ];

  return (
    <>
      <PageHeader
        title="Incidents"
        description="Events from news and public hazard feeds. Duplicate reports are merged into one incident; the source count shows how many reports back it."
      />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor="f-q" className="mb-1 block text-caption text-slate-600">
            Search
          </label>
          <Input
            id="f-q"
            className="h-9 w-56"
            value={f.q}
            onChange={(e) => set("q", e.target.value)}
            placeholder="Title contains"
          />
        </div>
        {[
          ["type", "Type", [["", "All types"], ...EVENT_TYPES.map((t) => [t, title(t)])]],
          [
            "severity",
            "Severity",
            [
              ["", "Any"],
              ["2", "2 and above"],
              ["3", "3 and above"],
              ["4", "4 only"],
            ],
          ],
          [
            "status",
            "Status",
            [
              ["", "Any"],
              ["new", "New"],
              ["developing", "Developing"],
              ["ongoing", "Ongoing"],
              ["closed", "Closed"],
            ],
          ],
          [
            "confirmation",
            "Confirmation",
            [
              ["", "Any"],
              ["unconfirmed", "Unconfirmed"],
              ["confirmed", "Confirmed"],
            ],
          ],
          [
            "window",
            "Time window",
            [
              ["24h", "Last 24 hours"],
              ["7d", "Last 7 days"],
              ["30d", "Last 30 days"],
              ["all", "All time"],
            ],
          ],
        ].map(([k, label, opts]) => (
          <div key={k as string}>
            <label htmlFor={`f-${k}`} className="mb-1 block text-caption text-slate-600">
              {label as string}
            </label>
            <Select
              id={`f-${k}`}
              className="h-9"
              value={f[k as string]}
              onChange={(e) => set(k as string, e.target.value)}
            >
              {(opts as string[][]).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </Select>
          </div>
        ))}
        <SavedViews storageKey="incidents" state={f} onApply={setF} />
      </div>
      {res.error ? (
        <ErrorState error={res.error} onRetry={res.reload} />
      ) : res.loading && !res.data ? (
        <LoadingRows />
      ) : (
        <DataTable
          rows={rows}
          columns={columns}
          rowKey={(e) => e.id}
          caption="Incidents"
          exportName="incidents"
          onRowClick={setOpen}
          activeKey={open?.id}
          empty={{ title: "No incidents match", body: "Widen the time window or clear a filter." }}
        />
      )}
      <p className="mt-3 text-caption text-slate-600">{rows.length} incidents shown.</p>
      <div className="mt-4">
        <Disclaimer />
      </div>

      <Dialog open={!!open} onOpenChange={(o) => !o && setOpen(null)}>
        <DialogContent side="right" className="max-w-md">
          {open ? (
            <>
              <DialogTitle className="pr-8 text-h4 text-ink">{open.title}</DialogTitle>
              <DialogDescription className="mt-1 text-small text-slate-600">
                {title(open.subtype ?? open.type)}, first seen {when(open.first_seen_at)}
              </DialogDescription>
              <div className="mt-3 flex flex-wrap gap-2">
                <SeverityBadge level={levelFromSeverity(open.severity)} />
                <StatusChip status={open.status} />
                <Badge tone="neutral">{open.confirmation_text}</Badge>
              </div>
              {open.summary ? (
                <p className="mt-4 whitespace-pre-line text-small text-slate-700">{open.summary}</p>
              ) : null}
              <dl className="mt-4 grid grid-cols-2 gap-2 text-small">
                <dt className="text-slate-600">Location level</dt>
                <dd>{open.location_level}</dd>
                <dt className="text-slate-600">Uncertainty</dt>
                <dd>{open.uncertainty_km} km</dd>
                <dt className="text-slate-600">Sources</dt>
                <dd>{open.source_count}</dd>
              </dl>
              {open.reduced_confidence ? (
                <p className="mt-3 text-caption text-caution">
                  Reduced confidence: a fallback was used for this location.
                </p>
              ) : null}
              <Button asChild className="mt-6">
                <Link href={`/app/incidents/${open.id}`}>Open full incident</Link>
              </Button>
            </>
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  );
}
