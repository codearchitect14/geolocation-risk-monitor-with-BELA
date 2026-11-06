export const usd = (n: number | null | undefined, compact = false) =>
  n === null || n === undefined
    ? "n/a"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 0,
        notation: compact ? "compact" : "standard",
      }).format(n);

export const num = (n: number | null | undefined, digits = 0) =>
  n === null || n === undefined
    ? "n/a"
    : new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(n);

export const pct = (n: number | null | undefined, digits = 1) =>
  n === null || n === undefined ? "n/a" : `${num(n, digits)}%`;

export function when(iso: string | null | undefined): string {
  if (!iso) return "n/a";
  return new Date(iso).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" });
}

export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "n/a";
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 129600) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export const minutes = (m: number | null | undefined) =>
  m === null || m === undefined ? "n/a" : m < 90 ? `${num(m)} min` : `${num(m / 60, 1)} h`;

export const km = (d: number | null | undefined) =>
  d === null || d === undefined ? "n/a" : d < 10 ? `${num(d, 1)} km` : `${num(d)} km`;

export const title = (s: string) => s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

export const LEVELS = ["low", "medium", "high", "critical"] as const;
export type AlertLevel = (typeof LEVELS)[number];
/** Alert levels share the severity ramp: level 1 to 4. */
export const levelNumber = (level: string): 1 | 2 | 3 | 4 =>
  (Math.max(0, LEVELS.indexOf(level as AlertLevel)) + 1) as 1 | 2 | 3 | 4;
