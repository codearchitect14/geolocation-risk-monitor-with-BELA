"use client";

import { useState } from "react";
import { DataTable } from "@/components/app/data-table";
import { Disclaimer, ErrorState, LoadingRows, PageHeader } from "@/components/app/states";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, download } from "@/lib/api";
import { title, when } from "@/lib/app/format";
import { atLeast, useSession } from "@/lib/app/session";
import { useApi } from "@/lib/app/use-api";

type Briefing = {
  id: string;
  kind: string;
  period_start: string;
  period_end: string;
  created_at: string;
  evidence?: { items: unknown[] };
};

export default function Briefings() {
  const { me } = useSession();
  const toast = useToast();
  const res = useApi<{ items: Briefing[] }>("/briefings?limit=100");
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<Briefing | null>(null);
  const canCreate = atLeast(me.role, "analyst");

  async function create(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    const kind = String(d.get("kind"));
    const body: Record<string, unknown> = { kind };
    if (kind === "custom") {
      body.period_start = new Date(String(d.get("start"))).toISOString();
      body.period_end = new Date(String(d.get("end"))).toISOString();
    }
    try {
      await api("/briefings", { method: "POST", body });
      toast("Briefing created.");
      setOpen(false);
      res.reload();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "The briefing could not be created.", "error");
    }
  }
  async function email(id: string) {
    try {
      await api(`/briefings/${id}/email`, { method: "POST" });
      toast("The briefing was queued for email.");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Email is not available.", "error");
    }
  }

  if (res.error) return <ErrorState error={res.error} onRetry={res.reload} />;
  const items = (res.data?.items ?? []) as Briefing[];
  return (
    <>
      <PageHeader
        title="Briefings"
        description="Summaries of the alerts in a period. Daily and weekly briefings can be scheduled by an administrator under Administration, Risk configuration."
        actions={
          canCreate ? (
            <Button size="sm" onClick={() => setOpen(true)}>
              Create briefing
            </Button>
          ) : null
        }
      />
      {res.loading && !res.data ? (
        <LoadingRows rows={4} />
      ) : (
        <DataTable
          rows={items}
          rowKey={(b) => b.id}
          caption="Briefings"
          exportName="briefings"
          empty={{
            title: "No briefings yet",
            body: canCreate
              ? "Create a daily, weekly or custom briefing from your stored alerts."
              : "Briefings will appear here once your team creates them.",
          }}
          columns={[
            { key: "k", header: "Type", cell: (b) => title(b.kind), value: (b) => b.kind },
            {
              key: "p",
              header: "Period",
              cell: (b) => `${when(b.period_start)} to ${when(b.period_end)}`,
              value: (b) => b.period_start,
            },
            {
              key: "i",
              header: "Items",
              cell: (b) => b.evidence?.items.length ?? 0,
              value: (b) => b.evidence?.items.length ?? 0,
              align: "right",
            },
            { key: "c", header: "Created", cell: (b) => when(b.created_at), value: (b) => b.created_at },
            {
              key: "a",
              header: "Actions",
              cell: (b) => (
                <span className="flex flex-wrap gap-1">
                  <Button size="sm" variant="ghost" onClick={() => setView(b)}>
                    View
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      void download(
                        `/briefings/${b.id}?format=pdf`,
                        `briefing-${b.id.slice(0, 8)}.pdf`,
                      ).catch(() => toast("The PDF could not be downloaded.", "error"))
                    }
                  >
                    PDF
                  </Button>
                  {canCreate ? (
                    <Button size="sm" variant="ghost" onClick={() => void email(b.id)}>
                      Email
                    </Button>
                  ) : null}
                </span>
              ),
            },
          ]}
        />
      )}
      <div className="mt-4">
        <Disclaimer />
      </div>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogTitle className="text-h4 text-ink">Create a briefing</DialogTitle>
          <DialogDescription className="text-small text-slate-600">
            Built from alerts stored for your organisation.
          </DialogDescription>
          <form onSubmit={create} className="mt-4 space-y-3">
            <Field label="Type" htmlFor="br-kind">
              <Select id="br-kind" name="kind" defaultValue="daily">
                <option value="daily">Daily (last 24 hours)</option>
                <option value="weekly">Weekly (last 7 days)</option>
                <option value="custom">Custom period</option>
              </Select>
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Start (custom only)" htmlFor="br-s">
                <Input id="br-s" name="start" type="datetime-local" />
              </Field>
              <Field label="End (custom only)" htmlFor="br-e">
                <Input id="br-e" name="end" type="datetime-local" />
              </Field>
            </div>
            <Button type="submit">Create</Button>
          </form>
        </DialogContent>
      </Dialog>
      <Dialog open={!!view} onOpenChange={(o) => !o && setView(null)}>
        <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
          <DialogTitle className="text-h4 text-ink">{view ? `${title(view.kind)} briefing` : ""}</DialogTitle>
          <DialogDescription className="text-small text-slate-600">
            Rendered by the server from stored alerts. Report text is untrusted and shown in a sandboxed
            frame.
          </DialogDescription>
          <BriefingFrame id={view?.id} />
        </DialogContent>
      </Dialog>
    </>
  );
}

function BriefingFrame({ id }: { id?: string }) {
  const [src, setSrc] = useState<string>();
  const [err, setErr] = useState(false);
  const [loaded, setLoaded] = useState<string>();
  if (id && loaded !== id) {
    setLoaded(id);
    setSrc(undefined);
    setErr(false);
    fetch(`/api/v1/briefings/${id}?format=html`, { credentials: "same-origin" })
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error("failed"))))
      .then(
        (t) => setSrc(t),
        () => setErr(true),
      );
  }
  if (err) return <p className="mt-4 text-small text-danger">The briefing could not be loaded.</p>;
  if (!src)
    return (
      <div className="mt-4">
        <LoadingRows rows={4} />
      </div>
    );
  return (
    <iframe
      title="Briefing"
      sandbox=""
      srcDoc={src}
      className="mt-4 h-[60vh] w-full rounded-control border border-line bg-white"
    />
  );
}
