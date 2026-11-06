"use client";

import { DataTable } from "@/components/app/data-table";
import { Disclaimer, ErrorState, LoadingRows, PageHeader, StatusChip } from "@/components/app/states";
import { ago, num, when } from "@/lib/app/format";
import { useApi } from "@/lib/app/use-api";

type Source = {
  kind: string;
  name: string;
  license_note: string;
  last_record_at: string | null;
  records_total: number;
  records_24h: number;
  freshness: string;
  feed: {
    state: string;
    consecutive_failures: number;
    last_success: string | null;
    last_error: string | null;
  };
};
type Pipeline = {
  model_server: string;
  entity_linker: string;
  reduced_confidence_events_7d: number;
  dead_letters: { queued: number; abandoned: number };
  note: string;
};
const COVERAGE: Record<string, string> = {
  usgs: "Global earthquakes. Automated magnitudes; small events can be revised.",
  nws: "United States only. Official alert products restated; coverage ends at US borders.",
  firms: "Global satellite fire detections. Needs a map key; detections are not confirmed fires.",
  reliefweb: "Humanitarian disasters at country level; no precise coordinates.",
  news: "Public news in several languages. Locations are inferred from text and can be uncertain.",
};

export default function Sources() {
  const res = useApi<{ items: Source[]; pipeline: Pipeline }>("/sources");
  const p = res.data?.pipeline;
  if (res.error) return <ErrorState error={res.error} onRetry={res.reload} />;
  return (
    <>
      <PageHeader
        title="Data sources"
        description="Where incidents come from, how fresh each feed is, and the terms each source is used under."
      />
      {p ? (
        <section aria-labelledby="pipeline-h" className="mb-6 rounded-card border border-line bg-white p-4">
          <h2 id="pipeline-h" className="text-h4 font-semibold">
            Processing components
          </h2>
          <dl className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <dt className="text-caption text-slate-600">Language model server</dt>
              <dd className="mt-1">
                <StatusChip status={p.model_server} />
              </dd>
            </div>
            <div>
              <dt className="text-caption text-slate-600">Entity linker</dt>
              <dd className="mt-1">
                <StatusChip status={p.entity_linker} />
              </dd>
            </div>
            <div>
              <dt className="text-caption text-slate-600">Reduced confidence incidents, 7 days</dt>
              <dd className="mt-1 text-body font-medium">{num(p.reduced_confidence_events_7d)}</dd>
            </div>
            <div>
              <dt className="text-caption text-slate-600">Articles waiting for retry / given up</dt>
              <dd className="mt-1 text-body font-medium">
                {num(p.dead_letters.queued)} / {num(p.dead_letters.abandoned)}
              </dd>
            </div>
          </dl>
          <p className="mt-3 text-caption text-slate-600">{p.note}</p>
        </section>
      ) : null}
      {res.loading && !res.data ? (
        <LoadingRows rows={5} />
      ) : (
        <DataTable
          rows={res.data?.items ?? []}
          rowKey={(s) => s.kind}
          caption="Data sources"
          exportName="data-sources"
          columns={[
            { key: "n", header: "Source", cell: (s) => s.name, value: (s) => s.name },
            {
              key: "f",
              header: "Freshness",
              cell: (s) => <StatusChip status={s.freshness} />,
              value: (s) => s.freshness,
            },
            {
              key: "fd",
              header: "Feed job",
              cell: (s) => (
                <span title={s.feed.last_error ?? undefined}>
                  <StatusChip status={s.feed.state} />
                </span>
              ),
              value: (s) => s.feed.state,
            },
            {
              key: "l",
              header: "Last record",
              cell: (s) =>
                s.last_record_at ? `${when(s.last_record_at)} (${ago(s.last_record_at)})` : "none",
              value: (s) => s.last_record_at,
            },
            {
              key: "t",
              header: "Records",
              cell: (s) => num(s.records_total),
              value: (s) => s.records_total,
              align: "right",
            },
            {
              key: "d",
              header: "Last 24 h",
              cell: (s) => num(s.records_24h),
              value: (s) => s.records_24h,
              align: "right",
            },
            { key: "c", header: "Coverage", cell: (s) => COVERAGE[s.kind] ?? "", className: "max-w-xs" },
            {
              key: "li",
              header: "License note",
              cell: (s) => s.license_note,
              value: (s) => s.license_note,
              className: "max-w-xs",
            },
          ]}
        />
      )}
      <p className="mt-3 text-caption text-slate-600">
        Stale means no new record within the usual interval of the feed. No data means the feed has not been
        configured or has produced nothing yet.
      </p>
      <div className="mt-4">
        <Disclaimer />
      </div>
    </>
  );
}
