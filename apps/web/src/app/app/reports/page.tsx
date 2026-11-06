"use client";

import { useState } from "react";
import { DataTable } from "@/components/app/data-table";
import { Disclaimer, ErrorState, LoadingRows, PageHeader } from "@/components/app/states";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, download } from "@/lib/api";
import { title, when } from "@/lib/app/format";
import { useApi } from "@/lib/app/use-api";

type Report = { id: string; kind: string; event_id: string | null; status: string; created_at: string; formats: string[] };

export default function Reports() {
  const toast = useToast();
  const res = useApi<{ items: Report[] }>("/reports?limit=100");
  const [busy, setBusy] = useState(false);
  async function portfolio() {
    setBusy(true);
    try {
      await api("/reports/portfolio", { method: "POST" });
      toast("The portfolio report was created.");
      res.reload();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "The report could not be created.", "error");
    } finally {
      setBusy(false);
    }
  }
  if (res.error) return <ErrorState error={res.error} onRetry={res.reload} />;
  return (
    <>
      <PageHeader
        title="Reports"
        description="Portfolio exposure reports and incident reports. Create an incident report from the incident page."
        actions={<Button size="sm" disabled={busy} onClick={() => void portfolio()}>{busy ? "Creating" : "Create portfolio report"}</Button>}
      />
      {res.loading && !res.data ? <LoadingRows rows={4} /> : (
        <DataTable
          rows={res.data?.items ?? []}
          rowKey={(r) => r.id}
          caption="Reports"
          exportName="reports"
          empty={{ title: "No reports yet", body: "Create a portfolio report now, or an incident report from an incident page." }}
          columns={[
            { key: "k", header: "Type", cell: (r) => title(r.kind), value: (r) => r.kind },
            { key: "s", header: "Status", cell: (r) => r.status, value: (r) => r.status },
            { key: "c", header: "Created", cell: (r) => when(r.created_at), value: (r) => r.created_at },
            { key: "d", header: "Download", cell: (r) => (
              <span className="flex gap-1">{r.formats.map((f) => <Button key={f} size="sm" variant="ghost" aria-label={`Download ${title(r.kind)} report as ${f.toUpperCase()}`} onClick={() => void download(`/reports/${r.id}?format=${f}`, `report-${r.id.slice(0, 8)}.${f}`).catch(() => toast("The file could not be downloaded.", "error"))}>{f.toUpperCase()}</Button>)}</span>
            ) },
          ]}
        />
      )}
      <div className="mt-4"><Disclaimer /></div>
    </>
  );
}
