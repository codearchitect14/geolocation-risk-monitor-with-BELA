"use client";

import { Bell } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { ago } from "@/lib/app/format";
import { LevelChip } from "./states";

type Note = {
  id: string;
  level: string;
  title: string;
  asset: string;
  kind: string;
  at: string;
  alertId?: string;
};

/** Live alerts from the server-sent event stream. The bell shows how many arrived since it was last opened. */
export function Notifications() {
  const [notes, setNotes] = useState<Note[]>([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const toast = useToast();
  const openRef = useRef(open);
  openRef.current = open;

  useEffect(() => {
    const es = new EventSource("/api/v1/stream/alerts", { withCredentials: true });
    es.addEventListener("update", (e) => {
      try {
        const d = JSON.parse((e as MessageEvent<string>).data) as {
          id?: string;
          alert_id?: string;
          level?: string;
          kind?: string;
          event?: { title?: string };
          asset?: { name?: string };
        };
        const note: Note = {
          id: `${d.id ?? d.alert_id ?? Math.random()}-${Date.now()}`,
          alertId: d.id ?? d.alert_id,
          level: d.level ?? "medium",
          kind: d.kind ?? "alert.created",
          title: d.event?.title ?? "Alert update",
          asset: d.asset?.name ?? "an asset",
          at: new Date().toISOString(),
        };
        setNotes((n) => [note, ...n].slice(0, 20));
        if (!openRef.current) setUnread((u) => u + 1);
        if (note.kind === "alert.created") toast(`New ${note.level} alert for ${note.asset}`);
      } catch {
        /* a malformed message is skipped */
      }
    });
    return () => es.close();
  }, [toast]);

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (o) setUnread(0);
      }}
    >
      <DialogTrigger
        className="relative rounded-control p-2 text-slate-700 hover:bg-slate-100"
        aria-label={unread ? `Notifications, ${unread} new` : "Notifications"}
      >
        <Bell className="size-5" aria-hidden="true" />
        {unread ? (
          <span className="absolute -right-0.5 -top-0.5 grid min-w-4 place-items-center rounded-full bg-danger px-1 text-[10px] font-semibold text-white">
            {unread}
          </span>
        ) : null}
      </DialogTrigger>
      <DialogContent side="right">
        <DialogTitle className="text-h4 text-ink">Notifications</DialogTitle>
        <DialogDescription className="text-small text-slate-600">
          Live alert changes for your organisation since you opened this page.
        </DialogDescription>
        {notes.length === 0 ? (
          <p className="mt-6 text-small text-slate-600">
            Nothing new. Alerts appear here as they are raised.
          </p>
        ) : (
          <ul className="mt-4 space-y-3">
            {notes.map((n) => (
              <li key={n.id} className="rounded-control border border-line p-3 text-small">
                <div className="flex items-center justify-between gap-2">
                  <LevelChip level={n.level} />
                  <span className="text-caption text-slate-600">{ago(n.at)}</span>
                </div>
                <p className="mt-1 text-ink">{n.title}</p>
                <p className="text-caption text-slate-600">{n.asset}</p>
                <Link
                  href="/app/alerts"
                  onClick={() => setOpen(false)}
                  className="text-caption font-medium text-brand-600 underline"
                >
                  Open alerts
                </Link>
              </li>
            ))}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  );
}
