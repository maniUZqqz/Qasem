/**
 * منطقِ خالصِ صفحهٔ «گزارشِ سرورهای پردازش» (بدونِ React و DOM، تا بدونِ مرورگر آزمون شود): قالبِ اعداد و مدت، تاریخِ شمسی،
 * بازهٔ زمانی و نشانیِ درخواست/CSV، کاهشِ نقاطِ نمودار و ساختنِ مسیرِ SVG، نوارِ زمانیِ روشن/خاموش، و متن‌های ثابتِ صفحه.
 * خودِ صفحه فقط نمایش می‌دهد.
 *
 * آزمون: frontend/tests/compute-report.test.ts
 */
import { humanDuration, relativeTime, toFa, versionText } from "../queue/model";

export { humanDuration, relativeTime, toFa, versionText };

export type Tone = "neutral" | "brand" | "ok" | "warn" | "bad" | "info";

// ───────────────────────────────────────────────────────────── نوعِ پاسخِ API

export type JobStat = {
  count: number;
  success: number;
  failed: number;
  cancelled: number;
  running: number;
  waiting: number;
  avg_run_s: number | null;
  avg_wait_s: number | null;
  success_rate: number | null;
};

export type KindStat = JobStat & { kind: string; kind_label: string; p50_run_s?: number | null; p95_run_s?: number | null };

export type Uptime = {
  range_s: number;
  online_s: number;
  pct: number | null;
  longest_gap_s: number;
  sessions: number;
  since: string | null;
  partial: boolean;
};

export type SessionRow = { started: string; ended: string | null; minutes: number; ongoing: boolean; agent: string };

export type Point = [number, number];

export type SeriesMap = {
  ram_used_pct: Point[];
  vram_used_pct: Point[];
  disk_free_gb: Point[];
  gpu_util_pct: Point[];
  gpu_temp_c: Point[];
};

export type Resources = {
  ram_free_mb: number | null;
  ram_total_mb: number | null;
  vram_used_mb: number | null;
  vram_total_mb: number | null;
  disk_free_gb: number | null;
  disk_total_gb: number | null;
  gpu_util_pct: number | null;
  gpu_temp_c: number | null;
  ram_used_pct: number | null;
  vram_used_pct: number | null;
  disk_used_pct: number | null;
};

export type ModelsInfo = {
  ollama: string[];
  ollama_stale: boolean;
  comfy: Record<string, string[]>;
  comfy_count: number;
  audio: Record<string, boolean>;
  voice_clone: boolean;
  packages: { key: string; title: string; installed: boolean; optional: boolean; missing_mb: number; total_mb: number }[];
  download_running: boolean;
  download_error: string;
};

export type ReportNode = {
  id: number;
  name: string;
  enabled: boolean;
  online: boolean;
  last_seen: string | null;
  created: string;
  agent: string | null;
  agent_latest: string | null;
  update_waiting: boolean;
  hostname: string | null;
  gpu: string | null;
  services: Record<string, boolean>;
  models: ModelsInfo;
  resources: Resources;
  resources_known: { ram: boolean; vram: boolean; disk: boolean; gpu_util: boolean; gpu_temp: boolean };
  jobs: JobStat;
  jobs_by_kind: KindStat[];
  logs: { count: number; kept_max: number; truncated: boolean };
  uptime: Uptime;
  segments: [number, number][];
  sessions: SessionRow[];
  sessions_truncated: boolean;
  series: SeriesMap;
};

export type Explain = { code: string; known: boolean; what: string; advice: string };

export type ErrorItem = {
  source: "job" | "log";
  at: string;
  node: string | null;
  node_id: number | null;
  level: string;
  kind: string | null;
  kind_label: string;
  uid: string | null;
  short: string;
  text: string;
  explain: Explain;
};

export type DownloadActive = {
  source: "job" | "node";
  uid: string | null;
  title: string;
  kind: string;
  node: string | null;
  state: string;
  percent: number | null;
  bytes_done: number | null;
  bytes_total: number | null;
  speed_bps: number | null;
  eta_s: number | null;
  phase: string;
  attempt: number | null;
  max_attempts: number | null;
  message: string;
  items_done?: number | null;
  items_total?: number | null;
  failed?: string[];
};

export type DownloadWaiting = {
  uid: string;
  title: string;
  kind: string;
  node_wanted: string;
  scheduled_for: string | null;
  window: string;
  status_text: string;
  wait_reason: string;
  waiting_s: number | null;
  created: string;
};

export type DownloadHistory = {
  uid: string;
  title: string;
  kind: string;
  node: string | null;
  state: string;
  state_label: string;
  started: string | null;
  finished: string | null;
  created: string;
  scheduled_for: string | null;
  window: string;
  run_s: number | null;
  bytes: number | null;
  speed_bps: number | null;
  error: string;
  explain: string;
};

export type DevicesInfo = {
  counted: number;
  without_device: number;
  by_device: Record<string, number>;
  by_kind: { kind: string; kind_label: string; count: number; devices: Record<string, number> }[];
  fallbacks: { uid: string; short: string; kind: string; kind_label: string; node: string | null; at: string; device: string; warning: string }[];
  truncated: boolean;
};

export type ReportData = {
  generated_at: string;
  range: {
    from: string;
    to: string;
    start: string;
    end: string;
    days: number;
    retention_days: number;
    tracking_start: string | null;
    max_days: number;
  };
  agent_latest: string | null;
  site_version: string;
  nodes: ReportNode[];
  jobs: { per_kind: KindStat[]; totals: JobStat };
  /** عامل ۲٫۱۱: هر کارِ تمام‌شده روی چه دستگاهی اجرا شد (کارت یا پردازنده) */
  devices?: DevicesInfo;
  queue_now: { waiting: number; running: number; oldest_wait_s: number | null; oldest_wait_text: string };
  errors: ErrorItem[];
  error_groups: { code: string; count: number; what: string }[];
  downloads: { active: DownloadActive[]; waiting: DownloadWaiting[]; history: DownloadHistory[] };
  agent_versions: { version: string; nodes: string[]; latest: boolean }[];
  logs_note: { kept_per_node: number; any_truncated: boolean };
};

export type LogLine = {
  id: number;
  node: string;
  node_id: number;
  level: string;
  message: string;
  ts: string;
  received: string;
  explain: Explain | null;
};

export type LogsData = {
  total: number;
  limit: number;
  offset: number;
  lines: LogLine[];
  kept_per_node: number;
  truncated: boolean;
  oldest: string | null;
};

// ───────────────────────────────────────────────────────────── اعداد و اندازه

/** «۱٫۵» — ممیزِ فارسی؛ عددِ نامعتبر ⇒ «—». */
export function fmtNum(n: number | null | undefined, digits = 1): string {
  if (typeof n !== "number" || !Number.isFinite(n)) return "—";
  const fixed = Number(n.toFixed(digits));
  const [int, frac] = String(fixed).split(".");
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, "٬");
  return toFa(frac ? `${grouped}٫${frac}` : grouped);
}

/** بایت ⇒ «۴۵۰ مگابایت» / «۱٫۲ گیگابایت». */
export function fmtBytes(n: number | null | undefined): string {
  if (typeof n !== "number" || !Number.isFinite(n) || n < 0) return "—";
  if (n < 1024) return `${fmtNum(n, 0)} بایت`;
  if (n < 1024 ** 2) return `${fmtNum(n / 1024, 0)} کیلوبایت`;
  if (n < 1024 ** 3) return `${fmtNum(n / 1024 ** 2, n < 10 * 1024 ** 2 ? 1 : 0)} مگابایت`;
  return `${fmtNum(n / 1024 ** 3, 1)} گیگابایت`;
}

export function fmtMb(mb: number | null | undefined): string {
  return typeof mb === "number" && Number.isFinite(mb) ? fmtBytes(mb * 1024 ** 2) : "—";
}

export function fmtGb(gb: number | null | undefined): string {
  if (typeof gb !== "number" || !Number.isFinite(gb)) return "—";
  return `${fmtNum(gb, gb < 10 ? 1 : 0)} گیگابایت`;
}

export function fmtSpeed(bps: number | null | undefined): string {
  if (typeof bps !== "number" || !Number.isFinite(bps) || bps <= 0) return "";
  return `${fmtBytes(bps)} بر ثانیه`;
}

export function fmtPct(p: number | null | undefined, digits = 0): string {
  return typeof p === "number" && Number.isFinite(p) ? `${fmtNum(p, digits)}٪` : "—";
}

export function fmtTemp(c: number | null | undefined): string {
  return typeof c === "number" && Number.isFinite(c) ? `${fmtNum(c, 0)} درجه` : "—";
}

/** مدت به زبانِ آدم؛ ناشناخته ⇒ «—». */
export function dur(s: number | null | undefined): string {
  const t = humanDuration(s);
  return t || "—";
}

/** «۸ دقیقه و ۱۲ ثانیه» برای مدت‌های کوتاهِ اجرا؛ بیشتر از یک ساعت همان humanDuration. */
export function runDuration(s: number | null | undefined): string {
  if (typeof s !== "number" || !Number.isFinite(s)) return "—";
  const t = Math.max(0, Math.round(s));
  if (t < 60) return `${toFa(t)} ثانیه`;
  if (t < 3600) {
    const m = Math.floor(t / 60);
    const r = t % 60;
    return `${toFa(m)} دقیقه` + (r ? ` و ${toFa(r)} ثانیه` : "");
  }
  return humanDuration(t);
}

// ───────────────────────────────────────────────────────────── تاریخِ شمسی (وقتِ تهران)

const TEHRAN_OFFSET_MS = 3.5 * 3600 * 1000;
const DAY_MS = 86_400_000;

const BREAKS = [-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210, 1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178];
const div = (a: number, b: number) => Math.trunc(a / b);
const mod = (a: number, b: number) => a - Math.trunc(a / b) * b;

function jalCal(jy: number, withoutLeap = false): { leap: number; gy: number; march: number } {
  const bl = BREAKS.length;
  const gy = jy + 621;
  let leapJ = -14;
  let jp = BREAKS[0];
  let jump = 0;
  if (jy < jp || jy >= BREAKS[bl - 1]) throw new Error("invalid jalali year");
  for (let i = 1; i < bl; i += 1) {
    const jm = BREAKS[i];
    jump = jm - jp;
    if (jy < jm) break;
    leapJ += div(jump, 33) * 8 + div(mod(jump, 33), 4);
    jp = jm;
  }
  let n = jy - jp;
  leapJ += div(n, 33) * 8 + div(mod(n, 33) + 3, 4);
  if (mod(jump, 33) === 4 && jump - n === 4) leapJ += 1;
  const leapG = div(gy, 4) - div((div(gy, 100) + 1) * 3, 4) - 150;
  const march = 20 + leapJ - leapG;
  if (withoutLeap) return { leap: 0, gy, march };
  if (jump - n < 6) n = n - jump + div(jump + 4, 33) * 33;
  let leap = mod(mod(n + 1, 33) - 1, 4);
  if (leap === -1) leap = 4;
  return { leap, gy, march };
}

function g2d(gy: number, gm: number, gd: number): number {
  let d = div((gy + div(gm - 8, 6) + 100100) * 1461, 4) + div(153 * mod(gm + 9, 12) + 2, 5) + gd - 34840408;
  d = d - div(div(gy + 100100 + div(gm - 8, 6), 100) * 3, 4) + 752;
  return d;
}

function d2g(jdn: number): { gy: number; gm: number; gd: number } {
  let j = 4 * jdn + 139361631;
  j += div(div(4 * jdn + 183187720, 146097) * 3, 4) * 4 - 3908;
  const i = div(mod(j, 1461), 4) * 5 + 308;
  const gd = div(mod(i, 153), 5) + 1;
  const gm = mod(div(i, 153), 12) + 1;
  const gy = div(j, 1461) - 100100 + div(8 - gm, 6);
  return { gy, gm, gd };
}

function j2d(jy: number, jm: number, jd: number): number {
  const r = jalCal(jy, true);
  return g2d(r.gy, 3, r.march) + (jm - 1) * 31 - div(jm, 7) * (jm - 7) + jd - 1;
}

function d2j(jdn: number): { jy: number; jm: number; jd: number } {
  const gy = d2g(jdn).gy;
  let jy = gy - 621;
  const r = jalCal(jy, false);
  const jdn1f = g2d(gy, 3, r.march);
  let k = jdn - jdn1f;
  if (k >= 0) {
    if (k <= 185) return { jy, jm: 1 + div(k, 31), jd: mod(k, 31) + 1 };
    k -= 186;
  } else {
    jy -= 1;
    k += 179;
    if (r.leap === 1) k += 1;
  }
  return { jy, jm: 7 + div(k, 30), jd: mod(k, 30) + 1 };
}

/** میلادی ⇒ [سالِ شمسی، ماه، روز] */
export function toJalali(gy: number, gm: number, gd: number): [number, number, number] {
  const r = d2j(g2d(gy, gm, gd));
  return [r.jy, r.jm, r.jd];
}

/** شمسی ⇒ [سالِ میلادی، ماه، روز] */
export function toGregorian(jy: number, jm: number, jd: number): [number, number, number] {
  const r = d2g(j2d(jy, jm, jd));
  return [r.gy, r.gm, r.gd];
}

const pad2 = (n: number) => String(n).padStart(2, "0");

/** «۲۰۲۶-۱۱-۰۷» (لاتین) از لحظه‌ای به وقتِ تهران. */
export function tehranIsoDate(nowMs: number): string {
  const d = new Date(nowMs + TEHRAN_OFFSET_MS);
  return `${d.getUTCFullYear()}-${pad2(d.getUTCMonth() + 1)}-${pad2(d.getUTCDate())}`;
}

export function shiftIsoDate(iso: string, days: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const t = new Date(Date.UTC(y, m - 1, d) + days * DAY_MS);
  return `${t.getUTCFullYear()}-${pad2(t.getUTCMonth() + 1)}-${pad2(t.getUTCDate())}`;
}

export function isoDaysBetween(from: string, to: string): number {
  const a = from.split("-").map(Number);
  const b = to.split("-").map(Number);
  return Math.round((Date.UTC(b[0], b[1] - 1, b[2]) - Date.UTC(a[0], a[1] - 1, a[2])) / DAY_MS);
}

/** «۱۴۰۵/۰۸/۱۶» از «2026-11-07»؛ ورودیِ بد ⇒ «». */
export function jalaliDate(iso: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso ?? "");
  if (!m) return "";
  try {
    const [jy, jm, jd] = toJalali(Number(m[1]), Number(m[2]), Number(m[3]));
    return toFa(`${jy}/${pad2(jm)}/${pad2(jd)}`);
  } catch {
    return "";
  }
}

/** لحظهٔ ISO ⇒ «۱۴۰۵/۰۸/۱۶ ۱۴:۲۱» به وقتِ تهران؛ نامعتبر ⇒ «—». */
export function jalaliDateTime(iso: string | number | null | undefined): string {
  if (iso === null || iso === undefined || iso === "") return "—";
  const ms = typeof iso === "number" ? iso * 1000 : Date.parse(iso);
  if (!Number.isFinite(ms)) return "—";
  const t = new Date(ms + TEHRAN_OFFSET_MS);
  const day = jalaliDate(`${t.getUTCFullYear()}-${pad2(t.getUTCMonth() + 1)}-${pad2(t.getUTCDate())}`);
  return `${day} ${toFa(`${pad2(t.getUTCHours())}:${pad2(t.getUTCMinutes())}`)}`;
}

/** فقط ساعت و دقیقه به وقتِ تهران: «۱۴:۲۱» (epoch ثانیه یا ISO). */
export function clockText(v: string | number): string {
  const ms = typeof v === "number" ? v * 1000 : Date.parse(v);
  if (!Number.isFinite(ms)) return "—";
  const t = new Date(ms + TEHRAN_OFFSET_MS);
  return toFa(`${pad2(t.getUTCHours())}:${pad2(t.getUTCMinutes())}`);
}

const DIGITS: Record<string, string> = {};
"۰۱۲۳۴۵۶۷۸۹".split("").forEach((c, i) => (DIGITS[c] = String(i)));
"٠١٢٣٤٥٦٧٨٩".split("").forEach((c, i) => (DIGITS[c] = String(i)));

/** «۱۴۰۵/۰۸/۱۶» یا «1405-8-16» ⇒ «2026-11-07»؛ نادرست (ماهِ ۱۳، روزِ ۳۱ در ماهِ ۷ تا ۱۲، روزِ ۳۰ اسفندِ غیرکبیسه…) ⇒ null. */
export function parseJalaliDate(text: string): string | null {
  const latin = String(text ?? "")
    .trim()
    .replace(/[۰-۹٠-٩]/g, (c) => DIGITS[c]);
  const m = /^(\d{4})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})$/.exec(latin);
  if (!m) return null;
  const [jy, jm, jd] = [Number(m[1]), Number(m[2]), Number(m[3])];
  if (jy < 1300 || jy > 1600 || jm < 1 || jm > 12 || jd < 1 || jd > 31) return null;
  try {
    const [gy, gm, gd] = toGregorian(jy, jm, jd);
    const back = toJalali(gy, gm, gd);
    if (back[0] !== jy || back[1] !== jm || back[2] !== jd) return null; // روزِ ناموجود (مثل ۳۱ شهریور+۱ یا ۳۰ اسفندِ غیرکبیسه)
    return `${gy}-${pad2(gm)}-${pad2(gd)}`;
  } catch {
    return null;
  }
}

// ───────────────────────────────────────────────────────────── بازهٔ زمانی

export type Preset = "today" | "7d" | "30d" | "custom";

export const PRESETS: { key: Preset; label: string; days?: number }[] = [
  { key: "today", label: "امروز", days: 1 },
  { key: "7d", label: "۷ روزِ اخیر", days: 7 },
  { key: "30d", label: "۳۰ روزِ اخیر", days: 30 },
  { key: "custom", label: "بازهٔ دلخواه" },
];

export const MAX_DAYS = 90;

/** انتخابِ بازه: پیش‌تنظیم، یا (برای custom) دو روزِ میلادیِ ISO که صفحه از ورودیِ شمسی ساخته است. */
export type RangeSel = { preset: Preset; from?: string; to?: string };

export const DEFAULT_RANGE: RangeSel = { preset: "7d" };

/** پارامترهای بازه برای API؛ custom بی‌تاریخ ⇒ هفت روز. */
export function rangeParams(sel: RangeSel): Record<string, string> {
  if (sel.preset === "custom" && sel.from && sel.to) return { from: sel.from, to: sel.to };
  const days = PRESETS.find((p) => p.key === sel.preset)?.days ?? 7;
  return { days: String(days) };
}

export type CustomRangeResult = { ok: true; from: string; to: string; days: number } | { ok: false; error: string };

/** تاریخِ شمسیِ نوشته‌شده توسط کاربر ⇒ بازهٔ معتبر یا پیامِ خطای فارسی. `todayIso` = امروزِ تهران (میلادی). */
export function validateCustomRange(fromText: string, toText: string, todayIso: string): CustomRangeResult {
  const from = parseJalaliDate(fromText);
  const toRaw = toText.trim() ? parseJalaliDate(toText) : todayIso;
  if (!from) return { ok: false, error: "تاریخِ شروع را مثل ۱۴۰۵/۰۸/۱۰ بنویسید." };
  if (!toRaw) return { ok: false, error: "تاریخِ پایان را مثل ۱۴۰۵/۰۸/۱۶ بنویسید." };
  const to = toRaw > todayIso ? todayIso : toRaw;
  if (from > todayIso) return { ok: false, error: "تاریخِ شروع در آینده است." };
  if (from > to) return { ok: false, error: "تاریخِ شروع باید پیش از تاریخِ پایان باشد." };
  const days = isoDaysBetween(from, to) + 1;
  if (days > MAX_DAYS) return { ok: false, error: `بازه نباید بیشتر از ${toFa(MAX_DAYS)} روز باشد.` };
  return { ok: true, from, to, days };
}

/** «۱۴۰۵/۰۸/۱۰ تا ۱۴۰۵/۰۸/۱۶» (شمسی) از بازهٔ پاسخ. */
export function rangeText(range: Pick<ReportData["range"], "from" | "to" | "days">): string {
  if (range.from === range.to) return `${jalaliDate(range.from)} (یک روز)`;
  return `${jalaliDate(range.from)} تا ${jalaliDate(range.to)} (${toFa(range.days)} روز)`;
}

/** رشتهٔ پرس‌وجو برای GET /compute/report/ — ترتیبِ ثابت، تا کلیدِ «داده مالِ کدام درخواست است» پایدار بماند. */
export function reportQuery(sel: RangeSel, nodeId: number | null): string {
  const p = new URLSearchParams(rangeParams(sel));
  if (nodeId) p.set("node", String(nodeId));
  return p.toString();
}

export const LEVEL_OPTIONS: { key: string; label: string }[] = [
  { key: "all", label: "همهٔ سطح‌ها" },
  { key: "error", label: "خطا" },
  { key: "warning", label: "هشدار" },
  { key: "info", label: "اطلاع" },
];

export const PAGE_SIZE = 100;

export function logsQuery(p: { sel: RangeSel; nodeId: number | null; level: string; q: string; offset: number; limit?: number }): string {
  const params = new URLSearchParams(rangeParams(p.sel));
  if (p.nodeId) params.set("node", String(p.nodeId));
  if (p.level && p.level !== "all") params.set("level", p.level);
  const q = p.q.trim().slice(0, 100);
  if (q) params.set("q", q);
  params.set("limit", String(Math.max(1, Math.min(500, Math.floor(p.limit ?? PAGE_SIZE)))));
  params.set("offset", String(Math.max(0, Math.floor(p.offset))));
  return params.toString();
}

export type CsvSection = "jobs" | "sessions" | "samples" | "logs" | "errors" | "downloads";

export const CSV_LABELS: Record<CsvSection, string> = {
  jobs: "کارها",
  sessions: "نوبت‌های روشن/خاموش",
  samples: "منابع (RAM، VRAM، دیسک، GPU)",
  logs: "لاگ‌ها",
  errors: "خطاها",
  downloads: "دانلودها",
};

/** نشانیِ خروجیِ CSV (نسبت به /api/v1). لاگ‌ها فیلترهای سطح و جستجو را هم می‌برند. */
export function csvPath(
  section: CsvSection,
  sel: RangeSel,
  nodeId: number | null,
  extra: { level?: string; q?: string } = {},
): string {
  const p = new URLSearchParams({ section, ...rangeParams(sel) });
  if (nodeId) p.set("node", String(nodeId));
  if (section === "logs") {
    if (extra.level && extra.level !== "all") p.set("level", extra.level);
    const q = (extra.q ?? "").trim().slice(0, 100);
    if (q) p.set("q", q);
  }
  return `/compute/report/export.csv?${p.toString()}`;
}

/** پیامِ خطای فارسی از بدنهٔ خطای DRF که به‌صورت متن رسیده (دانلودِ blob خطا را متن می‌کند). */
export function errorTextFromBody(body: string): string {
  try {
    const data = JSON.parse(body) as unknown;
    const pick = (v: unknown): string => {
      if (typeof v === "string") return v;
      if (Array.isArray(v)) return v.map(pick).filter(Boolean)[0] ?? "";
      if (v && typeof v === "object") return Object.values(v as Record<string, unknown>).map(pick).filter(Boolean)[0] ?? "";
      return "";
    };
    return pick(data) || "خروجی ساخته نشد.";
  } catch {
    return "خروجی ساخته نشد.";
  }
}

/** «نگه‌داریِ آمار (روز)»: ۱ تا ۳۶۵. */
export function parseRetention(text: string): { ok: true; days: number } | { ok: false; error: string } {
  const latin = String(text ?? "")
    .trim()
    .replace(/[۰-۹٠-٩]/g, (c) => DIGITS[c]);
  if (!/^\d{1,3}$/.test(latin)) return { ok: false, error: "تعدادِ روز را با عدد بنویسید (۱ تا ۳۶۵)." };
  const days = Number(latin);
  if (days < 1 || days > 365) return { ok: false, error: "تعدادِ روز باید بین ۱ تا ۳۶۵ باشد." };
  return { ok: true, days };
}

// ───────────────────────────────────────────────────────────── نمودار

export function seriesStats(points: Point[]): { min: number; max: number; avg: number; last: number } | null {
  const vals = points.map((p) => p[1]).filter((v) => Number.isFinite(v));
  if (vals.length === 0) return null;
  return {
    min: Math.min(...vals),
    max: Math.max(...vals),
    avg: vals.reduce((a, b) => a + b, 0) / vals.length,
    last: points[points.length - 1][1],
  };
}

/** نقطه‌های بیش از `max` را با میانگینِ سطل کم می‌کند (زمان و مقدارِ هر سطل میانگین است)؛ ترتیبِ زمانی حفظ می‌شود. */
export function thinPoints(points: Point[], max: number): Point[] {
  const clean = points.filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1])).sort((a, b) => a[0] - b[0]);
  if (max < 2 || clean.length <= max) return clean;
  const out: Point[] = [];
  const size = clean.length / max;
  for (let i = 0; i < max; i += 1) {
    const slice = clean.slice(Math.floor(i * size), Math.floor((i + 1) * size) || undefined);
    if (slice.length === 0) continue;
    const t = slice.reduce((a, p) => a + p[0], 0) / slice.length;
    const v = slice.reduce((a, p) => a + p[1], 0) / slice.length;
    out.push([Math.round(t), Math.round(v * 10) / 10]);
  }
  return out;
}

/** سقفِ محورِ عمودی: درصدها ۱۰۰؛ بقیه کمی بالاتر از بیشینهٔ داده، گرد‌شده. */
export function niceMax(values: number[], hardMax?: number): number {
  if (hardMax !== undefined) return hardMax;
  const m = values.length ? Math.max(...values) : 0;
  if (m <= 0) return 1;
  const pow = 10 ** Math.floor(Math.log10(m));
  const unit = m / pow <= 2 ? pow / 2 : pow;
  return Math.ceil((m * 1.05) / unit) * unit;
}

export type LinePaths = { lines: string[]; areas: string[]; dots: [number, number][] };

/**
 * نقطه‌ها ⇒ مسیرهای SVG. هر وقفه‌ای بزرگ‌تر از `gapS` (مثلاً وقتی سرور خاموش بود) خط را می‌شکند، نه اینکه دو سویش را وصل کند.
 * نقطهٔ تنها (بین دو وقفه) به‌صورتِ دایره (dots) کشیده می‌شود. x از `lo` تا `hi` (ثانیهٔ epoch) روی [0, w]، y از ۰ تا yMax روی [h, 0].
 */
export function buildLinePaths(points: Point[], lo: number, hi: number, w: number, h: number, yMax: number, gapS: number): LinePaths {
  const out: LinePaths = { lines: [], areas: [], dots: [] };
  if (!(hi > lo) || !(yMax > 0)) return out;
  const x = (t: number) => Math.round(((t - lo) / (hi - lo)) * w * 10) / 10;
  const y = (v: number) => Math.round((h - (Math.max(0, Math.min(yMax, v)) / yMax) * h) * 10) / 10;
  const runs: Point[][] = [];
  let cur: Point[] = [];
  for (const p of points.filter((q) => q[0] >= lo && q[0] <= hi)) {
    if (cur.length && p[0] - cur[cur.length - 1][0] > gapS) {
      runs.push(cur);
      cur = [];
    }
    cur.push(p);
  }
  if (cur.length) runs.push(cur);
  for (const run of runs) {
    if (run.length === 1) {
      out.dots.push([x(run[0][0]), y(run[0][1])]);
      continue;
    }
    const d = run.map((p, i) => `${i ? "L" : "M"}${x(p[0])} ${y(p[1])}`).join(" ");
    out.lines.push(d);
    out.areas.push(`${d} L${x(run[run.length - 1][0])} ${h} L${x(run[0][0])} ${h} Z`);
  }
  return out;
}

/** بزرگ‌ترین فاصلهٔ مجازِ بین دو نقطه پیش از شکستنِ خط: دو برابرِ گامِ نمونه‌ها (بازهٔ کوتاه ⇒ ۱ دقیقه، بلند ⇒ سطلِ ۱۵ دقیقه و بیشتر). */
export function gapLimit(rangeS: number, buckets = 240): number {
  return Math.max(150, (rangeS / buckets) * 2.5);
}

export type Seg = { left: number; width: number };

/** نوارِ روشن/خاموش: هر بازه ⇒ درصدِ چپ و پهنا (کمینه ۰٫۴٪ تا نوبتِ کوتاه هم دیده شود). */
export function segmentBars(segments: [number, number][], lo: number, hi: number): Seg[] {
  if (!(hi > lo)) return [];
  const total = hi - lo;
  const out: Seg[] = [];
  for (const [s, e] of segments) {
    const a = Math.max(lo, Math.min(hi, s));
    const b = Math.max(lo, Math.min(hi, e));
    if (b < a) continue;
    const left = ((a - lo) / total) * 100;
    const width = Math.max(0.4, ((b - a) / total) * 100);
    out.push({ left: Math.round(left * 100) / 100, width: Math.round(Math.min(width, 100 - left) * 100) / 100 });
  }
  return out;
}

/** برچسبِ محورِ زمان: بازهٔ کوتاه ⇒ ساعت، بلند ⇒ تاریخِ شمسی. */
export function axisLabel(epochS: number, spanS: number): string {
  if (spanS <= 2 * 86400) return clockText(epochS);
  const t = new Date(epochS * 1000 + TEHRAN_OFFSET_MS);
  return jalaliDate(`${t.getUTCFullYear()}-${pad2(t.getUTCMonth() + 1)}-${pad2(t.getUTCDate())}`).slice(5);
}

// ───────────────────────────────────────────────────────────── سرور

/** «2.60» ⇒ «۲٫۶۰» (ممیزِ فارسی). */
export function faVersion(v: string | null | undefined): string {
  return toFa(String(v ?? "")).replace(/\./g, "٫");
}

export type NodeState = "online" | "offline" | "disabled";

export function nodeState(n: Pick<ReportNode, "enabled" | "online">): { state: NodeState; label: string; tone: Tone } {
  if (!n.enabled) return { state: "disabled", label: "غیرفعال", tone: "neutral" };
  return n.online ? { state: "online", label: "روشن", tone: "ok" } : { state: "offline", label: "خاموش", tone: "bad" };
}

/** روشن‌ها اول، بعد خاموش‌ها، بعد غیرفعال‌ها؛ در هر دسته به ترتیبِ نام. */
export function sortNodes<T extends Pick<ReportNode, "enabled" | "online" | "name">>(nodes: T[]): T[] {
  const rank = (n: T) => (!n.enabled ? 2 : n.online ? 0 : 1);
  return [...nodes].sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
}

export function lastSeenText(lastSeen: string | null, nowMs: number = Date.now()): string {
  if (!lastSeen) return "هنوز وصل نشده";
  return `${relativeTime(lastSeen, nowMs)} (${jalaliDateTime(lastSeen)})`;
}

/** نسخهٔ نرم‌افزارِ سرور + اینکه نسخهٔ تازه‌تری روی سایت هست یا نه. */
export function agentVersionView(n: Pick<ReportNode, "agent" | "agent_latest" | "update_waiting">): { text: string; tone: Tone; note: string } {
  const text = versionText(n.agent) || "نسخه نامعلوم";
  if (n.update_waiting) {
    const latest = versionText(n.agent_latest);
    return { text, tone: "warn", note: latest ? `${latest} روی سایت آماده است؛ سرور را به‌روز کنید` : "نسخهٔ تازه‌تری روی سایت آماده است؛ سرور را به‌روز کنید" };
  }
  if (!n.agent) return { text, tone: "neutral", note: "" };
  return { text, tone: "ok", note: "به‌روز است" };
}

export const SERVICE_LABELS: Record<string, string> = {
  comfyui: "ComfyUI",
  comfy_bridge: "پلِ ComfyUI",
  photo: "ویرایشگرِ عکس",
  video: "ویرایشگرِ ویدیو",
  voice: "صدا",
  ollama: "Ollama",
  blender: "سه‌بعدی",
};

export const AUDIO_LABELS: Record<string, string> = {
  speech: "گفتار",
  moss: "گفتارِ MOSS",
  sfx: "صدای محیط و افکت",
  music: "موسیقی",
  clone: "کلونِ صدا",
};

export function serviceChips(services: Record<string, boolean>): { key: string; label: string; on: boolean }[] {
  return Object.keys(SERVICE_LABELS).map((k) => ({ key: k, label: SERVICE_LABELS[k], on: Boolean(services[k]) }));
}

export function meterTone(pct: number | null | undefined): Tone {
  if (typeof pct !== "number" || !Number.isFinite(pct)) return "neutral";
  return pct >= 90 ? "bad" : pct >= 70 ? "warn" : "ok";
}

export type ResourceRow = { key: string; label: string; value: string; pct: number | null; tone: Tone };

/** ردیف‌های «منابعِ الان»؛ چیزی که عاملِ سرور نفرستاده «نامعلوم» نشان داده می‌شود (عاملِ قدیمی دیسک و دمای GPU را نمی‌فرستد). */
export function resourceRows(n: Pick<ReportNode, "resources" | "resources_known">): ResourceRow[] {
  const r = n.resources;
  const k = n.resources_known;
  const rows: ResourceRow[] = [];
  rows.push({
    key: "ram",
    label: "RAM",
    value: k.ram ? `${fmtMb((r.ram_total_mb ?? 0) - (r.ram_free_mb ?? 0))} از ${fmtMb(r.ram_total_mb)}` : "نامعلوم",
    pct: k.ram ? r.ram_used_pct : null,
    tone: k.ram ? meterTone(r.ram_used_pct) : "neutral",
  });
  rows.push({
    key: "vram",
    label: "VRAM",
    value: k.vram ? `${fmtMb(r.vram_used_mb)} از ${fmtMb(r.vram_total_mb)}` : "نامعلوم",
    pct: k.vram ? r.vram_used_pct : null,
    tone: k.vram ? meterTone(r.vram_used_pct) : "neutral",
  });
  rows.push({
    key: "gpu",
    label: "فشارِ GPU",
    value: k.gpu_util ? fmtPct(r.gpu_util_pct) : "نامعلوم",
    pct: k.gpu_util ? r.gpu_util_pct : null,
    tone: "neutral",
  });
  rows.push({
    key: "disk",
    label: "دیسک",
    value: k.disk ? `${fmtGb(r.disk_free_gb)} آزاد${r.disk_total_gb ? ` از ${fmtGb(r.disk_total_gb)}` : ""}` : "نامعلوم",
    pct: k.disk ? r.disk_used_pct : null,
    tone: k.disk ? meterTone(r.disk_used_pct) : "neutral",
  });
  rows.push({
    key: "temp",
    label: "دمای GPU",
    value: k.gpu_temp ? fmtTemp(r.gpu_temp_c) : "نامعلوم",
    pct: null,
    tone: k.gpu_temp && typeof r.gpu_temp_c === "number" ? (r.gpu_temp_c >= 85 ? "bad" : r.gpu_temp_c >= 75 ? "warn" : "ok") : "neutral",
  });
  return rows;
}

/** نمودارهایی که برای یک سرور کشیده می‌شوند. `max`: سقفِ ثابتِ محور (درصد)؛ بدونِ آن، از روی داده. */
export const CHARTS: { key: keyof SeriesMap; label: string; unit: "pct" | "gb" | "c"; max?: number }[] = [
  { key: "ram_used_pct", label: "مصرفِ RAM", unit: "pct", max: 100 },
  { key: "vram_used_pct", label: "مصرفِ VRAM", unit: "pct", max: 100 },
  { key: "gpu_util_pct", label: "فشارِ GPU", unit: "pct", max: 100 },
  { key: "disk_free_gb", label: "دیسکِ آزاد", unit: "gb" },
  { key: "gpu_temp_c", label: "دمای GPU", unit: "c" },
];

export function chartValue(unit: "pct" | "gb" | "c", v: number | null | undefined): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  return unit === "pct" ? fmtPct(v) : unit === "gb" ? fmtGb(v) : fmtTemp(v);
}

export function uptimeText(u: Uptime): string {
  if (u.pct === null || u.range_s <= 0) return "هنوز آماری ثبت نشده";
  const base = `${fmtPct(u.pct, u.pct >= 99.95 || u.pct === 0 ? 0 : 1)} روشن`;
  return u.longest_gap_s > 60 ? `${base} · طولانی‌ترین خاموشی ${humanDuration(u.longest_gap_s)}` : base;
}

export function uptimeNote(u: Uptime): string {
  return u.partial && u.since ? `آمارِ روشن/خاموش از ${jalaliDateTime(u.since)} شروع شده است.` : "";
}

// ───────────────────────────────────────────────────────────── آمارِ کارها

export const STAT_COLUMNS = ["نوعِ کار", "تعداد", "موفق", "ناموفق", "لغو", "میانگینِ اجرا", "میانگینِ انتظار در صف"] as const;

export function successRateText(s: Pick<JobStat, "success_rate" | "success" | "failed">): string {
  return s.success_rate === null ? "—" : `${fmtPct(s.success_rate)} موفق`;
}

export function successTone(s: Pick<JobStat, "success_rate">): Tone {
  if (s.success_rate === null) return "neutral";
  return s.success_rate >= 95 ? "ok" : s.success_rate >= 80 ? "warn" : "bad";
}

export type SummaryTile = { key: string; label: string; value: string; hint: string; tone: Tone };

/** کاشی‌های بالای صفحه. `nodes` = سرورهایی که در گزارش آمده‌اند. */
export function summaryTiles(data: Pick<ReportData, "nodes" | "jobs" | "errors" | "queue_now">): SummaryTile[] {
  const enabled = data.nodes.filter((n) => n.enabled);
  const online = enabled.filter((n) => n.online).length;
  const t = data.jobs.totals;
  return [
    {
      key: "nodes",
      label: "سرورِ روشن",
      value: `${toFa(online)} از ${toFa(enabled.length)}`,
      hint: enabled.length === 0 ? "هنوز سروری ثبت نشده" : online === 0 ? "همهٔ سرورها خاموش‌اند" : "",
      tone: enabled.length === 0 ? "neutral" : online === 0 ? "bad" : online < enabled.length ? "warn" : "ok",
    },
    {
      key: "jobs",
      label: "کار در این بازه",
      value: toFa(t.count),
      hint: t.success_rate === null ? "هنوز کارِ تمام‌شده‌ای نیست" : successRateText(t),
      tone: t.count === 0 ? "neutral" : successTone(t),
    },
    {
      key: "run",
      label: "میانگینِ زمانِ اجرا",
      value: runDuration(t.avg_run_s),
      hint: t.avg_run_s === null ? "" : "فقط کارهای تمام‌شده",
      tone: "neutral",
    },
    {
      key: "wait",
      label: "میانگینِ انتظار در صف",
      value: runDuration(t.avg_wait_s),
      hint: data.queue_now.waiting > 0 ? `الان ${toFa(data.queue_now.waiting)} کار منتظر است` : "الان صف خالی است",
      tone: "neutral",
    },
    {
      key: "errors",
      label: "خطا در این بازه",
      value: toFa(data.errors.length),
      hint: data.errors.length >= 50 ? "فقط ۵۰ موردِ اخیر نشان داده می‌شود" : data.errors.length === 0 ? "خطایی نیست" : "",
      tone: data.errors.length === 0 ? "ok" : "bad",
    },
  ];
}

// ───────────────────────────────────────────────────────────── خطا و لاگ

export function levelLabel(level: string): string {
  const l = (level || "").toUpperCase();
  if (l === "ERROR" || l === "CRITICAL" || l === "FATAL") return "خطا";
  if (l === "WARNING" || l === "WARN") return "هشدار";
  if (l === "DEBUG") return "جزئیات";
  return "اطلاع";
}

export function levelTone(level: string): Tone {
  const l = (level || "").toUpperCase();
  if (l === "ERROR" || l === "CRITICAL" || l === "FATAL") return "bad";
  if (l === "WARNING" || l === "WARN") return "warn";
  return "neutral";
}

export function errorSourceLabel(source: string): string {
  return source === "job" ? "کارِ ناموفق" : "لاگِ سرور";
}

export function pageInfo(total: number, offset: number, shown: number): string {
  if (total <= 0 || shown <= 0) return "موردی نیست";
  return `${toFa(offset + 1)} تا ${toFa(offset + shown)} از ${toFa(total)}`;
}

export function logsTruncatedNote(keptPerNode: number): string {
  return `از هر سرور فقط ${toFa(keptPerNode)} خطِ آخر در سایت نگه داشته می‌شود.`;
}

// ───────────────────────────────────────────────────────────── دانلود

export function downloadProgressText(d: Pick<DownloadActive, "percent" | "bytes_done" | "bytes_total" | "speed_bps" | "eta_s" | "items_done" | "items_total">): string {
  const parts: string[] = [];
  if (d.percent !== null) parts.push(fmtPct(d.percent));
  if (d.bytes_total) parts.push(`${fmtBytes(d.bytes_done)} از ${fmtBytes(d.bytes_total)}`);
  const sp = fmtSpeed(d.speed_bps);
  if (sp) parts.push(sp);
  if (d.eta_s !== null && d.eta_s > 0) parts.push(`حدودِ ${humanDuration(d.eta_s)} مانده`);
  if (d.items_total) parts.push(`${toFa(d.items_done ?? 0)} از ${toFa(d.items_total)} فایل`);
  return parts.length ? parts.join(" · ") : "در حالِ آماده‌سازی…";
}

export function downloadStateTone(state: string): Tone {
  return state === "COMPLETED" ? "ok" : state === "FAILED" ? "bad" : state === "CANCELLED" ? "neutral" : "brand";
}

/** برای دانلودِ زمان‌بندی‌شده: «زمان‌بندی: بازهٔ ۰۲:۰۰-۰۷:۰۰ (وقتِ تهران)». */
export function scheduleText(d: { scheduled_for: string | null; window: string }): string {
  const parts: string[] = [];
  if (d.scheduled_for) parts.push(`شروعِ زمان‌بندی‌شده ${jalaliDateTime(d.scheduled_for)}`);
  if (d.window) parts.push(`فقط در بازهٔ ${toFa(d.window)} (وقتِ تهران)`);
  return parts.join(" · ");
}

// ───────────────────────────────────────────────────────────── به‌روزرسانی

/** هر ۳۰ ثانیه، و فقط وقتی زبانهٔ مرورگر دیده می‌شود. */
export const POLL_MS = 30_000;

export function shouldPoll(hidden: boolean, inflight: boolean): boolean {
  return !hidden && !inflight;
}

// ───────────────────────────────────────────────────────────── متن‌های ثابتِ صفحه

export const TABS = [
  { key: "overview", label: "سرورها" },
  { key: "jobs", label: "آمارِ کارها" },
  { key: "errors", label: "خطاها" },
  { key: "logs", label: "لاگ‌ها" },
  { key: "downloads", label: "دانلودها" },
] as const;
export type TabKey = (typeof TABS)[number]["key"];

export const TEXT = {
  title: "گزارشِ سرورهای پردازش",
  subtitle: "وضعیتِ روشن/خاموش، منابع، کارها، خطاها، لاگ و دانلودِ سرورهای پردازش، برای هر بازهٔ زمانی؛ با خروجیِ CSV برای Excel.",
  allNodes: "همهٔ سرورها",
  nodeFilter: "سرور",
  refresh: "تازه‌سازی",
  updatedAt: "آخرین به‌روزرسانی",
  noNodes: "هنوز سرورِ پردازشی ثبت نشده است؛ بعد از اجرای START.bat روی کامپیوترِ گرافیکی، سرور این‌جا پیدا می‌شود.",
  timeline: "روشن/خاموش",
  timelineHint: "هر نوارِ رنگی یک نوبتِ وصل‌بودنِ سرور است؛ جای خالی یعنی سرور خاموش یا بی‌اینترنت بوده.",
  now: "اکنون",
  resourcesNow: "منابعِ الان",
  chartsTitle: "نمودارِ منابع",
  noSeries: "هنوز نمونه‌ای برای این بازه ثبت نشده.",
  models: "مدل‌های نصب‌شده",
  noModels: "گزارشی از مدل‌های این سرور نرسیده.",
  sessions: "نوبت‌های اتصال",
  noSessions: "در این بازه نوبتِ اتصالی ثبت نشده.",
  jobsByKind: "بر اساسِ نوعِ کار",
  jobsByNode: "بر اساسِ سرور",
  noJobs: "در این بازه کاری ثبت نشده.",
  noErrors: "در این بازه خطایی نبوده.",
  errorTop: "بیشترین دلیل‌ها",
  rawError: "متنِ خطا",
  advice: "پیشنهاد",
  copy: "کپی",
  copied: "کپی شد",
  logsSearch: "جستجو در لاگ‌ها",
  logsEmpty: "لاگی با این فیلتر پیدا نشد.",
  prev: "قبلی",
  next: "بعدی",
  downloadsActive: "در حالِ دانلود",
  downloadsWaiting: "منتظر یا زمان‌بندی‌شده",
  downloadsHistory: "سابقهٔ دانلودها",
  noActiveDownloads: "الان دانلودی در جریان نیست.",
  noWaitingDownloads: "دانلودِ منتظر یا زمان‌بندی‌شده‌ای نیست.",
  noDownloadHistory: "در این بازه دانلودی ثبت نشده.",
  csv: "خروجی CSV",
  csvBusy: "در حالِ ساختنِ فایل…",
  settingsTitle: "نگه‌داریِ آمار",
  retentionLabel: "نگه‌داریِ آمار (روز)",
  retentionHint: "نمونه‌های منابع و نوبت‌های اتصال به‌اندازهٔ این روزها می‌مانند و قدیمی‌ترها خودکار پاک می‌شوند. نمونه‌ها تا ۴۸ ساعت دقیقه‌ای و بعد از آن ۱۵ دقیقه‌ای ذخیره می‌شوند.",
  retentionSave: "ذخیره",
  retentionSaved: "ذخیره شد.",
  apply: "اعمال",
  customFrom: "از تاریخ (شمسی)",
  customTo: "تا تاریخ (شمسی)",
  customPlaceholder: "۱۴۰۵/۰۸/۱۰",
  customHint: "تاریخ را شمسی بنویسید؛ خالی‌گذاشتنِ «تا» یعنی امروز. حداکثر ۹۰ روز.",
  versions: "نسخهٔ نرم‌افزارِ سرورها",
  siteVersion: "نسخهٔ سایت",
  queueLink: "صفِ پردازش",
  serversLink: "سرورهای پردازش",
} as const;

/** همهٔ متن‌های ثابتِ فارسیِ صفحه (برای آزمونِ «انگلیسیِ سرگردان ندارد»). */
export function allStaticTexts(): string[] {
  return [
    ...Object.values(TEXT),
    ...PRESETS.map((p) => p.label),
    ...LEVEL_OPTIONS.map((o) => o.label),
    ...TABS.map((t) => t.label),
    ...Object.values(CSV_LABELS),
    ...Object.values(SERVICE_LABELS),
    ...Object.values(AUDIO_LABELS),
    ...CHARTS.map((c) => c.label),
    ...STAT_COLUMNS,
  ];
}
