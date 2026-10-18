import axios, { AxiosError, InternalAxiosRequestConfig } from "axios";

export const api = axios.create({ baseURL: "/api/v1" });

/** The current access token, for callers that cannot use the axios instance
 *  — the SSE reader builds its own `fetch` and needs the same header. */
export function accessToken(): string | null {
  try {
    return localStorage.getItem("access");
  } catch {
    return null; // private window with storage blocked
  }
}

api.interceptors.request.use((config) => {
  const token = accessToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

let refreshing: Promise<string | null> | null = null;

async function refreshAccess(): Promise<string | null> {
  const refresh = localStorage.getItem("refresh");
  if (!refresh) {
    localStorage.removeItem("access");
    return null;
  }
  try {
    const { data } = await axios.post("/api/v1/auth/refresh/", { refresh });
    localStorage.setItem("access", data.access);
    return data.access as string;
  } catch {
    localStorage.removeItem("access");
    localStorage.removeItem("refresh");
    return null;
  }
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as (InternalAxiosRequestConfig & { _retry?: boolean }) | undefined;
    if (error.response?.status === 401 && original && !original._retry) {
      original._retry = true;
      // one shared refresh for all concurrent 401s; the latch clears itself
      if (!refreshing) {
        refreshing = refreshAccess().finally(() => {
          refreshing = null;
        });
      }
      const token = await refreshing;
      if (token) {
        original.headers.Authorization = `Bearer ${token}`;
        return api(original);
      }
      if (window.location.pathname !== "/panel/login") window.location.href = "/panel/login";
    }
    return Promise.reject(error);
  },
);

/** Follows DRF pagination `next` links and returns ALL results (bounded). */
export async function fetchAllPages<T>(url: string, maxPages = 30): Promise<T[]> {
  const results: T[] = [];
  let next: string | null = url;
  let pages = 0;
  while (next && pages < maxPages) {
    const page: { results: T[]; next: string | null } = (
      await api.get<{ results: T[]; next: string | null }>(next)
    ).data;
    results.push(...page.results);
    // `next` is absolute (http://host/api/v1/...); strip it back to a path the
    // baseURL-relative client can request
    next = page.next ? page.next.replace(/^https?:\/\/[^/]+\/api\/v1/, "") : null;
    pages += 1;
  }
  return results;
}

export function errorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const data = err.response?.data as Record<string, unknown> | undefined;
    if (data) {
      if (typeof data.detail === "string") return data.detail;
      if (typeof data.error === "string") return data.error;
      const nested = data.error as { message?: string } | undefined;
      if (nested?.message) return nested.message;
      const firstKey = Object.keys(data)[0];
      const firstVal = firstKey ? data[firstKey] : undefined;
      if (Array.isArray(firstVal) && firstVal.length) return `${firstKey}: ${firstVal[0]}`;
    }
    if (err.response?.status) return `خطای سرور (${err.response.status})`;
    return "ارتباط با سرور برقرار نشد";
  }
  return "خطای ناشناخته";
}
