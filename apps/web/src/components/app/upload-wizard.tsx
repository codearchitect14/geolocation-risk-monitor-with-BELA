"use client";

import dynamic from "next/dynamic";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Select } from "@/components/ui/field";
import { Skeleton } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, download, upload } from "@/lib/api";
import { num } from "@/lib/app/format";
import { StatusChip } from "./states";

const AppMap = dynamic(() => import("./app-map"), {
  ssr: false,
  loading: () => <Skeleton className="size-full" />,
});

type Cand = {
  name: string;
  admin1: string | null;
  country_code: string | null;
  place_id: number;
  score: number;
  type: string;
  lat: number;
  lon: number;
};
type Row = {
  row: number;
  name: string;
  status: "ready" | "review" | "duplicate" | "error";
  message: string | null;
  geometry?: GeoJSON.Point;
  place?: { name: string; place_id: number };
  candidates: Cand[];
  country_code: string | null;
};
type Staged = {
  id: string;
  filename: string;
  rows_total: number;
  summary: Record<string, number>;
  mapping: Record<string, string>;
  rows: Row[];
};

const FIELDS = ["name", "lat", "lon", "city", "country", "criticality", "type", "external_id", "tags"];
const STEPS = ["File", "Columns", "Review locations", "Confirm"];

/** Four steps: choose a file, check the column mapping, review geocoded locations on a map, then confirm. */
export function UploadWizard({
  open,
  onOpenChange,
  onDone,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onDone: () => void;
}) {
  const [step, setStep] = useState(0);
  const [file, setFile] = useState<File | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [staged, setStaged] = useState<Staged | null>(null);
  const [choices, setChoices] = useState<Record<number, number>>({});
  const [skip, setSkip] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [drag, setDrag] = useState(false);
  const [progress, setProgress] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const toast = useToast();

  const reset = () => {
    setStep(0);
    setFile(null);
    setMapping({});
    setStaged(null);
    setChoices({});
    setSkip(new Set());
    setError("");
    setProgress("");
  };
  const close = async () => {
    if (staged && step < 4)
      await api(`/uploads/${staged.id}/cancel`, { method: "POST" }).catch(() => undefined);
    reset();
    onOpenChange(false);
  };

  async function stage(withMapping?: Record<string, string>) {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.set("file", file);
      if (withMapping) form.set("mapping", JSON.stringify(withMapping));
      if (staged) await api(`/uploads/${staged.id}/cancel`, { method: "POST" }).catch(() => undefined);
      const s = await upload<Staged>("/uploads/stage", form);
      setStaged(s);
      setMapping(s.mapping);
      setStep(1);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The file could not be read.");
    } finally {
      setBusy(false);
    }
  }

  async function commit() {
    if (!staged) return;
    setBusy(true);
    setError("");
    setProgress("Creating assets");
    try {
      const res = await api<{ created?: number; assets_created?: number }>(`/uploads/${staged.id}/commit`, {
        method: "POST",
        body: {
          choices: Object.entries(choices).map(([row, place_id]) => ({ row: Number(row), place_id })),
          skip_rows: [...skip],
        },
      });
      toast(`${res.created ?? res.assets_created ?? "The"} assets were added.`);
      reset();
      onOpenChange(false);
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The assets could not be created.");
    } finally {
      setBusy(false);
      setProgress("");
    }
  }

  const review = staged?.rows.filter((r) => r.status === "review") ?? [];
  const points = (staged?.rows ?? [])
    .filter((r) => r.geometry)
    .map((r) => {
      const c = choices[r.row] ? r.candidates.find((x) => x.place_id === choices[r.row]) : undefined;
      return {
        id: String(r.row),
        lon: c?.lon ?? (r.geometry as GeoJSON.Point).coordinates[0]!,
        lat: c?.lat ?? (r.geometry as GeoJSON.Point).coordinates[1]!,
        label: r.name,
        exposed: r.status === "review" && !c,
        criticality: 2,
      };
    });

  return (
    <Dialog open={open} onOpenChange={(o) => (o ? onOpenChange(true) : void close())}>
      <DialogContent className="max-h-[92vh] max-w-3xl overflow-y-auto">
        <DialogTitle className="text-h4 text-ink">Upload assets</DialogTitle>
        <DialogDescription className="text-small text-slate-600">
          Step {step + 1} of {STEPS.length}: {STEPS[step]}. Nothing is created until you confirm.
        </DialogDescription>
        <ol className="my-4 flex gap-2 text-caption" aria-label="Progress">
          {STEPS.map((s, i) => (
            <li
              key={s}
              aria-current={i === step ? "step" : undefined}
              className={`rounded-full px-3 py-1 ${i === step ? "bg-brand-600 text-white" : i < step ? "bg-brand-100 text-ink" : "bg-slate-100 text-slate-600"}`}
            >
              {i + 1}. {s}
            </li>
          ))}
        </ol>
        {error ? (
          <p role="alert" className="mb-3 rounded-control border border-danger/40 p-3 text-small text-danger">
            {error}
          </p>
        ) : null}

        {step === 0 ? (
          <div>
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDrag(true);
              }}
              onDragLeave={() => setDrag(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDrag(false);
                setFile(e.dataTransfer.files[0] ?? null);
              }}
              className={`rounded-card border-2 border-dashed p-8 text-center ${drag ? "border-brand-500 bg-brand-100" : "border-slate-300"}`}
            >
              <p className="text-small text-slate-700">Drop a CSV or GeoJSON file here, or</p>
              <input
                ref={input}
                id="asset-file"
                type="file"
                accept=".csv,.geojson,.json,text/csv,application/geo+json"
                className="sr-only"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
              <Button variant="secondary" size="sm" className="mt-2" onClick={() => input.current?.click()}>
                Choose a file
              </Button>
              {file ? (
                <p className="mt-3 text-small text-ink">
                  {file.name} ({num(file.size / 1024, 1)} KB)
                </p>
              ) : null}
            </div>
            <div className="mt-4 flex flex-wrap justify-between gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => void download("/uploads/template?format=csv", "assets-template.csv")}
              >
                Download the CSV template
              </Button>
              <Button disabled={!file || busy} onClick={() => void stage()}>
                {busy ? "Reading" : "Continue"}
              </Button>
            </div>
          </div>
        ) : null}

        {step === 1 && staged ? (
          <div>
            <p className="mb-3 text-small text-slate-600">
              {staged.rows_total} rows. Match each field to a column of your file.
            </p>
            <div className="grid gap-3 sm:grid-cols-2">
              {FIELDS.map((f) => (
                <div key={f}>
                  <label htmlFor={`map-${f}`} className="mb-1 block text-small font-medium text-ink">
                    {f.replace("_", " ")}
                  </label>
                  <Select
                    id={`map-${f}`}
                    value={mapping[f] ?? ""}
                    onChange={(e) => setMapping({ ...mapping, [f]: e.target.value })}
                  >
                    <option value="">Not in my file</option>
                    {[...new Set(Object.values(staged.mapping))].map((c) => (
                      <option key={c}>{c}</option>
                    ))}
                  </Select>
                </div>
              ))}
            </div>
            <div className="mt-4 flex justify-between">
              <Button variant="ghost" onClick={() => setStep(0)}>
                Back
              </Button>
              <div className="flex gap-2">
                <Button variant="secondary" disabled={busy} onClick={() => void stage(mapping)}>
                  Apply mapping
                </Button>
                <Button onClick={() => setStep(2)}>Continue</Button>
              </div>
            </div>
          </div>
        ) : null}

        {step === 2 && staged ? (
          <div>
            <p className="mb-2 text-small text-slate-700">
              {staged.summary.ready ?? 0} ready, {staged.summary.review ?? 0} need review,{" "}
              {staged.summary.duplicate ?? 0} duplicates, {staged.summary.error ?? 0} errors. Red markers need
              a choice.
            </p>
            <div className="h-64 overflow-hidden rounded-card border border-line">
              <AppMap assets={points} label="Geocode preview" className="size-full" />
            </div>
            <div
              className="mt-3 max-h-64 overflow-y-auto rounded-card border border-line"
              tabIndex={0}
              role="region"
              aria-label="Rows to review"
            >
              <table className="w-full text-small">
                <caption className="sr-only">Rows from the file</caption>
                <thead className="bg-slate-50 text-left text-caption text-slate-600">
                  <tr>
                    <th scope="col" className="px-2 py-1">
                      Row
                    </th>
                    <th scope="col">Name</th>
                    <th scope="col">Status</th>
                    <th scope="col">Location</th>
                    <th scope="col">Skip</th>
                  </tr>
                </thead>
                <tbody>
                  {staged.rows.map((r) => (
                    <tr key={r.row} className="border-t border-line">
                      <td className="px-2 py-1">{r.row}</td>
                      <td>{r.name}</td>
                      <td>
                        <StatusChip status={r.status === "ready" ? "active" : r.status} />
                      </td>
                      <td>
                        {r.status === "review" && r.candidates.length ? (
                          <Select
                            aria-label={`Location for row ${r.row}`}
                            className="h-8 text-caption"
                            value={choices[r.row] ?? ""}
                            onChange={(e) => setChoices({ ...choices, [r.row]: Number(e.target.value) })}
                          >
                            <option value="">Best match: {r.place?.name}</option>
                            {r.candidates.map((c) => (
                              <option key={c.place_id} value={c.place_id}>
                                {c.name}, {c.admin1 ?? c.country_code} ({c.type})
                              </option>
                            ))}
                          </Select>
                        ) : (
                          (r.message ?? "OK")
                        )}
                      </td>
                      <td>
                        <input
                          type="checkbox"
                          aria-label={`Skip row ${r.row}`}
                          checked={skip.has(r.row) || r.status === "error"}
                          disabled={r.status === "error"}
                          onChange={() => {
                            const n = new Set(skip);
                            if (n.has(r.row)) n.delete(r.row);
                            else n.add(r.row);
                            setSkip(n);
                          }}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-4 flex justify-between">
              <Button variant="ghost" onClick={() => setStep(1)}>
                Back
              </Button>
              <Button onClick={() => setStep(3)}>
                Continue ({review.length - Object.keys(choices).length} unreviewed)
              </Button>
            </div>
          </div>
        ) : null}

        {step === 3 && staged ? (
          <div>
            <p className="text-small text-slate-700">
              {staged.rows.filter((r) => r.status !== "error" && !skip.has(r.row)).length} of{" "}
              {staged.rows_total} rows will become assets. Rows with errors and rows you skipped are left out.
              You can edit or archive assets afterwards.
            </p>
            {progress ? (
              <p role="status" className="mt-3 text-small text-slate-600">
                {progress}
              </p>
            ) : null}
            <div className="mt-4 flex justify-between">
              <Button variant="ghost" onClick={() => setStep(2)}>
                Back
              </Button>
              <Button disabled={busy} onClick={() => void commit()}>
                {busy ? "Creating" : "Create assets"}
              </Button>
            </div>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
