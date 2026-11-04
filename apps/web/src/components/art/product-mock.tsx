import { Bell, Layers, LayoutDashboard, MapPin, Search, Settings } from "lucide-react";
import { WorldMap } from "./world-map";
import { SeverityBadge } from "@/components/ui/badge";

type Tab = "map" | "exposure" | "incident" | "analytics";

const NAV = [LayoutDashboard, MapPin, Layers, Bell, Settings];

function Frame({
  children,
  label,
  url = "app.meridian-signal.example/map",
}: {
  children: React.ReactNode;
  label: string;
  url?: string;
}) {
  return (
    <figure
      className="overflow-hidden rounded-card border border-line bg-white shadow-e3"
      role="img"
      aria-label={label}
    >
      <div
        className="flex items-center gap-2 border-b border-line bg-slate-50 px-4 py-2.5"
        aria-hidden="true"
      >
        <span className="size-2.5 rounded-full bg-slate-300" />
        <span className="size-2.5 rounded-full bg-slate-300" />
        <span className="size-2.5 rounded-full bg-slate-300" />
        <span className="ml-3 flex-1 truncate rounded-md bg-white px-3 py-1 text-caption text-slate-500">
          {url}
        </span>
      </div>
      <div className="relative aspect-[16/10] bg-white" aria-hidden="true">
        {children}
      </div>
    </figure>
  );
}

function Sidebar() {
  return (
    <div className="flex w-12 shrink-0 flex-col items-center gap-4 border-r border-line bg-ink py-4 text-slate-300">
      {NAV.map((Icon, i) => (
        <Icon key={i} className={i === 1 ? "size-5 text-white" : "size-5"} />
      ))}
    </div>
  );
}

function MapPanel() {
  return (
    <div className="relative flex-1 overflow-hidden bg-[#F1F5FA]">
      <WorldMap
        view={{ x: 0, y: 40, w: 1000, h: 300 }}
        className="absolute inset-0 size-full"
        markerScale={1.6}
        land="#C9D6E8"
        stroke="#F1F5FA"
      />
      <div className="absolute left-3 top-3 flex items-center gap-2 rounded-control border border-line bg-white px-3 py-1.5 text-caption text-slate-500 shadow-e1">
        <Search className="size-3.5" />
        Search places and assets
      </div>
    </div>
  );
}

function Mock({ tab }: { tab: Tab }) {
  if (tab === "analytics") {
    const bars = [38, 52, 44, 61, 58, 73, 66, 82, 78, 91, 84, 96];
    return (
      <div className="flex size-full">
        <Sidebar />
        <div className="flex-1 space-y-4 bg-page p-5">
          <p className="text-small font-semibold text-ink">Operational analytics</p>
          <div className="grid grid-cols-3 gap-3">
            {["Incidents by type", "Alerts by level", "Acknowledgement time"].map((t) => (
              <div key={t} className="rounded-control border border-line bg-white p-3">
                <p className="text-caption text-slate-500">{t}</p>
                <div className="mt-2 h-2 w-2/3 rounded bg-brand-500" />
                <div className="mt-1.5 h-2 w-1/2 rounded bg-teal" />
              </div>
            ))}
          </div>
          <div className="rounded-control border border-line bg-white p-4">
            <p className="text-caption text-slate-500">Incidents per week</p>
            <svg viewBox="0 0 240 70" className="mt-2 h-28 w-full" preserveAspectRatio="none">
              {bars.map((b, i) => (
                <rect
                  key={i}
                  x={i * 20 + 4}
                  y={70 - b * 0.65}
                  width="13"
                  height={b * 0.65}
                  rx="2"
                  fill={i % 4 === 3 ? "#00A3A3" : "#2F74D8"}
                />
              ))}
            </svg>
          </div>
        </div>
      </div>
    );
  }
  const exposure = [
    ["Depot A", "12 km", 3],
    ["Plant B", "34 km", 2],
    ["Office C", "58 km", 1],
  ] as const;
  return (
    <div className="flex size-full">
      <Sidebar />
      <MapPanel />
      {tab !== "map" ? (
        <aside className="hidden w-[38%] shrink-0 border-l border-line bg-white p-4 sm:block">
          {tab === "incident" ? (
            <div className="space-y-3">
              <SeverityBadge level={3} />
              <p className="text-small font-semibold leading-snug text-ink">
                Flood reported along the river, two towns affected
              </p>
              <p className="text-caption text-slate-500">Located at district level, uncertainty 18 km</p>
              <div className="space-y-2 pt-2">
                {["Report, regional outlet", "Weather alert, NWS", "Report, national outlet"].map((s) => (
                  <div key={s} className="flex items-center gap-2 text-caption text-slate-700">
                    <span className="size-1.5 rounded-full bg-brand-500" />
                    {s}
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              <p className="text-small font-semibold text-ink">Exposed assets</p>
              {exposure.map(([name, d, l]) => (
                <div
                  key={name}
                  className="flex items-center justify-between rounded-control border border-line px-3 py-2 text-caption"
                >
                  <span className="font-medium text-ink">{name}</span>
                  <span className="text-slate-500">{d}</span>
                  <SeverityBadge level={l as 1 | 2 | 3} />
                </div>
              ))}
            </div>
          )}
        </aside>
      ) : null}
    </div>
  );
}

const LABELS: Record<Tab, string> = {
  map: "Illustrative rendering of the live map with located incidents",
  exposure: "Illustrative rendering of the map with a list of exposed assets",
  incident: "Illustrative rendering of an incident detail panel",
  analytics: "Illustrative rendering of the analytics page",
};

export function ProductMock({ tab = "map" }: { tab?: Tab }) {
  return (
    <Frame label={LABELS[tab]} url={`app.meridian-signal.example/${tab === "map" ? "map" : tab}`}>
      <Mock tab={tab} />
    </Frame>
  );
}

/** Floating incident card used over the hero rendering. */
export function IncidentCard() {
  return (
    <div className="rounded-card border border-line bg-white p-4 shadow-e3">
      <div className="flex items-center justify-between gap-3">
        <SeverityBadge level={3} />
        <span className="text-caption text-slate-500">Illustrative</span>
      </div>
      <p className="mt-2 text-small font-semibold text-ink">Terminal closed after storm</p>
      <p className="text-caption text-slate-600">
        Nearest asset: Depot A, 12 km. Location certainty: district level.
      </p>
    </div>
  );
}

export function ExposureList() {
  return (
    <div className="rounded-card border border-line bg-white p-4 shadow-e3">
      <p className="text-small font-semibold text-ink">Exposure</p>
      <ul className="mt-2 space-y-1.5 text-caption text-slate-700">
        {[
          ["Depot A", "12 km"],
          ["Plant B", "34 km"],
          ["Office C", "58 km"],
        ].map(([n, d]) => (
          <li key={n} className="flex justify-between gap-6">
            <span>{n}</span>
            <span className="tabular text-slate-500">{d}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
