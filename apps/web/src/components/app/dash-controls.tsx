"use client";

import { useMemo, useState } from "react";
import { Checkbox, Input, Select } from "@/components/ui/field";
import { when } from "@/lib/app/format";

export type Range = {
  preset: string;
  from: string;
  to: string;
  granularity: "day" | "week" | "month";
  compare: boolean;
};
const iso = (d: Date) => d.toISOString().slice(0, 10);

export function useRange(initialPreset = "30d", granularity: Range["granularity"] = "day") {
  const [r, setR] = useState<Range>({ preset: initialPreset, from: "", to: "", granularity, compare: false });
  const resolved = useMemo(() => {
    const today = new Date();
    const days = { "30d": 30, "90d": 90, "12m": 365, "36m": 1100, all: 4000 }[r.preset];
    const from = r.preset === "custom" ? r.from : iso(new Date(today.getTime() - (days ?? 30) * 86_400_000));
    const to = r.preset === "custom" ? r.to : iso(today);
    return { ...r, from, to };
  }, [r]);
  return [resolved, setR] as const;
}

/** Date range presets, granularity, comparison toggle and the "as of" time shared by every dashboard. */
export function DashControls({
  range,
  onChange,
  asOf,
  showCompare = true,
  granularities = ["day", "week", "month"],
}: {
  range: Range;
  onChange: (r: Range) => void;
  asOf?: string | null;
  showCompare?: boolean;
  granularities?: Range["granularity"][];
}) {
  return (
    <div className="mb-4 flex flex-wrap items-end gap-3 rounded-card border border-line bg-white p-3">
      <div>
        <label htmlFor="dc-range" className="mb-1 block text-caption text-slate-600">
          Date range
        </label>
        <Select
          id="dc-range"
          className="h-9"
          value={range.preset}
          onChange={(e) => onChange({ ...range, preset: e.target.value })}
        >
          <option value="30d">Last 30 days</option>
          <option value="90d">Last 90 days</option>
          <option value="12m">Last 12 months</option>
          <option value="all">All time</option>
          <option value="custom">Custom</option>
        </Select>
      </div>
      {range.preset === "custom" ? (
        <>
          <div>
            <label htmlFor="dc-from" className="mb-1 block text-caption text-slate-600">
              From
            </label>
            <Input
              id="dc-from"
              type="date"
              className="h-9"
              value={range.from}
              onChange={(e) => onChange({ ...range, from: e.target.value })}
            />
          </div>
          <div>
            <label htmlFor="dc-to" className="mb-1 block text-caption text-slate-600">
              To
            </label>
            <Input
              id="dc-to"
              type="date"
              className="h-9"
              value={range.to}
              onChange={(e) => onChange({ ...range, to: e.target.value })}
            />
          </div>
        </>
      ) : null}
      <div>
        <label htmlFor="dc-gran" className="mb-1 block text-caption text-slate-600">
          Granularity
        </label>
        <Select
          id="dc-gran"
          className="h-9"
          value={range.granularity}
          onChange={(e) => onChange({ ...range, granularity: e.target.value as Range["granularity"] })}
        >
          {granularities.map((g) => (
            <option key={g} value={g}>
              {g[0]?.toUpperCase()}
              {g.slice(1)}
            </option>
          ))}
        </Select>
      </div>
      {showCompare ? (
        <label className="flex items-center gap-2 pb-2 text-small">
          <Checkbox
            checked={range.compare}
            onChange={(e) => onChange({ ...range, compare: e.target.checked })}
          />{" "}
          Compare with previous period
        </label>
      ) : null}
      <div className="ml-auto pb-2 text-caption text-slate-600">
        As of {asOf ? when(asOf) : when(new Date().toISOString())}
      </div>
    </div>
  );
}
