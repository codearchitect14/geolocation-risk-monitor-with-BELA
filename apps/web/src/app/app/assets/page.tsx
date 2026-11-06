"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { DataTable, type Column } from "@/components/app/data-table";
import { SavedViews } from "@/components/app/saved-views";
import { DemoBadge, ErrorState, LevelChip, LoadingRows, PageHeader } from "@/components/app/states";
import { UploadWizard } from "@/components/app/upload-wizard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Checkbox, Field, Input, Select } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, download, qs } from "@/lib/api";
import { centroid, fetchAll, type AlertItem, type AssetItem } from "@/lib/app/data";
import { title } from "@/lib/app/format";
import { atLeast, useSession } from "@/lib/app/session";
import { useApi } from "@/lib/app/use-api";

const ALL_COLUMNS = ["type", "criticality", "exposure", "country", "tags", "status", "coordinates"] as const;

export default function Assets() {
  const { me } = useSession();
  const toast = useToast();
  const canWrite = atLeast(me.role, "manager");
  const [f, setF] = useState<Record<string, string>>({
    q: "",
    type: "",
    min_criticality: "",
    tag: "",
    exposure: "",
    status: "active",
  });
  const [rows, setRows] = useState<AssetItem[]>();
  const [error, setError] = useState<Error>();
  const [tick, setTick] = useState(0);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [cols, setCols] = useState<Set<string>>(
    new Set(["type", "criticality", "exposure", "country", "tags"]),
  );
  const [wizard, setWizard] = useState(false);
  const [bulk, setBulk] = useState(false);
  const alerts = useApi<{ items: AlertItem[] }>("/alerts?limit=200");

  useEffect(() => {
    setRows(undefined);
    fetchAll<AssetItem>(
      `/assets${qs({ q: f.q, type: f.type, min_criticality: f.min_criticality, tag: f.tag, status: f.status })}`,
      5000,
    ).then(setRows, setError);
  }, [f.q, f.type, f.min_criticality, f.tag, f.status, tick]);

  const exposure = useMemo(() => {
    const m = new Map<string, string>();
    const rank = ["low", "medium", "high", "critical"];
    (alerts.data?.items ?? [])
      .filter((a) => !["dismissed", "resolved"].includes(a.status))
      .forEach((a) => {
        if (a.asset && rank.indexOf(a.level) > rank.indexOf(m.get(a.asset.id) ?? ""))
          m.set(a.asset.id, a.level);
      });
    return m;
  }, [alerts.data]);
  const shown = useMemo(
    () =>
      (rows ?? []).filter(
        (a) =>
          !f.exposure || (f.exposure === "none" ? !exposure.has(a.id) : exposure.get(a.id) === f.exposure),
      ),
    [rows, f.exposure, exposure],
  );
  const types = useMemo(() => [...new Set((rows ?? []).map((a) => a.type))], [rows]);

  const all: Record<string, Column<AssetItem>> = {
    type: { key: "type", header: "Type", cell: (a) => title(a.type), value: (a) => a.type },
    criticality: {
      key: "crit",
      header: "Criticality",
      cell: (a) => a.criticality,
      value: (a) => a.criticality,
      align: "right",
    },
    exposure: {
      key: "exp",
      header: "Exposure",
      cell: (a) =>
        exposure.get(a.id) ? (
          <LevelChip level={exposure.get(a.id) as string} />
        ) : (
          <span className="text-slate-500">None</span>
        ),
      value: (a) => exposure.get(a.id) ?? "none",
    },
    country: {
      key: "cc",
      header: "Country",
      cell: (a) => a.country_code ?? "",
      value: (a) => a.country_code,
    },
    tags: {
      key: "tags",
      header: "Tags",
      cell: (a) => (
        <span className="flex flex-wrap gap-1">
          {a.tags.map((t) => (
            <Badge key={t}>{t}</Badge>
          ))}
        </span>
      ),
      value: (a) => a.tags.join("|"),
    },
    status: { key: "st", header: "Status", cell: (a) => a.status, value: (a) => a.status },
    coordinates: {
      key: "co",
      header: "Coordinates",
      cell: (a) => (
        <span className="font-mono text-caption">
          {centroid(a.geometry)
            .map((n) => n.toFixed(3))
            .join(", ")}
        </span>
      ),
      value: (a) => centroid(a.geometry).join(" "),
    },
  };
  const columns: Column<AssetItem>[] = [
    { key: "name", header: "Name", cell: (a) => a.name, value: (a) => a.name },
    ...ALL_COLUMNS.filter((c) => cols.has(c)).map((c) => all[c] as Column<AssetItem>),
  ];

  async function applyBulk(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    const body: Record<string, unknown> = { asset_ids: [...sel] };
    if (d.get("criticality")) body.criticality = Number(d.get("criticality"));
    if (d.get("add_tags"))
      body.add_tags = String(d.get("add_tags"))
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
    if (d.get("status")) body.status = d.get("status");
    try {
      await api("/assets/bulk", { method: "POST", body });
      toast(`${sel.size} assets updated.`);
      setBulk(false);
      setSel(new Set());
      setTick((t) => t + 1);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "The change could not be saved.", "error");
    }
  }

  const set = (k: string, v: string) => setF((s) => ({ ...s, [k]: v }));
  return (
    <>
      <PageHeader
        title="Assets"
        description="Sites, facilities and routes you monitor. Locations are confidential to your organisation."
        badge={
          rows?.some((a) => a.name.includes("(illustrative)")) ? (
            <DemoBadge label="Illustrative assets" />
          ) : null
        }
        actions={
          <>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => void download("/assets-export", "assets.csv")}
            >
              Export CSV
            </Button>
            {canWrite ? (
              <Button size="sm" onClick={() => setWizard(true)}>
                Upload assets
              </Button>
            ) : null}
          </>
        }
      />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor="as-q" className="mb-1 block text-caption text-slate-600">
            Search
          </label>
          <Input
            id="as-q"
            className="h-9 w-52"
            value={f.q}
            onChange={(e) => set("q", e.target.value)}
            placeholder="Name or ID"
          />
        </div>
        <div>
          <label htmlFor="as-type" className="mb-1 block text-caption text-slate-600">
            Type
          </label>
          <Select id="as-type" className="h-9" value={f.type} onChange={(e) => set("type", e.target.value)}>
            <option value="">All</option>
            {types.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </Select>
        </div>
        <div>
          <label htmlFor="as-crit" className="mb-1 block text-caption text-slate-600">
            Criticality
          </label>
          <Select
            id="as-crit"
            className="h-9"
            value={f.min_criticality}
            onChange={(e) => set("min_criticality", e.target.value)}
          >
            <option value="">Any</option>
            {[2, 3, 4, 5].map((n) => (
              <option key={n} value={n}>
                {n} and above
              </option>
            ))}
          </Select>
        </div>
        <div>
          <label htmlFor="as-exp" className="mb-1 block text-caption text-slate-600">
            Exposure
          </label>
          <Select
            id="as-exp"
            className="h-9"
            value={f.exposure}
            onChange={(e) => set("exposure", e.target.value)}
          >
            <option value="">Any</option>
            <option value="none">Not exposed</option>
            {["low", "medium", "high", "critical"].map((l) => (
              <option key={l}>{l}</option>
            ))}
          </Select>
        </div>
        <div>
          <label htmlFor="as-tag" className="mb-1 block text-caption text-slate-600">
            Tag
          </label>
          <Input
            id="as-tag"
            className="h-9 w-28"
            value={f.tag}
            onChange={(e) => set("tag", e.target.value)}
          />
        </div>
        <div>
          <label htmlFor="as-st" className="mb-1 block text-caption text-slate-600">
            Status
          </label>
          <Select id="as-st" className="h-9" value={f.status} onChange={(e) => set("status", e.target.value)}>
            <option value="active">Active</option>
            <option value="archived">Archived</option>
          </Select>
        </div>
        <details className="relative">
          <summary className="flex h-9 cursor-pointer items-center rounded-control border border-slate-300 px-3 text-small">
            Columns
          </summary>
          <div className="absolute z-10 mt-1 w-44 space-y-1 rounded-control border border-line bg-white p-3 shadow-e2">
            {ALL_COLUMNS.map((c) => (
              <label key={c} className="flex items-center gap-2 text-small">
                <Checkbox
                  checked={cols.has(c)}
                  onChange={() =>
                    setCols((s) => {
                      const n = new Set(s);
                      if (n.has(c)) n.delete(c);
                      else n.add(c);
                      return n;
                    })
                  }
                />
                {title(c)}
              </label>
            ))}
          </div>
        </details>
        <SavedViews storageKey="assets" state={f} onApply={setF} />
      </div>
      {canWrite && sel.size ? (
        <div
          className="mb-3 flex items-center gap-3 rounded-control bg-brand-100 p-2 text-small"
          role="group"
          aria-label="Bulk actions"
        >
          {sel.size} selected{" "}
          <Button size="sm" variant="secondary" onClick={() => setBulk(true)}>
            Bulk edit
          </Button>
        </div>
      ) : null}
      {error ? (
        <ErrorState error={error} onRetry={() => setTick((t) => t + 1)} />
      ) : !rows ? (
        <LoadingRows rows={8} />
      ) : (
        <DataTable
          rows={shown}
          columns={columns}
          rowKey={(a) => a.id}
          caption="Assets"
          exportName="assets-view"
          selected={canWrite ? sel : undefined}
          onSelect={canWrite ? setSel : undefined}
          onRowClick={(a) => (window.location.href = `/app/assets/${a.id}`)}
          empty={{
            title: "No assets yet",
            body: canWrite
              ? "Upload a CSV or GeoJSON file to start monitoring. A template is in the upload dialog."
              : "Ask a manager to upload your assets.",
          }}
        />
      )}
      <p className="mt-3 text-caption text-slate-600">
        {shown.length} assets shown.{" "}
        <Link href="/app/map" className="underline">
          See them on the map
        </Link>
        .
      </p>
      <UploadWizard open={wizard} onOpenChange={setWizard} onDone={() => setTick((t) => t + 1)} />
      <Dialog open={bulk} onOpenChange={setBulk}>
        <DialogContent>
          <DialogTitle className="text-h4 text-ink">Edit {sel.size} assets</DialogTitle>
          <DialogDescription className="text-small text-slate-600">
            Only the fields you fill in are changed. Archiving removes assets from monitoring but keeps their
            history.
          </DialogDescription>
          <form onSubmit={applyBulk} className="mt-4 space-y-3">
            <Field label="Criticality" htmlFor="b-crit">
              <Select id="b-crit" name="criticality">
                <option value="">Leave as is</option>
                {[1, 2, 3, 4, 5].map((n) => (
                  <option key={n}>{n}</option>
                ))}
              </Select>
            </Field>
            <Field label="Add tags (comma separated)" htmlFor="b-tags">
              <Input id="b-tags" name="add_tags" />
            </Field>
            <Field label="Status" htmlFor="b-status">
              <Select id="b-status" name="status">
                <option value="">Leave as is</option>
                <option value="archived">Archive</option>
                <option value="active">Activate</option>
              </Select>
            </Field>
            <Button type="submit">Apply</Button>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
