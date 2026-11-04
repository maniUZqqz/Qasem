/**
 * The lead list's filters, kept in the URL query string so a filtered view can be linked, reloaded and
 * reached with the back button. Names are the server's (`leads/services/queries.py`).
 */
export type LeadFilters = {
  q: string;
  status: string[];
  origin: string;
  country: string;
  city: string;
  category: string;
  tag: string[];
  has: string[];
  created_from: string;
  created_to: string;
  archived: "0" | "1" | "all";
  ordering: string;
  page: number;
  page_size: number;
  source_job: string;
};

export const DEFAULT_ORDERING = "-created_at";
export const PAGE_SIZES = [25, 50, 100];

const csv = (v: string | null) => (v ? v.split(",").map((s) => s.trim()).filter(Boolean) : []);

export function readFilters(p: URLSearchParams): LeadFilters {
  const size = Number(p.get("page_size"));
  const page = Number(p.get("page"));
  const archived = p.get("archived");
  return {
    q: p.get("q") ?? "",
    status: csv(p.get("status")),
    origin: p.get("origin") ?? "",
    country: p.get("country") ?? "",
    city: p.get("city") ?? "",
    category: p.get("category") ?? "",
    tag: csv(p.get("tag")),
    has: csv(p.get("has")),
    created_from: p.get("created_from") ?? "",
    created_to: p.get("created_to") ?? "",
    archived: archived === "1" || archived === "all" ? archived : "0",
    ordering: p.get("ordering") ?? DEFAULT_ORDERING,
    page: Number.isInteger(page) && page > 0 ? page : 1,
    page_size: PAGE_SIZES.includes(size) ? size : 25,
    source_job: p.get("source_job") ?? "",
  };
}

/** Parameters for the API and the URL: defaults are left out so the address stays short. */
export function toParams(f: LeadFilters): Record<string, string | number> {
  const out: Record<string, string | number> = {};
  if (f.q) out.q = f.q;
  if (f.status.length) out.status = f.status.join(",");
  if (f.origin) out.origin = f.origin;
  if (f.country) out.country = f.country;
  if (f.city) out.city = f.city;
  if (f.category) out.category = f.category;
  if (f.tag.length) out.tag = f.tag.join(",");
  if (f.has.length) out.has = f.has.join(",");
  if (f.created_from) out.created_from = f.created_from;
  if (f.created_to) out.created_to = f.created_to;
  if (f.archived !== "0") out.archived = f.archived;
  if (f.ordering !== DEFAULT_ORDERING) out.ordering = f.ordering;
  if (f.page > 1) out.page = f.page;
  if (f.page_size !== 25) out.page_size = f.page_size;
  if (f.source_job) out.source_job = f.source_job;
  return out;
}

/** How many filters are switched on (search, sorting and paging do not count). */
export function activeFilterCount(f: LeadFilters): number {
  return (
    f.status.length +
    (f.origin ? 1 : 0) +
    (f.country ? 1 : 0) +
    (f.city ? 1 : 0) +
    (f.category ? 1 : 0) +
    f.tag.length +
    f.has.length +
    (f.created_from ? 1 : 0) +
    (f.created_to ? 1 : 0) +
    (f.archived !== "0" ? 1 : 0) +
    (f.source_job ? 1 : 0)
  );
}

/** Filters that make the list narrower than "all leads" (the search box counts here). */
export function isNarrowed(f: LeadFilters): boolean {
  return activeFilterCount(f) > 0 || f.q.trim() !== "";
}
