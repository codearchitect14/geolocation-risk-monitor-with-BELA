"use client";

import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { api } from "@/lib/api";
import { atLeast, useSession } from "@/lib/app/session";
import { NAV_GROUPS } from "./nav";

type Hit = { id: string; label: string; group: string; href: string };

/** Ctrl+K or Cmd+K. Searches pages, assets, incidents and places. */
export function CommandPalette({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const { me } = useSession();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [remote, setRemote] = useState<Hit[]>([]);
  const [cursor, setCursor] = useState(0);

  const pages = useMemo<Hit[]>(
    () =>
      NAV_GROUPS.flatMap((g) => g.items)
        .filter((i) => i.allow(me.role))
        .map((i) => ({ id: i.href, label: i.label, group: "Pages", href: i.href })),
    [me.role],
  );

  useEffect(() => {
    if (!open) return;
    setQ("");
    setRemote([]);
  }, [open]);

  useEffect(() => {
    const term = q.trim();
    if (term.length < 2 || !atLeast(me.role, "viewer")) return setRemote([]);
    const timer = window.setTimeout(async () => {
      const enc = encodeURIComponent(term);
      const [assets, events, places] = await Promise.allSettled([
        api<{ items: { id: string; name: string }[] }>(`/assets?q=${enc}&limit=5`),
        api<{ items: { id: string; title: string }[] }>(`/events?limit=100`),
        api<{ items: { id: string; name: string; country_code?: string }[] }>(
          `/places/search?q=${enc}&limit=5`,
        ),
      ]);
      const out: Hit[] = [];
      if (assets.status === "fulfilled")
        out.push(
          ...assets.value.items.map((a) => ({
            id: a.id,
            label: a.name,
            group: "Assets",
            href: `/app/assets/${a.id}`,
          })),
        );
      if (events.status === "fulfilled")
        out.push(
          ...events.value.items
            .filter((e) => e.title.toLowerCase().includes(term.toLowerCase()))
            .slice(0, 5)
            .map((e) => ({ id: e.id, label: e.title, group: "Incidents", href: `/app/incidents/${e.id}` })),
        );
      if (places.status === "fulfilled")
        out.push(
          ...places.value.items.map((p) => ({
            id: p.id,
            label: `${p.name}${p.country_code ? `, ${p.country_code}` : ""}`,
            group: "Places",
            href: `/app/map?q=${encodeURIComponent(p.name)}`,
          })),
        );
      setRemote(out);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [q, me.role]);

  const hits = useMemo(() => {
    const t = q.trim().toLowerCase();
    return [...pages.filter((p) => !t || p.label.toLowerCase().includes(t)), ...remote];
  }, [pages, remote, q]);
  useEffect(() => setCursor(0), [hits.length]);

  const go = (h: Hit) => {
    onOpenChange(false);
    router.push(h.href);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="top-[20%] max-w-xl -translate-y-0 p-0">
        <DialogTitle className="sr-only">Search</DialogTitle>
        <DialogDescription className="sr-only">Search pages, assets, incidents and places.</DialogDescription>
        <div className="flex items-center gap-2 border-b border-line px-4">
          <Search className="size-4 text-slate-500" aria-hidden="true" />
          <input
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            aria-label="Search pages, assets, incidents and places"
            placeholder="Search assets, incidents, places"
            className="h-12 w-full bg-transparent text-body text-ink outline-none"
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") setCursor((c) => Math.min(c + 1, hits.length - 1));
              else if (e.key === "ArrowUp") setCursor((c) => Math.max(c - 1, 0));
              else if (e.key === "Enter" && hits[cursor]) go(hits[cursor]);
              else return;
              e.preventDefault();
            }}
          />
        </div>
        <ul role="listbox" aria-label="Results" className="max-h-80 overflow-y-auto p-2">
          {hits.length === 0 ? (
            <li className="px-3 py-6 text-center text-small text-slate-600">No matches</li>
          ) : null}
          {hits.map((h, i) => (
            <li
              key={`${h.group}-${h.id}`}
              role="option"
              aria-selected={i === cursor}
              onClick={() => go(h)}
              onMouseEnter={() => setCursor(i)}
              className={`flex cursor-pointer items-center justify-between gap-3 rounded-control px-3 py-2 text-small ${i === cursor ? "bg-brand-100 text-ink" : "text-slate-700"}`}
            >
              <span className="truncate">{h.label}</span>
              <span className="shrink-0 text-caption text-slate-500">{h.group}</span>
            </li>
          ))}
        </ul>
      </DialogContent>
    </Dialog>
  );
}
