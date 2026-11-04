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

/** JSON call to the same-origin /api proxy. Sends the CSRF double-submit header on state-changing requests. */
export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
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
  if (!res.ok) {
    const problem = data as { detail?: unknown; code?: string };
    const detail =
      typeof problem.detail === "string" ? problem.detail : "The request could not be completed.";
    throw new ApiError(res.status, detail, problem.code, Number(res.headers.get("Retry-After")) || undefined);
  }
  return data as T;
}
