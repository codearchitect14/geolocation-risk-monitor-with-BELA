"use client";

import {
  BarChart,
  BoxplotChart,
  CustomChart,
  HeatmapChart,
  LineChart,
  MapChart,
  PieChart,
  SankeyChart,
} from "echarts/charts";
import {
  AriaComponent,
  DatasetComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TitleComponent,
  TooltipComponent,
  VisualMapComponent,
  MarkAreaComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { Download, Image as ImageIcon, Table2 } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { EmptyState, Skeleton } from "@/components/ui/misc";
import { cn } from "@/lib/utils";
import { saveText, toCsv } from "@/lib/app/csv";
import { ErrorState } from "./states";
import { useTheme } from "./theme";

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  HeatmapChart,
  SankeyChart,
  BoxplotChart,
  CustomChart,
  MapChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  DatasetComponent,
  VisualMapComponent,
  MarkLineComponent,
  MarkAreaComponent,
  AriaComponent,
  CanvasRenderer,
]);

/** Color-blind safe palette from the design tokens. */
export const CHART = ["#2F74D8", "#00A3A3", "#E69F00", "#8E5BD9", "#D55E5E", "#6C7A89"];

export type ChartTable = { headers: string[]; rows: (string | number | null)[][] };

type Props = {
  title: string;
  description?: string;
  option: echarts.EChartsCoreOption | null;
  table: ChartTable;
  height?: number;
  loading?: boolean;
  error?: Error;
  onRetry?: () => void;
  empty?: string;
  actions?: React.ReactNode;
  badge?: React.ReactNode;
  onClickPoint?: (params: { name?: string; seriesName?: string; value?: unknown }) => void;
  className?: string;
};

/** Shared chart wrapper: title, ECharts canvas, a keyboard reachable data table, PNG and CSV export, and all states. */
export function ChartCard({
  title,
  description,
  option,
  table,
  height = 280,
  loading,
  error,
  onRetry,
  empty,
  actions,
  badge,
  onClickPoint,
  className,
}: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const [view, setView] = useState<"chart" | "table">("chart");
  const { theme } = useTheme();
  const id = useId();
  const hasData = table.rows.length > 0;

  useEffect(() => {
    if (view !== "chart" || !ref.current || !option || !hasData) return;
    const text = theme === "dark" ? "#C9D2E2" : "#475569";
    const grid = theme === "dark" ? "#243252" : "#E7ECF3";
    chart.current?.dispose();
    const c = echarts.init(ref.current, undefined, { renderer: "canvas" });
    chart.current = c;
    c.setOption({
      color: CHART,
      textStyle: { fontFamily: "Inter Variable, Inter, sans-serif", color: text },
      aria: { enabled: true },
      animationDuration: 250,
      tooltip: {
        trigger: "axis",
        confine: true,
        backgroundColor: theme === "dark" ? "#152038" : "#fff",
        borderColor: grid,
        textStyle: { color: text },
      },
      ...option,
    } as echarts.EChartsCoreOption);
    if (onClickPoint) c.on("click", (p) => onClickPoint(p as never));
    const ro = new ResizeObserver(() => c.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      c.dispose();
      chart.current = null;
    };
  }, [option, view, theme, hasData, onClickPoint]);

  const exportPng = () => {
    const url = chart.current?.getDataURL({
      type: "png",
      pixelRatio: 2,
      backgroundColor: theme === "dark" ? "#152038" : "#fff",
    });
    if (!url) return;
    const a = document.createElement("a");
    a.href = url;
    a.download = `${title.toLowerCase().replace(/\W+/g, "-")}.png`;
    a.click();
  };

  return (
    <section
      aria-labelledby={id}
      className={cn("rounded-card border border-line bg-white p-4 shadow-e1", className)}
    >
      <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 id={id} className="flex flex-wrap items-center gap-2 text-h4 text-ink">
            {title} {badge}
          </h2>
          {description ? <p className="text-caption text-slate-600">{description}</p> : null}
        </div>
        <div className="flex flex-wrap items-center gap-1">
          {actions}
          {hasData ? (
            <>
              <Button
                size="sm"
                variant="ghost"
                aria-pressed={view === "table"}
                onClick={() => setView(view === "chart" ? "table" : "chart")}
              >
                <Table2 className="size-4" aria-hidden="true" /> {view === "chart" ? "Table" : "Chart"}
              </Button>
              {view === "chart" ? (
                <Button size="sm" variant="ghost" onClick={exportPng} aria-label={`Export ${title} as PNG`}>
                  <ImageIcon className="size-4" aria-hidden="true" /> PNG
                </Button>
              ) : null}
              <Button
                size="sm"
                variant="ghost"
                aria-label={`Export ${title} as CSV`}
                onClick={() =>
                  saveText(
                    `${title.toLowerCase().replace(/\W+/g, "-")}.csv`,
                    toCsv(table.headers, table.rows),
                  )
                }
              >
                <Download className="size-4" aria-hidden="true" /> CSV
              </Button>
            </>
          ) : null}
        </div>
      </div>
      {error ? (
        <ErrorState error={error} onRetry={onRetry} />
      ) : loading && !hasData ? (
        <Skeleton className="w-full" />
      ) : !hasData ? (
        <EmptyState title="No data for this selection">
          {empty ?? "Change the date range or filters."}
        </EmptyState>
      ) : view === "chart" ? (
        <div
          ref={ref}
          style={{ height }}
          className="w-full"
          role="img"
          aria-label={`${title}. Use the Table button for the values.`}
        />
      ) : (
        <div className="max-h-80 overflow-auto" tabIndex={0} role="region" aria-label={`${title} data`}>
          <table className="w-full text-small">
            <thead className="sticky top-0 bg-slate-50 text-left text-caption text-slate-600">
              <tr>
                {table.headers.map((h) => (
                  <th key={h} scope="col" className="px-2 py-1 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((r, i) => (
                <tr key={i} className="border-t border-line">
                  {r.map((v, j) => (
                    <td key={j} className="px-2 py-1 tabular-nums">
                      {v ?? "n/a"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/** Axis defaults: light gridlines, units in the axis name. */
export const axis = {
  x: (name?: string) => ({
    type: "category" as const,
    name,
    nameLocation: "middle" as const,
    nameGap: 28,
    axisLine: { lineStyle: { color: "#C3CCD9" } },
  }),
  y: (name: string) => ({
    type: "value" as const,
    name,
    nameTextStyle: { align: "left" as const },
    splitLine: { lineStyle: { color: "#E7ECF3", opacity: 0.7 } },
  }),
};
