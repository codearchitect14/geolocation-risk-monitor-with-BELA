import raw from "./metrics.json";

export type Metrics = {
  generated_at: string;
  evaluation: string;
  places_indexed: number;
  median_error_km: number;
  acc_161km: number;
  acc_161km_ambiguous: number;
  acc_161km_best_gazetteer_baseline_ambiguous: number;
  system: string;
};

/** Evaluation figures produced by `make eval` and copied from public/metrics.json at build time. */
export const metrics: Metrics = raw as Metrics;

export const pct = (value: number, digits = 1): string => `${(value * 100).toFixed(digits)}%`;
export const points = (a: number, b: number): string => `${((a - b) * 100).toFixed(1)} points`;
export const formatInt = (n: number): string => new Intl.NumberFormat("en-US").format(n);

export type PublicStats = {
  places_indexed: number;
  places_with_wikidata: number;
  incidents_30d: number;
  event_sources_30d: Record<string, number>;
};

/** Live counts from the API at build or revalidation time. Returns null when the API is not reachable. */
export async function loadPublicStats(): Promise<PublicStats | null> {
  const origin = process.env.MS_API_URL ?? "http://127.0.0.1:8090";
  try {
    const res = await fetch(`${origin}/api/v1/public/stats`, {
      next: { revalidate: 300 },
      signal: AbortSignal.timeout(3000),
    });
    return res.ok ? ((await res.json()) as PublicStats) : null;
  } catch {
    return null;
  }
}
