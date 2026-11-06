"use client";

import { Bookmark, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";

type View = { name: string; state: Record<string, string> };

/** Named filter sets kept in this browser. They are a convenience and are never sent to the server. */
export function SavedViews({
  storageKey,
  state,
  onApply,
}: {
  storageKey: string;
  state: Record<string, string>;
  onApply: (state: Record<string, string>) => void;
}) {
  const [views, setViews] = useState<View[]>([]);
  const [selected, setSelected] = useState("");
  const toast = useToast();
  useEffect(() => {
    try {
      setViews(JSON.parse(localStorage.getItem(`ms_views_${storageKey}`) ?? "[]") as View[]);
    } catch {
      setViews([]);
    }
  }, [storageKey]);
  const persist = (next: View[]) => {
    setViews(next);
    try {
      localStorage.setItem(`ms_views_${storageKey}`, JSON.stringify(next));
    } catch {
      toast("Saved views are unavailable in this browser.", "error");
    }
  };
  return (
    <div className="flex flex-wrap items-center gap-2">
      <label className="sr-only" htmlFor={`sv-${storageKey}`}>
        Saved views
      </label>
      <Select
        id={`sv-${storageKey}`}
        className="h-9 w-44 text-small"
        value={selected}
        onChange={(e) => {
          setSelected(e.target.value);
          const v = views.find((x) => x.name === e.target.value);
          if (v) onApply(v.state);
        }}
      >
        <option value="">Saved views</option>
        {views.map((v) => (
          <option key={v.name} value={v.name}>
            {v.name}
          </option>
        ))}
      </Select>
      <Button
        size="sm"
        variant="ghost"
        onClick={() => {
          const name = window.prompt("Name for this view");
          if (!name?.trim()) return;
          persist([...views.filter((v) => v.name !== name.trim()), { name: name.trim(), state }]);
          setSelected(name.trim());
        }}
      >
        <Bookmark className="size-4" aria-hidden="true" /> Save view
      </Button>
      {selected ? (
        <Button
          size="sm"
          variant="ghost"
          aria-label={`Delete saved view ${selected}`}
          onClick={() => {
            if (!window.confirm(`Delete the saved view "${selected}"?`)) return;
            persist(views.filter((v) => v.name !== selected));
            setSelected("");
          }}
        >
          <Trash2 className="size-4" aria-hidden="true" />
        </Button>
      ) : null}
    </div>
  );
}
