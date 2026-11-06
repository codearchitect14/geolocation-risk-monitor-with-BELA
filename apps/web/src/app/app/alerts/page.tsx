"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { DataTable, type Column } from "@/components/app/data-table";
import {
  Disclaimer,
  ErrorState,
  LevelChip,
  LoadingRows,
  PageHeader,
  StatusChip,
} from "@/components/app/states";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Checkbox, Field, Input, Select, Textarea } from "@/components/ui/field";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, qs } from "@/lib/api";
import type { AlertItem } from "@/lib/app/data";
import { ago, km, title, when, LEVELS } from "@/lib/app/format";
import { atLeast, useSession } from "@/lib/app/session";
import { useApi } from "@/lib/app/use-api";

type Rule = {
  id: string;
  name: string;
  enabled: boolean;
  min_level: string;
  min_severity: number;
  event_types: string[];
  asset_group_ids: string[];
  escalation: { after_minutes: number } | null;
  quiet_hours: { start: string; end: string } | null;
};
type AlertDetail = AlertItem & {
  history?: { at: string; action: string; actor?: string; detail?: Record<string, unknown> }[];
  comments?: { at: string; text: string; author?: string }[];
};

const DISMISS_REASONS = [
  "Not relevant to this asset",
  "Already known",
  "Location is wrong",
  "Duplicate",
  "Other",
];

function RulesTab() {
  const res = useApi<{ items: Rule[]; default_when_none: { min_level: string } }>("/rules");
  const groups = useApi<{ items: { id: string; name: string }[] }>("/asset-groups");
  const [open, setOpen] = useState(false);
  const toast = useToast();
  async function create(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    try {
      await api("/rules", {
        method: "POST",
        body: {
          name: d.get("name"),
          min_level: d.get("min_level"),
          min_severity: Number(d.get("min_severity")),
          event_types: d.getAll("types"),
          asset_group_ids: d.getAll("groups"),
          enabled: true,
          escalation: d.get("esc") ? { after_minutes: Number(d.get("esc")) } : null,
          quiet_hours: d.get("qs") && d.get("qe") ? { start: d.get("qs"), end: d.get("qe") } : null,
        },
      });
      toast("Rule created.");
      setOpen(false);
      res.reload();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "The rule could not be saved.", "error");
    }
  }
  async function toggle(r: Rule) {
    try {
      await api(`/rules/${r.id}`, { method: "PATCH", body: { enabled: !r.enabled } });
      res.reload();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "The rule could not be changed.", "error");
    }
  }
  if (res.error) return <ErrorState error={res.error} onRetry={res.reload} />;
  return (
    <div>
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-small text-slate-600">
          With no rule, alerts are raised at level {res.data?.default_when_none.min_level ?? "medium"} and
          above for all assets.
        </p>
        <Button size="sm" onClick={() => setOpen(true)}>
          New rule
        </Button>
      </div>
      {res.loading && !res.data ? (
        <LoadingRows rows={3} />
      ) : (
        <DataTable
          rows={res.data?.items ?? []}
          rowKey={(r) => r.id}
          caption="Alert rules"
          empty={{
            title: "No rules yet",
            body: "Create a rule to choose which incidents raise alerts, for which assets, and when to escalate.",
          }}
          columns={[
            { key: "n", header: "Name", cell: (r) => r.name, value: (r) => r.name },
            {
              key: "l",
              header: "Minimum level",
              cell: (r) => <LevelChip level={r.min_level} />,
              value: (r) => r.min_level,
            },
            {
              key: "t",
              header: "Types",
              cell: (r) => (r.event_types.length ? r.event_types.map(title).join(", ") : "All"),
            },
            {
              key: "e",
              header: "Escalates after",
              cell: (r) => (r.escalation ? `${r.escalation.after_minutes} min` : "Never"),
            },
            {
              key: "q",
              header: "Quiet hours",
              cell: (r) => (r.quiet_hours ? `${r.quiet_hours.start} to ${r.quiet_hours.end}` : "None"),
            },
            {
              key: "on",
              header: "Enabled",
              cell: (r) => (
                <Button size="sm" variant="ghost" aria-pressed={r.enabled} onClick={() => toggle(r)}>
                  {r.enabled ? "On" : "Off"}
                </Button>
              ),
            },
          ]}
        />
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogTitle className="text-h4 text-ink">New alert rule</DialogTitle>
          <DialogDescription className="text-small text-slate-600">
            Quiet hours hold notifications; critical alerts are never held back.
          </DialogDescription>
          <form onSubmit={create} className="mt-4 space-y-3">
            <Field label="Name" htmlFor="r-name">
              <Input id="r-name" name="name" required maxLength={80} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Minimum level" htmlFor="r-level">
                <Select id="r-level" name="min_level" defaultValue="medium">
                  {LEVELS.map((l) => (
                    <option key={l}>{l}</option>
                  ))}
                </Select>
              </Field>
              <Field label="Minimum severity (1 to 4)" htmlFor="r-sev">
                <Input id="r-sev" name="min_severity" type="number" min={1} max={4} defaultValue={1} />
              </Field>
            </div>
            <fieldset>
              <legend className="mb-1 text-small font-medium text-ink">
                Incident types (none selected means all)
              </legend>
              <div className="flex flex-wrap gap-3 text-small">
                {["natural_hazard", "conflict", "civil_unrest", "infrastructure", "health", "transport"].map(
                  (t) => (
                    <label key={t} className="flex items-center gap-1.5">
                      <Checkbox name="types" value={t} />
                      {title(t)}
                    </label>
                  ),
                )}
              </div>
            </fieldset>
            {groups.data?.items.length ? (
              <fieldset>
                <legend className="mb-1 text-small font-medium text-ink">
                  Asset groups (none means all assets)
                </legend>
                <div className="flex flex-wrap gap-3 text-small">
                  {groups.data.items.map((g) => (
                    <label key={g.id} className="flex items-center gap-1.5">
                      <Checkbox name="groups" value={g.id} />
                      {g.name}
                    </label>
                  ))}
                </div>
              </fieldset>
            ) : null}
            <Field label="Escalate if not acknowledged after (minutes, optional)" htmlFor="r-esc">
              <Input id="r-esc" name="esc" type="number" min={5} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Quiet hours start (UTC)" htmlFor="r-qs">
                <Input id="r-qs" name="qs" type="time" />
              </Field>
              <Field label="Quiet hours end (UTC)" htmlFor="r-qe">
                <Input id="r-qe" name="qe" type="time" />
              </Field>
            </div>
            <Button type="submit">Create rule</Button>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function Alerts() {
  const { me } = useSession();
  const toast = useToast();
  const [f, setF] = useState({ level: "", status: "", mine: "" });
  const res = useApi<{ items: AlertItem[] }>(
    `/alerts${qs({ level: f.level, status: f.status, mine: f.mine || undefined, limit: 200 })}`,
  );
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [openId, setOpenId] = useState<string | null>(null);
  const [cursor, setCursor] = useState(0);
  const [reason, setReason] = useState<{ ids: string[] } | null>(null);
  const canAct = atLeast(me.role, "analyst");
  const rows = useMemo(() => res.data?.items ?? [], [res.data]);
  const detail = useApi<AlertDetail>(openId ? `/alerts/${openId}` : null);

  const act = useCallback(
    async (ids: string[], status: string, dismissal_reason?: string) => {
      const results = await Promise.allSettled(
        ids.map((id) =>
          api(`/alerts/${id}`, {
            method: "PATCH",
            body: { status, dismissal_reason: dismissal_reason ?? null },
          }),
        ),
      );
      const failed = results.filter((r) => r.status === "rejected").length;
      toast(
        failed
          ? `${ids.length - failed} updated, ${failed} could not be changed.`
          : `${ids.length} alert${ids.length > 1 ? "s" : ""} ${status}.`,
        failed ? "error" : "info",
      );
      setSelected(new Set());
      res.reload();
      if (openId) detail.reload();
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [toast, res.reload, openId],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (
        (e.target as HTMLElement).closest("input, textarea, select, [role=dialog]") ||
        e.ctrlKey ||
        e.metaKey
      )
        return;
      const cur = rows[cursor];
      if (e.key === "j") setCursor((c) => Math.min(c + 1, rows.length - 1));
      else if (e.key === "k") setCursor((c) => Math.max(c - 1, 0));
      else if (e.key === "Enter" && cur) setOpenId(cur.id);
      else if (e.key === "a" && cur && canAct) void act([cur.id], "acknowledged");
      else if (e.key === "d" && cur && canAct) setReason({ ids: [cur.id] });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [rows, cursor, canAct, act]);
  useEffect(() => setCursor(0), [f]);

  const columns: Column<AlertItem>[] = useMemo(
    () => [
      {
        key: "lvl",
        header: "Level",
        cell: (a) => <LevelChip level={a.level} />,
        value: (a) => LEVELS.indexOf(a.level as never),
      },
      {
        key: "ev",
        header: "Incident",
        cell: (a) => a.event.title,
        value: (a) => a.event.title,
        className: "max-w-md",
      },
      {
        key: "as",
        header: "Asset",
        cell: (a) => (a.asset ? `${a.asset.name} (${km(a.asset.distance_km)})` : "Watch zone"),
        value: (a) => a.asset?.name ?? "Watch zone",
      },
      { key: "st", header: "Status", cell: (a) => <StatusChip status={a.status} />, value: (a) => a.status },
      { key: "sc", header: "Score", cell: (a) => a.score.toFixed(2), value: (a) => a.score, align: "right" },
      { key: "ag", header: "Raised", cell: (a) => ago(a.created_at), value: (a) => a.created_at },
    ],
    [],
  );

  return (
    <>
      <PageHeader
        title="Alerts"
        description="Incidents that reached one of your assets. Shortcuts: j and k move, Enter opens, a acknowledges, d dismisses."
      />
      <Tabs defaultValue="queue">
        <TabsList>
          <TabsTrigger value="queue">Queue</TabsTrigger>
          {atLeast(me.role, "manager") ? <TabsTrigger value="rules">Rules</TabsTrigger> : null}
        </TabsList>
        <TabsContent value="queue" className="mt-4">
          <div className="mb-3 flex flex-wrap items-end gap-3">
            <div>
              <label htmlFor="al-level" className="mb-1 block text-caption text-slate-600">
                Level
              </label>
              <Select
                id="al-level"
                className="h-9"
                value={f.level}
                onChange={(e) => setF({ ...f, level: e.target.value })}
              >
                <option value="">All</option>
                {LEVELS.map((l) => (
                  <option key={l}>{l}</option>
                ))}
              </Select>
            </div>
            <div>
              <label htmlFor="al-status" className="mb-1 block text-caption text-slate-600">
                Status
              </label>
              <Select
                id="al-status"
                className="h-9"
                value={f.status}
                onChange={(e) => setF({ ...f, status: e.target.value })}
              >
                <option value="">All</option>
                {["new", "acknowledged", "monitoring", "escalated", "dismissed", "resolved"].map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </Select>
            </div>
            <label className="flex items-center gap-2 pb-2 text-small">
              <Checkbox
                checked={!!f.mine}
                onChange={(e) => setF({ ...f, mine: e.target.checked ? "true" : "" })}
              />{" "}
              Assigned to me
            </label>
            {canAct && selected.size ? (
              <div className="ml-auto flex gap-2" role="group" aria-label="Bulk actions">
                <Button size="sm" variant="secondary" onClick={() => act([...selected], "acknowledged")}>
                  Acknowledge {selected.size}
                </Button>
                <Button size="sm" variant="secondary" onClick={() => setReason({ ids: [...selected] })}>
                  Dismiss {selected.size}
                </Button>
              </div>
            ) : null}
          </div>
          {res.error ? (
            <ErrorState error={res.error} onRetry={res.reload} />
          ) : res.loading && !res.data ? (
            <LoadingRows />
          ) : (
            <DataTable
              rows={rows}
              columns={columns}
              rowKey={(a) => a.id}
              caption="Alert queue"
              exportName="alerts"
              selected={canAct ? selected : undefined}
              onSelect={canAct ? setSelected : undefined}
              onRowClick={(a) => setOpenId(a.id)}
              activeKey={rows[cursor]?.id}
              empty={{
                title: "No alerts",
                body: "Nothing matches these filters. Alerts appear when an incident reaches an asset.",
              }}
            />
          )}
          <div className="mt-4">
            <Disclaimer />
          </div>
        </TabsContent>
        <TabsContent value="rules" className="mt-4">
          <RulesTab />
        </TabsContent>
      </Tabs>

      <Dialog open={!!openId} onOpenChange={(o) => !o && setOpenId(null)}>
        <DialogContent side="right" className="max-w-md">
          <DialogTitle className="text-h4 text-ink">Alert</DialogTitle>
          <DialogDescription className="text-small text-slate-600">
            Review, acknowledge or dismiss.
          </DialogDescription>
          {detail.data ? (
            <div className="mt-4 space-y-3 text-small">
              <div className="flex gap-2">
                <LevelChip level={detail.data.level} />
                <StatusChip status={detail.data.status} />
              </div>
              <p className="text-ink">{detail.data.event.title}</p>
              <p className="text-slate-600">
                {detail.data.asset ? (
                  <>
                    Asset:{" "}
                    <Link href={`/app/assets/${detail.data.asset.id}`} className="underline">
                      {detail.data.asset.name}
                    </Link>
                    , {km(detail.data.asset.distance_km)} away.
                  </>
                ) : (
                  "Raised by a watch zone."
                )}{" "}
                Score {detail.data.score.toFixed(2)}.
              </p>
              <Button asChild variant="secondary" size="sm">
                <Link href={`/app/incidents/${detail.data.event.id}`}>Open incident</Link>
              </Button>
              {canAct ? (
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" onClick={() => act([detail.data!.id], "acknowledged")}>
                    Acknowledge
                  </Button>
                  <Button size="sm" variant="secondary" onClick={() => act([detail.data!.id], "escalated")}>
                    Escalate
                  </Button>
                  <Button size="sm" variant="secondary" onClick={() => act([detail.data!.id], "resolved")}>
                    Resolve
                  </Button>
                  <Button size="sm" variant="secondary" onClick={() => setReason({ ids: [detail.data!.id] })}>
                    Dismiss
                  </Button>
                </div>
              ) : null}
              {detail.data.dismissal_reason ? (
                <p className="text-slate-600">Dismissed: {detail.data.dismissal_reason}</p>
              ) : null}
              {canAct ? (
                <form
                  onSubmit={async (e) => {
                    e.preventDefault();
                    const text = String(new FormData(e.currentTarget).get("text") ?? "");
                    try {
                      await api(`/alerts/${detail.data!.id}/comments`, { method: "POST", body: { text } });
                      (e.target as HTMLFormElement).reset();
                      detail.reload();
                    } catch {
                      toast("The comment could not be saved.", "error");
                    }
                  }}
                >
                  <label htmlFor="al-c" className="mb-1 block text-small font-medium text-ink">
                    Comment
                  </label>
                  <Textarea id="al-c" name="text" required maxLength={1000} />
                  <Button type="submit" size="sm" variant="secondary" className="mt-2">
                    Add comment
                  </Button>
                </form>
              ) : null}
              <h3 className="pt-2 text-small font-medium text-ink">History</h3>
              <ul className="space-y-1 text-caption text-slate-600">
                {(detail.data.history ?? []).map((h, i) => (
                  <li key={i}>
                    {when(h.at)}: {h.action.replace(/[._]/g, " ")}
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <div className="mt-6">
              <LoadingRows rows={4} />
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={!!reason} onOpenChange={(o) => !o && setReason(null)}>
        <DialogContent>
          <DialogTitle className="text-h4 text-ink">
            Dismiss {reason?.ids.length} alert{(reason?.ids.length ?? 0) > 1 ? "s" : ""}?
          </DialogTitle>
          <DialogDescription className="text-small text-slate-600">
            Dismissed alerts stay in the history. Choose a reason; it improves future alerting.
          </DialogDescription>
          <form
            className="mt-4 space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              const r = String(new FormData(e.currentTarget).get("reason"));
              const ids = reason!.ids;
              setReason(null);
              void act(ids, "dismissed", r);
            }}
          >
            <Select name="reason" aria-label="Dismissal reason" required>
              {DISMISS_REASONS.map((r) => (
                <option key={r}>{r}</option>
              ))}
            </Select>
            <Button type="submit" variant="destructive">
              Dismiss
            </Button>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
