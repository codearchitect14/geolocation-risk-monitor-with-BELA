import { ChevronRight } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { cn } from "@/lib/utils";

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cn("animate-pulse rounded-md bg-slate-200", className)} />;
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="rounded-card border border-dashed border-slate-300 bg-white p-10 text-center">
      <h3 className="text-h4">{title}</h3>
      {children ? <p className="mx-auto mt-2 max-w-md text-slate-600">{children}</p> : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

export function Breadcrumbs({ items }: { items: { label: string; href?: string }[] }) {
  return (
    <nav aria-label="Breadcrumb" className="text-small text-slate-600">
      <ol className="flex flex-wrap items-center gap-1.5">
        {items.map((item, i) => (
          <li key={item.label} className="flex items-center gap-1.5">
            {i > 0 && <ChevronRight className="size-3.5" aria-hidden="true" />}
            {item.href ? (
              <Link href={item.href} className="hover:text-brand-600 hover:underline">
                {item.label}
              </Link>
            ) : (
              <span aria-current="page" className="text-ink">
                {item.label}
              </span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}

export function Stepper({ steps }: { steps: { title: string; body: string; visual?: React.ReactNode }[] }) {
  return (
    <ol className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
      {steps.map((step, i) => (
        <li key={step.title} className="relative rounded-card border border-line bg-white p-6 shadow-e1">
          <span className="mb-4 inline-flex size-9 items-center justify-center rounded-full bg-ink text-small font-semibold text-white tabular">
            {i + 1}
          </span>
          {step.visual ? (
            <div className="mb-4" aria-hidden="true">
              {step.visual}
            </div>
          ) : null}
          <h3 className="text-h4">{step.title}</h3>
          <p className="mt-2 text-slate-700">{step.body}</p>
        </li>
      ))}
    </ol>
  );
}

export function Timeline({ items }: { items: { title: string; body: string; meta?: string }[] }) {
  return (
    <ol className="relative space-y-6 border-l border-line pl-6">
      {items.map((item) => (
        <li key={item.title} className="relative">
          <span
            className="absolute -left-[31px] top-1.5 size-2.5 rounded-full bg-brand-500 ring-4 ring-page"
            aria-hidden="true"
          />
          {item.meta ? <p className="text-caption text-slate-600 tabular">{item.meta}</p> : null}
          <p className="font-medium text-ink">{item.title}</p>
          <p className="text-slate-700">{item.body}</p>
        </li>
      ))}
    </ol>
  );
}
