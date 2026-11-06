"use client";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
    public retryAfter?: number,
  ) {
    super(message);
  }
}

function cookie(name: string): string {
  if (typeof document === "undefined") return "";
  const match = document.cookie.split("; ").find((c) => c.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.split("=")[1] ?? "") : "";
}

let refreshing: Promise<boolean> | null = null;

/** Rotate the refresh cookie once, however many requests failed at the same time. */
function refreshSession(): Promise<boolean> {
  refreshing ??= (async () => {
    try {
      const csrf = cookie("ms_csrf");
      const res = await fetch("/api/v1/auth/refresh", {
        method: "POST",
        credentials: "same-origin",
        headers: csrf ? { "X-CSRF-Token": csrf } : {},
      });
      return res.ok;
    } catch {
      return false;
    } finally {
      window.setTimeout(() => (refreshing = null), 1000);
    }
  })();
  return refreshing;
}

/** JSON call to the same-origin /api proxy. Sends the CSRF double-submit header on state-changing requests.
 * A 401 on an application call triggers one token refresh and one retry before the user is sent to sign in. */
export async function api<T>(
  path: string,
  init: { method?: string; body?: unknown; retried?: boolean } = {},
): Promise<T> {
  const method = init.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") {
    const csrf = cookie("ms_csrf");
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  const res = await fetch(`/api/v1${path}`, {
    method,
    headers,
    credentials: "same-origin",
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const data: unknown = text ? JSON.parse(text) : {};
  if (res.status === 401 && !init.retried && !path.startsWith("/auth/")) {
    if (await refreshSession()) return api<T>(path, { ...init, retried: true });
    if (typeof window !== "undefined" && window.location.pathname.startsWith("/app")) {
      window.location.href = "/login?expired=1";
    }
  }
  if (!res.ok) {
    const problem = data as { detail?: unknown; code?: string };
    const detail =
      typeof problem.detail === "string" ? problem.detail : "The request could not be completed.";
    throw new ApiError(res.status, detail, problem.code, Number(res.headers.get("Retry-After")) || undefined);
  }
  return data as T;
}

/** Query string from the defined entries of an object. */
export function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params))
    if (v !== undefined && v !== null && v !== "") u.set(k, String(v));
  const out = u.toString();
  return out ? `?${out}` : "";
}

/** Multipart upload with the CSRF header. */
export async function upload<T>(path: string, form: FormData): Promise<T> {
  const csrf = cookie("ms_csrf");
  const res = await fetch(`/api/v1${path}`, {
    method: "POST",
    body: form,
    credentials: "same-origin",
    headers: csrf ? { "X-CSRF-Token": csrf } : {},
  });
  const data = (await res.json().catch(() => ({}))) as { detail?: string; code?: string };
  if (!res.ok) throw new ApiError(res.status, data.detail ?? "The upload failed.", data.code);
  return data as T;
}

/** Fetch a file (PDF, CSV, HTML) and hand it to the browser as a download. */
export async function download(path: string, filename: string): Promise<void> {
  const res = await fetch(`/api/v1${path}`, { credentials: "same-origin" });
  if (!res.ok) throw new ApiError(res.status, "The file could not be downloaded.");
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
