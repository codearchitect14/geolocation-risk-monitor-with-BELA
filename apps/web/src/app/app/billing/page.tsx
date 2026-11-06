"use client";

import { useState } from "react";
import { DataTable } from "@/components/app/data-table";
import {
  DemoBadge,
  Disclaimer,
  ErrorState,
  LoadingRows,
  PageHeader,
  StatusChip,
} from "@/components/app/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { plans } from "@/content/site";
import { num, usd } from "@/lib/app/format";
import { useApi } from "@/lib/app/use-api";

type Plan = {
  plan: {
    id: string;
    name: string;
    billing_cycle: string;
    price: number;
    since: string;
    asset_limit: number;
    assets_in_use: number;
  } | null;
};
type Invoice = {
  id: string;
  period_start: string;
  period_end: string;
  status: string;
  total: number;
  issued_at: string;
  due_at: string;
  paid_at: string | null;
};

export default function Billing() {
  const plan = useApi<Plan>("/billing/plan");
  const invoices = useApi<{ items: Invoice[] }>("/billing/invoices?limit=36");
  const [view, setView] = useState<Invoice | null>(null);
  if (plan.error) return <ErrorState error={plan.error} onRetry={plan.reload} />;
  const p = plan.data?.plan;
  const pctUsed = p ? Math.min(100, Math.round((p.assets_in_use / p.asset_limit) * 100)) : 0;
  return (
    <>
      <PageHeader
        title="Billing"
        description="Your plan, usage against its limit, and invoices. No payment is collected in this environment."
        badge={<DemoBadge label="Demo data, synthetic" />}
      />
      {plan.loading && !plan.data ? (
        <LoadingRows rows={3} />
      ) : p ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <h2 className="text-h4 text-ink">Current plan</h2>
            <p className="mt-2 text-h3 text-ink">
              {p.name}{" "}
              <span className="text-body text-slate-600">
                {usd(p.price)} per {p.billing_cycle === "annual" ? "year" : "month"}
              </span>
            </p>
            <p className="text-caption text-slate-600">Since {p.since}</p>
          </Card>
          <Card>
            <h2 className="text-h4 text-ink">Monitored assets</h2>
            <div
              className="mt-3"
              role="meter"
              aria-valuemin={0}
              aria-valuemax={p.asset_limit}
              aria-valuenow={p.assets_in_use}
              aria-label="Monitored assets against the plan limit"
            >
              <div className="h-3 overflow-hidden rounded-full bg-slate-100">
                <div
                  className={`h-full ${pctUsed > 90 ? "bg-danger" : "bg-brand-500"}`}
                  style={{ width: `${pctUsed}%` }}
                />
              </div>
              <p className="mt-2 text-small text-slate-700">
                {num(p.assets_in_use)} of {num(p.asset_limit)} ({pctUsed}%).{" "}
                {p.assets_in_use > p.asset_limit ? "Over the limit: usage overage applies." : ""}
              </p>
            </div>
          </Card>
        </div>
      ) : (
        <Card>
          <p className="text-small text-slate-600">
            This organisation has no subscription in the demonstration data.
          </p>
        </Card>
      )}

      <h2 className="mb-2 mt-6 text-h4 text-ink">Invoices</h2>
      <DataTable
        rows={invoices.data?.items ?? []}
        rowKey={(i) => i.id}
        caption="Invoices"
        exportName="invoices"
        empty={{ title: "No invoices", body: "Invoices appear here once a subscription has been billed." }}
        columns={[
          {
            key: "p",
            header: "Period",
            cell: (i) => `${i.period_start} to ${i.period_end}`,
            value: (i) => i.period_start,
          },
          {
            key: "s",
            header: "Status",
            cell: (i) => <StatusChip status={i.status} />,
            value: (i) => i.status,
          },
          { key: "t", header: "Total", cell: (i) => usd(i.total), value: (i) => i.total, align: "right" },
          { key: "d", header: "Due", cell: (i) => i.due_at?.slice(0, 10), value: (i) => i.due_at },
          {
            key: "a",
            header: "",
            cell: (i) => (
              <Button size="sm" variant="ghost" onClick={() => setView(i)}>
                View and print
              </Button>
            ),
          },
        ]}
      />

      <h2 className="mb-2 mt-6 text-h4 text-ink">Plans</h2>
      <div
        className="overflow-x-auto rounded-card border border-line bg-white"
        tabIndex={0}
        role="region"
        aria-label="Plan comparison"
      >
        <table className="w-full text-small">
          <caption className="sr-only">Plan comparison</caption>
          <thead className="bg-slate-50 text-left text-caption text-slate-600">
            <tr>
              <th scope="col" className="px-3 py-2">
                Plan
              </th>
              <th scope="col">Per month</th>
              <th scope="col">Assets included</th>
              <th scope="col">Overage</th>
            </tr>
          </thead>
          <tbody>
            {plans.map((pl) => (
              <tr key={pl.id} className="border-t border-line">
                <th scope="row" className="px-3 py-2 text-left font-medium text-ink">
                  {pl.name} {p?.id === pl.id ? <Badge tone="brand">Current</Badge> : null}
                </th>
                <td>{usd(pl.price)}</td>
                <td>{num(pl.assets)}</td>
                <td>
                  {usd(pl.overagePrice)} per {pl.overageUnit} assets
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-caption text-slate-600">
        To change plan, contact your account manager. Plan changes are not self service in this environment.
      </p>

      <Dialog open={!!view} onOpenChange={(o) => !o && setView(null)}>
        <DialogContent>
          <DialogTitle className="text-h4 text-ink">Invoice</DialogTitle>
          <DialogDescription className="text-small text-slate-600">
            Synthetic invoice for demonstration. Use Print, then Save as PDF.
          </DialogDescription>
          {view ? (
            <dl className="mt-4 grid grid-cols-2 gap-2 text-small">
              <dt>Period</dt>
              <dd>
                {view.period_start} to {view.period_end}
              </dd>
              <dt>Issued</dt>
              <dd>{view.issued_at?.slice(0, 10)}</dd>
              <dt>Due</dt>
              <dd>{view.due_at?.slice(0, 10)}</dd>
              <dt>Status</dt>
              <dd>{view.status}</dd>
              <dt className="font-medium">Total</dt>
              <dd className="font-medium">{usd(view.total)}</dd>
            </dl>
          ) : null}
          <Button className="mt-4" onClick={() => window.print()}>
            Print
          </Button>
        </DialogContent>
      </Dialog>
      <div className="mt-6">
        <Disclaimer />
      </div>
    </>
  );
}
