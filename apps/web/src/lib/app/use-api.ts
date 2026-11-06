"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";

export type Resource<T> = {
  data: T | undefined;
  error: ApiError | undefined;
  loading: boolean;
  reload: () => void;
};

/** GET a path (or nothing when `path` is null). Keeps the last data while a reload runs; ignores stale answers. */
export function useApi<T>(path: string | null): Resource<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<ApiError>();
  const [loading, setLoading] = useState(path !== null);
  const [tick, setTick] = useState(0);
  const seq = useRef(0);
  useEffect(() => {
    if (path === null) {
      setLoading(false);
      return;
    }
    const mine = ++seq.current;
    setLoading(true);
    api<T>(path).then(
      (d) => {
        if (mine !== seq.current) return;
        setData(d);
        setError(undefined);
        setLoading(false);
      },
      (e: unknown) => {
        if (mine !== seq.current) return;
        setError(e instanceof ApiError ? e : new ApiError(0, "The request failed."));
        setLoading(false);
      },
    );
  }, [path, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}
