/**
 * نسخهٔ نرم‌افزار — بخشِ خالصِ منطق (بی React و بی DOM تا با `node` آزموده شود).
 *
 * منبعِ نسخه فایلِ VERSION روی سرور است و `GET /api/v1/version/` آن را می‌دهد.
 * هر چیزِ نامعتبر (نشانیِ نصب‌نشده که HTML برگردانده، JSON خراب، نسخهٔ بی‌قالب)
 * ⇒ `null` ⇒ نشان اصلاً کشیده نمی‌شود؛ نشانِ نسخه نباید خودش خطا شود.
 */

export type VersionInfo = {
  version: string;
  built_at: string;
  commit: string;
  name: string;
};

export type ChangelogEntry = {
  version: string;
  date: string;
  summary: string;
  items: string[];
};

const VERSION_RE = /^\d{1,3}\.\d{2,3}$/;
const COMMIT_RE = /^[0-9a-f]{4,40}$/i;

const asText = (v: unknown, max = 600): string => (typeof v === "string" ? v.trim().slice(0, max) : "");

export function parseVersionInfo(raw: unknown): VersionInfo | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const r = raw as Record<string, unknown>;
  const version = asText(r.version, 12);
  if (!VERSION_RE.test(version)) return null;
  const commit = asText(r.commit, 40);
  return {
    version,
    built_at: asText(r.built_at, 40),
    commit: COMMIT_RE.test(commit) ? commit.toLowerCase() : "",
    name: asText(r.name, 60) || "NMarketing",
  };
}

/** `2026-11-07T05:30:00Z` ⇒ «۱۴۰۵/۸/۱۶» (تقویمِ شمسیِ خودِ مرورگر)؛ ناخوانا ⇒ "". */
export function formatBuilt(iso: string, locale = "fa-IR"): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  try {
    return d.toLocaleDateString(locale, { year: "numeric", month: "2-digit", day: "2-digit", timeZone: "Asia/Tehran" });
  } catch {
    return "";
  }
}

/** راهنمای شناور: «ساخته‌شده: ۱۴۰۵/۰۸/۱۶ · commit abc1234». */
export function tooltipFor(info: VersionInfo, locale = "fa-IR"): string {
  const parts: string[] = [];
  const built = formatBuilt(info.built_at, locale);
  if (built) parts.push(`ساخته‌شده: ${built}`);
  if (info.commit) parts.push(`commit ${info.commit}`);
  return parts.length ? parts.join(" · ") : `نسخهٔ ${info.version}`;
}

export function parseChangelog(raw: unknown): ChangelogEntry[] {
  if (!Array.isArray(raw)) return [];
  const out: ChangelogEntry[] = [];
  for (const e of raw.slice(0, 200)) {
    if (!e || typeof e !== "object") continue;
    const r = e as Record<string, unknown>;
    const version = asText(r.version, 12);
    if (!VERSION_RE.test(version)) continue;
    const items = Array.isArray(r.items) ? r.items.map((i) => asText(i)).filter(Boolean).slice(0, 100) : [];
    out.push({ version, date: asText(r.date, 60), summary: asText(r.summary), items });
  }
  return out;
}
