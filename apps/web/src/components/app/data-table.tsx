"use client";

import { ArrowDown, ArrowUp, Download } from "lucide-react";
import { type ReactNode, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/misc";
import { cn } from "@/lib/utils";
import { saveText, toCsv } from "@/lib/app/csv";

export type Column<T> = {
  key: string;
  header: string;
  cell: (row: T) => ReactNode;
  /** Plain value for sorting and CSV export. */
  value?: (row: T) => string | number | null | undefined;
  align?: "right";
  className?: string;
};

type Props<T> = {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string;
  caption: string;
  exportName?: string;
  onRowClick?: (row: T) => void;
  selected?: Set<string>;
  onSelect?: (next: Set<string>) => void;
  empty?: { title: string; body: string };
  rowClass?: (row: T) => string | undefined;
  activeKey?: string | null;
};

/** Sortable table with optional selection and CSV export. Rows open on click and on Enter. */
export function DataTable<T>({
  rows,
  columns,
  rowKey,
  caption,
  exportName,
  onRowClick,
  selected,
  onSelect,
  empty,
  rowClass,
  activeKey,
}: Props<T>) {
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);
  const sorted = useMemo(() => {
    const col = columns.find((c) => c.key === sort?.key);
    if (!sort || !col?.value) return rows;
    const get = col.value;
    return [...rows].sort((a, b) => {
      const x = get(a) ?? "";
      const y = get(b) ?? "";
      return (
        (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y))) *
        sort.dir
      );
    });
  }, [rows, columns, sort]);

  if (!rows.length && empty) return <EmptyState title={empty.title}>{empty.body}</EmptyState>;

  const exportCsv = () => {
    const cols = columns.filter((c) => c.value);
    saveText(
      `${exportName ?? "export"}.csv`,
      toCsv(
        cols.map((c) => c.header),
        sorted.map((r) => cols.map((c) => c.value?.(r))),
      ),
    );
  };
  const allSelected = !!selected && rows.length > 0 && rows.every((r) => selected.has(rowKey(r)));

  return (
    <div>
      {exportName ? (
        <div className="mb-2 flex justify-end">
          <Button size="sm" variant="ghost" onClick={exportCsv}>
            <Download className="size-4" aria-hidden="true" /> Export CSV
          </Button>
        </div>
      ) : null}
      <div
        className="overflow-x-auto rounded-card border border-line bg-white"
        tabIndex={0}
        role="region"
        aria-label={caption}
      >
        <table className="w-full min-w-[640px] border-collapse text-small">
          <caption className="sr-only">{caption}</caption>
          <thead className="bg-slate-50 text-left text-caption uppercase tracking-wide text-slate-600">
            <tr>
              {onSelect ? (
                <th scope="col" className="w-10 px-3 py-2">
                  <input
                    type="checkbox"
                    aria-label="Select all rows"
                    checked={allSelected}
                    onChange={() => onSelect(allSelected ? new Set() : new Set(rows.map(rowKey)))}
                  />
                </th>
              ) : null}
              {columns.map((c) => (
                <th
                  key={c.key}
                  scope="col"
                  aria-sort={sort?.key === c.key ? (sort.dir === 1 ? "ascending" : "descending") : undefined}
                  className={cn("px-3 py-2 font-medium", c.align === "right" && "text-right", c.className)}
                >
                  {c.value ? (
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 uppercase tracking-wide hover:text-ink"
                      onClick={() =>
                        setSort((s) =>
                          s?.key === c.key
                            ? { key: c.key, dir: s.dir === 1 ? -1 : 1 }
                            : { key: c.key, dir: 1 },
                        )
                      }
                    >
                      {c.header}
                      {sort?.key === c.key ? (
                        sort.dir === 1 ? (
                          <ArrowUp className="size-3" aria-hidden="true" />
                        ) : (
                          <ArrowDown className="size-3" aria-hidden="true" />
                        )
                      ) : null}
                    </button>
                  ) : (
                    c.header
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((r) => {
              const id = rowKey(r);
              return (
                <tr
                  key={id}
                  data-row={id}
                  className={cn(
                    "border-t border-line",
                    onRowClick && "cursor-pointer hover:bg-slate-50",
                    activeKey === id && "bg-brand-100",
                    rowClass?.(r),
                  )}
                  onClick={onRowClick ? () => onRowClick(r) : undefined}
                >
                  {onSelect ? (
                    <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        aria-label={`Select row ${id}`}
                        checked={selected?.has(id) ?? false}
                        onChange={() => {
                          const next = new Set(selected);
                          if (next.has(id)) next.delete(id);
                          else next.add(id);
                          onSelect(next);
                        }}
                      />
                    </td>
                  ) : null}
                  {columns.map((c, i) => (
                    <td
                      key={c.key}
                      className={cn(
                        "px-3 py-2 align-top",
                        c.align === "right" && "text-right tabular-nums",
                        c.className,
                      )}
                    >
                      {onRowClick && i === 0 ? (
                        <button
                          type="button"
                          className="text-left font-medium text-ink hover:text-brand-600"
                          onClick={(e) => {
                            e.stopPropagation();
                            onRowClick(r);
                          }}
                        >
                          {c.cell(r)}
                        </button>
                      ) : (
                        c.cell(r)
                      )}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
