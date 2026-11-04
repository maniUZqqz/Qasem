import { useEffect, useMemo, useState } from "react";

import { g, problem, useGet, type ApiProblem } from "../api";
import type { Paged } from "../types";
import type { GrowthSettings, ItemStatus, OutreachItem } from "./types";

/** Helpers of the outreach screens (the shared `g` client lives in ../api). */

export const O = "/outreach";

/** A list endpoint may answer with a page object or a plain array: accept both. */
export function asList<T>(data: Paged<T> | T[] | null | undefined): T[] {
  if (!data) return [];
  return Array.isArray(data) ? data : data.results ?? [];
}

export function countOf<T>(data: Paged<T> | T[] | null | undefined): number {
  if (!data) return 0;
  return Array.isArray(data) ? data.length : data.count ?? data.results?.length ?? 0;
}

/** Field errors out of an API problem: our `{errors:[{field,message}]}` or a DRF `{field:[msg]}` body. */
export function fieldErrorsOf(p: ApiProblem | null): Record<string, string> {
  const out: Record<string, string> = {};
  if (!p) return out;
  for (const e of p.errors ?? []) out[e.field] = out[e.field] ? `${out[e.field]} ${e.message}` : e.message;
  if (!p.errors && p.body) {
    for (const [key, value] of Object.entries(p.body)) {
      if (Array.isArray(value) && typeof value[0] === "string") out[key] = value.join(" ");
    }
  }
  return out;
}

export function useSettings() {
  return useGet<GrowthSettings>("/settings/");
}

/** Fetches every item of a campaign in the given statuses (page by page, at most `maxPages`). */
export async function fetchItems(campaignId: number | string, statuses: ItemStatus[], maxPages = 5): Promise<OutreachItem[]> {
  const all: OutreachItem[] = [];
  for (const status of statuses) {
    for (let page = 1; page <= maxPages; page++) {
      const data = await g.get<Paged<OutreachItem> | OutreachItem[]>(`${O}/campaigns/${campaignId}/items/`, { status, page, page_size: 100 });
      all.push(...asList(data));
      if (Array.isArray(data) || !data.next) break;
    }
  }
  return all.sort((a, b) => a.id - b.id);
}

/** Debounced value: updates `delay` ms after the last change. */
export function useDebounced<T>(value: T, delay = 400): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return v;
}

/** Runs an async action with `busy` / `error` state (the error is the API problem, kept for field errors). */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiProblem | null>(null);
  return useMemo(
    () => ({
      busy,
      error,
      clear: () => setError(null),
      async run<T>(fn: () => Promise<T>): Promise<T | undefined> {
        setBusy(true);
        setError(null);
        try {
          return await fn();
        } catch (err) {
          setError(problem(err));
          return undefined;
        } finally {
          setBusy(false);
        }
      },
    }),
    [busy, error],
  );
}

export { problem };
export type { ApiProblem };
