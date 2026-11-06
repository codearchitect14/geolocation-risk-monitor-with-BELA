"use client";

import { AlertTriangle, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/misc";
import { DISCLAIMER } from "@/lib/utils";
import type { ApiError } from "@/lib/api";

export function ErrorState({ error, onRetry }: { error: ApiError | Error; onRetry?: () => void }) {
  const status = "status" in error ? error.status : 0;
  const text =
    status === 403
      ? "Your role does not have access to this."
      : status === 429
        ? "Too many requests. Wait a moment and try again."
        : error.message;
  return (
    <div
      role="alert"
      className="flex flex-col items-start gap-3 rounded-card border border-danger/40 bg-white p-6"
    >
      <div className="flex items-center gap-2 font-medium text-danger">
        <AlertTriangle className="size-5" aria-hidden="true" /> Something went wrong
      </div>
      <p className="text-small text-slate-700">{text}</p>
      {onRetry && status !== 403 ? (
        <Button size="sm" variant="secondary" onClick={onRetry}>
          <RefreshCw className="size-4" aria-hidden="true" /> Try again
        </Button>
      ) : null}
    </div>
  );
}

export function LoadingRows({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-2" role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  );
}

export function DemoBadge({ label = "Demo data" }: { label?: string }) {
  return <Badge tone="illustrative">{label}</Badge>;
}

export function Disclaimer() {
  return <p className="text-caption text-slate-600">{DISCLAIMER}</p>;
}

export function PageHeader({
  title,
  description,
  actions,
  badge,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  badge?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-h3 text-ink">{title}</h1>
          {badge}
        </div>
        {description ? <p className="mt-1 max-w-3xl text-small text-slate-600">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function Kpi({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "danger";
}) {
  return (
    <div className="rounded-card border border-line bg-white p-4 shadow-e1">
      <div className="text-caption font-medium uppercase tracking-wide text-slate-600">{label}</div>
      <div className={`mt-1 text-h3 tabular-nums ${tone === "danger" ? "text-danger" : "text-ink"}`}>
        {value}
      </div>
      {hint ? <div className="mt-0.5 text-caption text-slate-600">{hint}</div> : null}
    </div>
  );
}

const LEVEL_TONE = { critical: "danger", high: "danger", medium: "warning", low: "neutral" } as const;
export function LevelChip({ level }: { level: string }) {
  const marks: Record<string, string> = { critical: "◆", high: "▲", medium: "■", low: "●" };
  return (
    <Badge tone={LEVEL_TONE[level as keyof typeof LEVEL_TONE] ?? "neutral"}>
      <span aria-hidden="true">{marks[level] ?? "●"}</span>
      {level[0]?.toUpperCase()}
      {level.slice(1)}
    </Badge>
  );
}

const STATUS_TONE: Record<string, "neutral" | "brand" | "success" | "warning" | "danger"> = {
  new: "brand",
  acknowledged: "warning",
  escalated: "danger",
  resolved: "success",
  dismissed: "neutral",
  fresh: "success",
  current: "success",
  ok: "success",
  up: "success",
  retrying: "warning",
  failing: "danger",
  down: "danger",
  stale: "warning",
  "no data": "neutral",
  active: "success",
  paid: "success",
  open: "warning",
  overdue: "danger",
};
export function StatusChip({ status }: { status: string }) {
  return <Badge tone={STATUS_TONE[status] ?? "neutral"}>{status.replace(/_/g, " ")}</Badge>;
}
