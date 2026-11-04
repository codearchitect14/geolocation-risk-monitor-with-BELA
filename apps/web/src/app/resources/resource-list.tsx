"use client";

import Link from "next/link";
import { useState } from "react";
import { Picture } from "@/components/picture";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { ArticleMeta } from "@/lib/articles";

const fmt = (iso: string) =>
  new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${iso}T00:00:00Z`));

export function ResourceList({ articles, tags }: { articles: ArticleMeta[]; tags: string[] }) {
  const [tag, setTag] = useState<string | null>(null);
  const shown = tag ? articles.filter((a) => a.tags.includes(tag)) : articles;
  return (
    <div>
      <div role="group" aria-label="Filter by tag" className="mb-8 flex flex-wrap gap-2">
        {[null, ...tags].map((t) => (
          <button
            key={t ?? "all"}
            type="button"
            aria-pressed={tag === t}
            onClick={() => setTag(t)}
            className={cn(
              "rounded-full border px-4 py-1.5 text-small font-medium transition-colors",
              tag === t
                ? "border-ink bg-ink text-white"
                : "border-slate-300 bg-white text-slate-700 hover:border-brand-500",
            )}
          >
            {t ?? "All"}
          </button>
        ))}
      </div>
      <p className="sr-only" role="status">
        {shown.length} articles shown
      </p>
      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        {shown.map((a) => (
          <Link
            key={a.slug}
            href={`/resources/${a.slug}`}
            className="group block focus-visible:outline-offset-4"
          >
            <Card hover className="h-full overflow-hidden !p-0">
              <Picture
                name={a.image}
                alt=""
                sizes="(min-width: 1024px) 360px, (min-width: 768px) 50vw, 100vw"
                className="aspect-[16/9] w-full object-cover"
              />
              <div className="p-5">
                <p className="text-caption text-slate-600">
                  {fmt(a.date)} · {a.minutes} min read
                </p>
                <h2 className="mt-1 text-h4 group-hover:text-brand-600">{a.title}</h2>
                <p className="mt-2 text-small text-slate-700">{a.summary}</p>
                <p className="mt-3 flex flex-wrap gap-2">
                  {a.tags.map((t) => (
                    <span
                      key={t}
                      className="rounded-full bg-slate-100 px-2.5 py-0.5 text-caption text-slate-700"
                    >
                      {t}
                    </span>
                  ))}
                </p>
              </div>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
