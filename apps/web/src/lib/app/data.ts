import type { IncidentPoint } from "@/components/app/app-map";
import { api } from "@/lib/api";

export type EventItem = {
  id: string;
  type: string;
  subtype: string | null;
  severity: number;
  status: string;
  confirmation: string;
  confirmation_text: string;
  first_seen_at: string;
  last_seen_at: string;
  title: string;
  summary: string | null;
  geometry: GeoJSON.Geometry;
  uncertainty_km: number;
  location_level: string;
  location_confidence: number;
  reduced_confidence: boolean;
  source_count: number;
};

export type AlertItem = {
  id: string;
  level: string;
  status: string;
  score: number;
  assignee_id: string | null;
  dismissal_reason: string | null;
  created_at: string;
  updated_at: string;
  event: {
    id: string;
    title: string;
    type: string;
    subtype: string | null;
    severity: number;
    status: string;
    confirmation: string;
    last_seen_at: string;
  };
  /** Null for an alert raised by a watch zone, which has no asset. */
  asset: { id: string; name: string; distance_km: number } | null;
  zone_id: string | null;
};

export type AssetItem = {
  id: string;
  name: string;
  type: string;
  geometry: GeoJSON.Geometry;
  criticality: number;
  country_code: string | null;
  tags: string[];
  status: string;
  external_id: string | null;
  maintenance_windows: { start: string; end: string; reason?: string }[];
  created_at: string;
  location_source: string;
  location_uncertainty_km: number | null;
};

/** Follow cursors until `max` items are loaded. */
export async function fetchAll<T>(path: string, max = 5000): Promise<T[]> {
  const out: T[] = [];
  let cursor: string | null = null;
  do {
    const sep = path.includes("?") ? "&" : "?";
    const res: { items: T[]; next_cursor: string | null } = await api(
      `${path}${sep}limit=200${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
    );
    out.push(...res.items);
    cursor = res.next_cursor;
  } while (cursor && out.length < max);
  return out.slice(0, max);
}

/** First position of any GeoJSON geometry, as [lon, lat], or the mean for a polygon ring. */
export function centroid(g: GeoJSON.Geometry): [number, number] {
  if (g.type === "Point") return g.coordinates as [number, number];
  const pts: number[][] = [];
  const walk = (c: unknown): void => {
    if (Array.isArray(c) && typeof c[0] === "number") pts.push(c as number[]);
    else if (Array.isArray(c)) c.forEach(walk);
  };
  walk("coordinates" in g ? g.coordinates : []);
  if (!pts.length) return [0, 0];
  return [
    pts.reduce((s, p) => s + (p[0] as number), 0) / pts.length,
    pts.reduce((s, p) => s + (p[1] as number), 0) / pts.length,
  ];
}

export const levelFromSeverity = (s: number): 1 | 2 | 3 | 4 => Math.min(4, Math.max(1, s)) as 1 | 2 | 3 | 4;

export function toIncidentPoint(e: EventItem): IncidentPoint {
  const [lon, lat] = centroid(e.geometry);
  return {
    id: e.id,
    lon,
    lat,
    level: levelFromSeverity(e.severity),
    label: e.title,
    type: e.type,
    uncertaintyKm: e.uncertainty_km || undefined,
    area: e.geometry.type === "Point" ? undefined : e.geometry,
  };
}

export const EVENT_TYPES = [
  "natural_hazard",
  "conflict",
  "civil_unrest",
  "infrastructure",
  "health",
  "transport",
  "other",
];
