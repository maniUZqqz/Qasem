import axios from "axios";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, errorMessage } from "../../api/client";
import type { FieldError } from "./types";

/**
 * Thin helpers over the shared axios client (`/api/v1`, JWT, refresh on 401).
 * Everything the Growth Engine says to the server goes through `g(...)`, so the prefix lives in one place.
 */

const BASE = "/growth";

export const g = {
  get: <T,>(path: string, params?: Record<string, unknown>) => api.get<T>(BASE + path, { params }).then((r) => r.data),
  post: <T,>(path: string, body?: unknown) => api.post<T>(BASE + path, body).then((r) => r.data),
  patch: <T,>(path: string, body?: unknown) => api.patch<T>(BASE + path, body).then((r) => r.data),
  put: <T,>(path: string, body?: unknown) => api.put<T>(BASE + path, body).then((r) => r.data),
  del: (path: string, params?: Record<string, unknown>) => api.delete(BASE + path, { params }).then((r) => r.data),
  /** a path under /api/v1 for plain links (downloads) */
  url: (path: string, params?: Record<string, unknown>) => {
    const query = new URLSearchParams();
    Object.entries(params ?? {}).forEach(([k, v]) => v !== undefined && v !== "" && v !== null && query.set(k, String(v)));
    const qs = query.toString();
    return `/api/v1${BASE}${path}${qs ? `?${qs}` : ""}`;
  },
};

export type ApiProblem = {
  status: number;
  message: string;
  code?: string;
  errors?: FieldError[];
  /** the whole response body (409 duplicates carry `duplicates` here) */
  body?: Record<string, unknown>;
};

/** Turns any thrown value into something a screen can show. */
export function problem(err: unknown): ApiProblem {
  if (axios.isAxiosError(err)) {
    const body = (err.response?.data ?? undefined) as Record<string, unknown> | undefined;
    return {
      status: err.response?.status ?? 0,
      message: errorMessage(err),
      code: typeof body?.code === "string" ? body.code : undefined,
      errors: Array.isArray(body?.errors) ? (body?.errors as FieldError[]) : undefined,
      body,
    };
  }
  return { status: 0, message: errorMessage(err) };
}

/** Download a file through the authenticated client (a plain <a href> would not carry the JWT). */
export async function download(path: string, params: Record<string, unknown>, fallbackName: string) {
  const response = await api.get(BASE + path, { params, responseType: "blob" });
  const disposition = String(response.headers["content-disposition"] ?? "");
  const match = /filename="?([^";]+)"?/.exec(disposition);
  const href = URL.createObjectURL(response.data as Blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = match?.[1] ?? fallbackName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 10_000);
}

export type Loaded<T> = {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
  setData: (value: T | null) => void;
};

/**
 * GET a path and keep it in state. Re-fetches when `path` or `params` change (params are compared by value).
 * `poll` (ms) re-fetches silently on an interval - used for running jobs.
 */
export function useGet<T>(path: string | null, params?: Record<string, unknown>, options: { poll?: number } = {}): Loaded<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(path !== null);
  const [error, setError] = useState<string | null>(null);
  const key = JSON.stringify([path, params ?? null]);
  const seq = useRef(0);

  const run = useCallback(
    (silent: boolean) => {
      if (path === null) return;
      const mine = ++seq.current;
      if (!silent) setLoading(true);
      g.get<T>(path, params)
        .then((value) => {
          if (mine === seq.current) {
            setData(value);
            setError(null);
          }
        })
        .catch((err) => {
          if (mine === seq.current) setError(problem(err).message);
        })
        .finally(() => {
          if (mine === seq.current) setLoading(false);
        });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [key],
  );

  useEffect(() => {
    run(false);
    if (!options.poll) return;
    const timer = setInterval(() => run(true), options.poll);
    return () => clearInterval(timer);
  }, [run, options.poll]);

  return { data, loading, error, reload: () => run(false), setData };
}
