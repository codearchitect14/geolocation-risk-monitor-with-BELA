"use client";

import { num, title } from "@/lib/app/format";

export type Components = Record<string, number | boolean>;

/** Every factor behind an exposure score, as a plain definition list so the score can be checked by hand. */
export function ScoreComponents({ components }: { components: Components }) {
  const order = [
    "proximity",
    "severity_weight",
    "type_weight",
    "recency_decay",
    "source_reliability",
    "location_confidence",
    "criticality_factor",
    "lambda_km",
    "uncertainty_km",
    "half_life_hours",
    "raw_score",
  ];
  const keys = [
    ...order.filter((k) => k in components),
    ...Object.keys(components).filter((k) => !order.includes(k) && k !== "clamped"),
  ];
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-small sm:grid-cols-3">
      {keys.map((k) => (
        <div key={k}>
          <dt className="text-caption text-slate-600">{title(k)}</dt>
          <dd className="tabular-nums text-ink">
            {typeof components[k] === "number" ? num(components[k] as number, 3) : String(components[k])}
          </dd>
        </div>
      ))}
    </dl>
  );
}
