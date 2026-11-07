/**
 * The software version, for the footer badge.
 *
 * One source of truth: the `VERSION` file at the project root, served by the
 * Django backend as `GET /api/v1/version/` (apps/common/versioning.py). The site
 * asks the API like every other piece of data here (see lib/api.ts) instead of
 * reading a file by path — a `fs` read of `../VERSION` makes Next's file tracer
 * pull the parent directory (the whole project, venv included) into the
 * standalone output, and it would not exist in the Docker image anyway.
 *
 * Same rule as the rest of the site: a dead backend, an old backend without the
 * endpoint, or a garbled answer all give `null` and the footer simply shows no
 * badge. It never fails a page or a build.
 *
 * `NM_VERSION_API_BASE` overrides the API address for this one call (used by the
 * smoke test, which points the build at a staging backend); in production it is
 * unset and the usual NEXT_PUBLIC_API_BASE applies.
 */
export type SiteVersion = { version: string; built_at: string; commit: string };

const BASE = process.env.NM_VERSION_API_BASE || process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";
const VERSION_RE = /^\d{1,3}\.\d{2,3}$/;
const COMMIT_RE = /^[0-9a-f]{4,40}$/i;

export async function getVersion(): Promise<SiteVersion | null> {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 4000);
    const res = await fetch(`${BASE}/api/v1/version/`, {
      // Same window as the rest of the footer data; tagged so it can be expired on demand.
      next: { revalidate: 120, tags: ["version"] },
      signal: controller.signal,
    });
    clearTimeout(timer);
    if (!res.ok) return null;
    const data = (await res.json()) as Record<string, unknown>;
    const version = typeof data?.version === "string" ? data.version.trim() : "";
    if (!VERSION_RE.test(version)) return null;
    const built = typeof data.built_at === "string" ? data.built_at.trim().slice(0, 40) : "";
    const commit = typeof data.commit === "string" && COMMIT_RE.test(data.commit.trim()) ? data.commit.trim().toLowerCase() : "";
    return { version, built_at: built, commit };
  } catch {
    return null;
  }
}

/** «ساخته‌شده: ۱۴۰۵/۰۸/۱۶ · commit abc1234» (fa) or «Built: 2026-11-07 · commit abc1234» (en). */
export function versionTitle(v: SiteVersion, locale: "fa" | "en"): string {
  const parts: string[] = [];
  const d = new Date(v.built_at);
  if (v.built_at && !Number.isNaN(d.getTime())) {
    try {
      const when =
        locale === "fa"
          ? d.toLocaleDateString("fa-IR", { year: "numeric", month: "2-digit", day: "2-digit", timeZone: "Asia/Tehran" })
          : d.toLocaleDateString("en-CA", { timeZone: "UTC" });
      parts.push(locale === "fa" ? `ساخته‌شده: ${when}` : `Built: ${when}`);
    } catch {
      /* no ICU data for the locale: skip the date */
    }
  }
  if (v.commit) parts.push(`commit ${v.commit}`);
  if (!parts.length) parts.push(locale === "fa" ? `نسخهٔ ${v.version}` : `Version ${v.version}`);
  return parts.join(" · ");
}
