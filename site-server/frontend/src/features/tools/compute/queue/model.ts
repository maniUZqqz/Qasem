/**
 * منطقِ خالصِ صفحهٔ «صفِ پردازش» و نشانِ بالای صفحه (بدونِ React و DOM، تا بدونِ مرورگر آزمون شود).
 *
 * هر چیزی که شکلِ جملهٔ فارسی، رنگِ برچسب یا پارامترِ درخواست را تعیین می‌کند اینجاست؛ خودِ صفحه فقط نمایش می‌دهد.
 * آزمون: frontend/tests/compute-queue.test.ts
 */

export type Tone = "neutral" | "brand" | "ok" | "warn" | "bad" | "info";

/** گروهِ نمایشیِ کار — همان `group` ِ API */
export type Group = "waiting" | "running" | "done" | "failed" | "cancelled";
export type Tab = Group | "all";

export type RetryMode = "" | "requeue" | "consumer" | "owner";

export type WaitReason =
  | "no_node"
  | "busy"
  | "scheduled"
  | "window"
  | "model"
  | "pinned_offline"
  | "pinned_gone"
  | "hold"
  | "";

export type QueueJob = {
  uid: string;
  kind: string;
  kind_label: string;
  title: string;
  state: string;
  state_label: string;
  group: Group;
  /** جملهٔ آمادهٔ فارسی؛ همان‌طور که هست نشان داده می‌شود */
  status_text: string;
  wait_reason: WaitReason;
  position: number;
  ahead: number;
  waiting_s: number | null;
  waiting_text: string;
  waited_s: number | null;
  run_s: number | null;
  created: string;
  queued_at: string | null;
  claimed: string | null;
  finished: string | null;
  node: string | null;
  node_wanted: string;
  attempts: number;
  max_attempts: number;
  lost_count: number;
  progress: number;
  message: string;
  error: string;
  origin: string;
  store: string | null;
  can_cancel: boolean;
  can_retry: boolean;
  /** «پردازشِ دوباره» چه می‌کند: همین کار دوباره در صف / ردیفِ صفحه هم برمی‌گردد / کارِ اصلیِ فروشگاه از اول */
  retry_mode?: RetryMode;
  /** جملهٔ فارسی: «پردازشِ دوباره» چه می‌کند، یا چرا نمی‌شود */
  retry_hint?: string;
  /** کارِ فروشگاه که این کار را ساخت (apps.jobs) */
  job_ref?: number | null;
  /** فقط در پاسخِ «پردازشِ دوباره» */
  notice?: string;
  scheduled_for: string | null;
  window: string;
  category: string;
  capability: string;
  parked: boolean;
  model: string;
};

export type QueueNode = {
  id: number;
  name: string;
  online: boolean;
  enabled: boolean;
  last_seen: string | null;
  agent: string | null;
};

export type QueueCounts = Record<Tab, number>;

export type QueueListing = {
  counts: QueueCounts;
  total: number;
  offset: number;
  limit: number;
  nodes: QueueNode[];
  jobs: QueueJob[];
};

export type QueueSummary = {
  waiting: number;
  parked: number;
  running: number;
  scheduled: number;
  failed_24h: number;
  nodes_total: number;
  nodes_online: number;
  oldest_wait_s: number | null;
  oldest_wait_text: string;
  text: string;
};

// ───────────────────────────────────────────────────────────── اعداد و زمان

/** ۱۲۳ → «۱۲۳» */
export function toFa(value: number | string): string {
  return String(value).replace(/[0-9]/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[Number(d)]);
}

/**
 * مدتِ زمان به زبانِ آدم — همان قاعدهٔ `human_duration` ِ بک‌اند، تا متنِ صفحه با متنِ آمادهٔ سرور یکی باشد.
 * «۴۵ ثانیه»، «۷ دقیقه»، «۳ ساعت و ۲۰ دقیقه»، «۲ روز». ورودیِ خالی یا نامعتبر ⇒ «».
 */
export function humanDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "";
  const s = Math.floor(Math.max(0, seconds));
  if (s < 60) return `${toFa(s)} ثانیه`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${toFa(m)} دقیقه`;
  const h = Math.floor(m / 60);
  const rest = m % 60;
  if (h < 48) return `${toFa(h)} ساعت` + (rest ? ` و ${toFa(rest)} دقیقه` : "");
  return `${toFa(Math.floor(h / 24))} روز`;
}

/** «۳ ساعت پیش» / «۴ دقیقه دیگر» / «همین الان». ورودیِ خالی یا نامعتبر ⇒ «—». */
export function relativeTime(iso: string | null | undefined, nowMs: number = Date.now()): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "—";
  const diff = Math.round((nowMs - t) / 1000);
  const abs = Math.abs(diff);
  if (abs < 10) return "همین الان";
  const body =
    abs < 60
      ? `${toFa(abs)} ثانیه`
      : abs < 3600
        ? `${toFa(Math.floor(abs / 60))} دقیقه`
        : abs < 86400
          ? `${toFa(Math.floor(abs / 3600))} ساعت`
          : `${toFa(Math.floor(abs / 86400))} روز`;
  return diff > 0 ? `${body} پیش` : `${body} دیگر`;
}

/** تاریخ و ساعتِ کامل (شمسی، وقتِ تهران) برای نکتهٔ روی ماوس. */
export function absoluteTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  try {
    return d.toLocaleString("fa-IR", {
      timeZone: "Asia/Tehran",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return d.toISOString();
  }
}

// ───────────────────────────────────────────────────────────── سرورها

/** «2.5» ⇒ «نسخهٔ ۲٫۵»؛ اگر عددی در متن نبود ⇒ «». */
export function versionText(agent: string | null | undefined): string {
  const m = /\d+(?:\.\d+)*/.exec(String(agent ?? ""));
  if (!m) return "";
  return `نسخهٔ ${toFa(m[0]).replace(/\./g, "٫")}`;
}

/** «آخرین حضور ۳ دقیقه پیش» / «هنوز وصل نشده» */
export function seenText(lastSeen: string | null | undefined, nowMs: number = Date.now()): string {
  const rel = relativeTime(lastSeen, nowMs);
  return rel === "—" ? "هنوز وصل نشده" : `آخرین حضور ${rel}`;
}

export type NodeView = {
  state: "online" | "offline" | "disabled";
  label: string;
  seen: string;
  version: string;
};

export function nodeView(n: QueueNode, nowMs: number = Date.now()): NodeView {
  const state = !n.enabled ? "disabled" : n.online ? "online" : "offline";
  return {
    state,
    label: state === "online" ? "روشن" : state === "offline" ? "خاموش" : "غیرفعال",
    seen: seenText(n.last_seen, nowMs),
    version: versionText(n.agent),
  };
}

export type QueueWarning = { title: string; steps: string[] };

/**
 * هشدارِ «سرور خاموش است»: فقط وقتی کاری منتظر است و هیچ سرورِ فعالی روشن نیست.
 * (اگر کاری منتظر نیست، خاموش بودنِ سرور مشکلی نیست و هشداری لازم نیست.)
 */
export function queueWarning(nodes: QueueNode[], waiting: number): QueueWarning | null {
  if (!(waiting > 0)) return null;
  const enabled = nodes.filter((n) => n.enabled);
  if (enabled.some((n) => n.online)) return null;
  // «۳ کار … آن‌اند» ولی «۱ کار … آن است» (نیم‌فاصلهٔ «آن‌اند» با ‌)
  const tail = waiting === 1 ? "آن است" : "آن‌اند";
  if (enabled.length === 0) {
    return {
      title: `هیچ سرورِ پردازشِ فعالی نیست؛ ${toFa(waiting)} کار منتظرِ وصل شدنِ یک سرور ${waiting === 1 ? "است" : "هستند"}`,
      steps: [
        "در صفحهٔ «سرورهای پردازش» یک سرور اضافه یا فعال کنید",
        "کامپیوترِ گرافیکی را روشن کنید",
        "فایلِ START.bat را اجرا کنید",
      ],
    };
  }
  return {
    title: `سرورِ پردازش خاموش است؛ ${toFa(waiting)} کار منتظرِ روشن شدنِ ${tail}`,
    steps: ["کامپیوترِ گرافیکی را روشن کنید", "فایلِ START.bat را اجرا کنید"],
  };
}

// ───────────────────────────────────────────────────────────── تب‌ها و فیلترها

export const TABS: { key: Tab; label: string }[] = [
  { key: "waiting", label: "منتظر" },
  { key: "running", label: "در حال اجرا" },
  { key: "done", label: "تمام‌شده" },
  { key: "failed", label: "ناموفق" },
  { key: "cancelled", label: "لغوشده" },
  { key: "all", label: "همه" },
];

/** تبِ پیش‌فرض: «منتظر» اگر کاری منتظر است، وگرنه «همه». */
export function defaultTab(counts: Pick<QueueCounts, "waiting"> | null | undefined): Tab {
  return counts && counts.waiting > 0 ? "waiting" : "all";
}

/**
 * گزینه‌های «نوعِ کار». `kind` پیشوندِ نوعِ کار در بک‌اند است (فقط یک پیشوند)؛ «دانلودها» با `category` جدا می‌شود.
 * ویدیو دو پیشوند دارد (video.* و edit.*) که API با هم نمی‌گیرد، برای همین دو گزینهٔ جدا.
 */
export const KIND_OPTIONS: { key: string; label: string; kind?: string; category?: string }[] = [
  { key: "", label: "همهٔ کارها" },
  { key: "photo", label: "عکس", kind: "photo" },
  { key: "video", label: "ویدیو (تدوین)", kind: "video" },
  { key: "edit", label: "ویرایشگرِ ویدیو (رندر و ردیابی)", kind: "edit" },
  { key: "voice", label: "صدا", kind: "voice" },
  { key: "comfy", label: "تولیدِ تصویر یا ویدیو (ComfyUI)", kind: "comfy" },
  { key: "ollama", label: "هوش مصنوعی (متن)", kind: "ollama" },
  { key: "downloads", label: "دانلودها", category: "download" },
  { key: "node", label: "کارِ خودِ سرور", kind: "node" },
];

export const PAGE_SIZE = 100;
/** سقفِ `limit` در API */
export const MAX_SIZE = 500;

export function kindOption(key: string) {
  return KIND_OPTIONS.find((o) => o.key === key) ?? KIND_OPTIONS[0];
}

/** رشتهٔ پرس‌وجو برای GET /compute/queue/ — ترتیبِ ثابت، تا کلیدِ «داده مالِ کدام درخواست است» پایدار بماند. */
export function buildQuery(p: { tab: Tab; kindKey: string; q: string; limit: number; offset?: number }): string {
  const opt = kindOption(p.kindKey);
  const params = new URLSearchParams();
  params.set("state", p.tab);
  if (opt.kind) params.set("kind", opt.kind);
  if (opt.category) params.set("category", opt.category);
  const q = p.q.trim();
  if (q) params.set("q", q.slice(0, 80));
  params.set("limit", String(Math.min(MAX_SIZE, Math.max(1, Math.floor(p.limit)))));
  params.set("offset", String(Math.max(0, Math.floor(p.offset ?? 0))));
  return params.toString();
}

/**
 * «لغوِ همهٔ منتظرها» فقط همان چیزی را لغو می‌کند که کاربر در فهرست می‌بیند. API فقط پیشوندِ نوع را می‌شناسد؛
 * با جستجو یا فیلترِ «دانلودها» دکمه‌ای که «همه» را لغو کند، کارهای دیگر را هم می‌برد — پس در آن حالت‌ها خاموش است.
 */
export function bulkCancelPlan(kindKey: string, q: string): { allowed: boolean; kind: string; hint: string } {
  const opt = kindOption(kindKey);
  if (q.trim() || opt.category) {
    return { allowed: false, kind: "", hint: "برای لغوِ گروهی، جستجو و فیلترِ دانلودها را بردارید." };
  }
  return { allowed: true, kind: opt.kind ?? "", hint: "" };
}

export function bulkCancelConfirm(count: number, kindKey: string): string {
  const opt = kindOption(kindKey);
  const scope = opt.kind ? ` از نوعِ «${opt.label}»` : "";
  return `همهٔ ${toFa(count)} کارِ منتظر${scope} لغو شود؟ کارهایی که الان در حال پردازش‌اند دست نمی‌خورند.`;
}

export function cancelConfirm(job: Pick<QueueJob, "title" | "group">): string {
  if (job.group === "running") {
    return `«${job.title}» همین حالا در حال پردازش است. لغو شود؟ کار در گامِ بعدی متوقف می‌شود.`;
  }
  return `«${job.title}» از صف برداشته شود؟`;
}

export function cancelNotice(job: Pick<QueueJob, "group">): string {
  return job.group === "running" ? "درخواستِ لغو ثبت شد؛ کار در گامِ بعدی متوقف می‌شود." : "کار لغو شد.";
}

export const RETRY_NOTICE = "کار دوباره در صف گذاشته شد.";

/** متنِ دکمه — مالک «پردازشِ دوباره» گفت */
export const RETRY_LABEL = "پردازشِ دوباره";

/** پیامِ بعد از «پردازشِ دوباره»: جملهٔ خودِ سرور (مثلاً «کارِ اصلی … دوباره فرستاده شد») یا پیامِ پیش‌فرض */
export function retryNotice(updated: Pick<QueueJob, "notice"> | null | undefined): string {
  return (updated?.notice || "").trim() || RETRY_NOTICE;
}

/**
 * «پردازشِ دوبارهٔ همه» فقط در تب‌های «ناموفق» و «لغوشده»، و فقط برای همان چیزی که دیده می‌شود: API پیشوندِ نوع را می‌شناسد،
 * پس با جستجو یا فیلترِ «دانلودها» خاموش است (مثلِ «لغوِ همهٔ منتظرها»).
 */
export function bulkRetryPlan(tab: Tab, kindKey: string, q: string): { allowed: boolean; state: string; kind: string; hint: string } {
  const state = tab === "failed" ? "FAILED" : tab === "cancelled" ? "CANCELLED" : "";
  if (!state) return { allowed: false, state: "", kind: "", hint: "" };
  const opt = kindOption(kindKey);
  if (q.trim() || opt.category) {
    return { allowed: false, state, kind: "", hint: "برای پردازشِ دوبارهٔ گروهی، جستجو و فیلترِ دانلودها را بردارید." };
  }
  return { allowed: true, state, kind: opt.kind ?? "", hint: "" };
}

export function bulkRetryConfirm(count: number, tab: Tab, kindKey: string): string {
  const opt = kindOption(kindKey);
  const scope = opt.kind ? ` از نوعِ «${opt.label}»` : "";
  const what = tab === "cancelled" ? "لغوشده" : "ناموفق";
  return `همهٔ کارهای ${what}${scope} (${toFa(count)} کار) دوباره پردازش شوند؟ کارهایی که از صفحهٔ یک فروشگاه آمده‌اند از اول دوباره فرستاده می‌شوند.`;
}

export type BulkRetryResult = { retried: number; skipped: number; errors: string[] };

export function bulkRetryNotice(r: BulkRetryResult): string {
  const parts = [r.retried > 0 ? `${toFa(r.retried)} کار دوباره فرستاده شد.` : "هیچ کاری دوباره فرستاده نشد."];
  if (r.skipped > 0) parts.push(`${toFa(r.skipped)} کار از این‌جا دوباره اجرا نمی‌شود (از صفحهٔ خودش دوباره بزنید).`);
  if (r.errors?.length) parts.push(r.errors[0]);
  return parts.join(" ");
}

// ───────────────────────────────────────────────────────────── کارهای فروشگاه‌ها (apps.jobs) که ناموفق/لغو شدند

export type StoreJob = {
  id: number;
  type: string;
  type_label: string;
  state: "FAILED" | "CANCELLED" | string;
  state_label: string;
  store: string | null;
  store_id: number;
  error: string;
  retry_count: number;
  can_retry: boolean;
  created: string;
  updated: string;
};

export type StoreJobsListing = { total: number; jobs: StoreJob[]; counts: { FAILED: number; CANCELLED: number } };

export function storeJobsTitle(l: Pick<StoreJobsListing, "counts">): string {
  const f = l.counts?.FAILED ?? 0;
  const c = l.counts?.CANCELLED ?? 0;
  if (!f && !c) return "هیچ کارِ ناموفق یا لغوشده‌ای در فروشگاه‌ها نیست (۷ روزِ اخیر).";
  const bits = [f ? `${toFa(f)} ناموفق` : "", c ? `${toFa(c)} لغوشده` : ""].filter(Boolean);
  return `کارهای فروشگاه‌ها در ۷ روزِ اخیر: ${bits.join(" و ")}`;
}

/** آخرین خطِ خطا، کوتاه — برای زیرِ عنوانِ ردیف */
export function shortError(text: string | null | undefined, max = 160): string {
  const lines = String(text ?? "").trim().split(/\n+/);
  const last = lines[lines.length - 1] ?? "";
  return last.length > max ? `${last.slice(0, max - 1)}…` : last;
}

export function emptyText(tab: Tab, filtered: boolean): string {
  if (filtered) return "کاری با این فیلتر پیدا نشد.";
  switch (tab) {
    case "waiting":
      return "صف خالی است؛ هیچ کاری منتظرِ سرورِ پردازش نیست.";
    case "running":
      return "الان هیچ کاری در حال پردازش نیست.";
    case "done":
      return "هنوز کارِ تمام‌شده‌ای نیست.";
    case "failed":
      return "هیچ کارِ ناموفقی نیست.";
    case "cancelled":
      return "هیچ کارِ لغوشده‌ای نیست.";
    default:
      return "هنوز هیچ کاری به سرورِ پردازش نرفته است.";
  }
}

// ───────────────────────────────────────────────────────────── ردیفِ کار

/** رنگِ برچسبِ وضعیت */
export function statusTone(j: Pick<QueueJob, "group" | "wait_reason" | "ahead">): Tone {
  switch (j.group) {
    case "running":
      return "brand";
    case "done":
      return "ok";
    case "failed":
      return "bad";
    case "cancelled":
      return "neutral";
    default:
      switch (j.wait_reason) {
        case "no_node":
        case "pinned_offline":
          return "warn";
        case "pinned_gone":
          return "bad";
        case "scheduled":
        case "window":
        case "model":
          return "info";
        case "busy":
          // نفرِ اولِ صف که فقط منتظرِ نوبت است، یک اشاره بیشتر می‌گیرد
          return j.ahead === 0 ? "brand" : "neutral";
        default:
          return "neutral";
      }
  }
}

/**
 * ستونِ «جایگاه». `position` جایگاه در صفِ همان توانایی است (کارِ عکس پشتِ کارِ صدا نمی‌ماند)،
 * پس «۲ از ۵» فقط وقتی درست است که تعدادِ کلِ آن صف را بدانیم (`capTotal`)؛ وگرنه فقط «۲».
 */
export function positionView(
  j: Pick<QueueJob, "group" | "position" | "ahead">,
  capTotal?: number,
): { main: string; sub: string } {
  if (j.group !== "waiting" || !(j.position > 0)) return { main: "—", sub: "" };
  const main = capTotal && capTotal >= j.position ? `${toFa(j.position)} از ${toFa(capTotal)}` : toFa(j.position);
  return { main, sub: j.ahead > 0 ? `${toFa(j.ahead)} کار جلوتر` : "اولِ صف" };
}

/** تعدادِ کارهای منتظر در هر توانایی، از روی فهرستِ بارگذاری‌شده — فقط وقتی فهرست کامل است معنی دارد. */
export function capabilityTotals(jobs: Pick<QueueJob, "group" | "capability">[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const j of jobs) {
    if (j.group === "waiting") out[j.capability] = (out[j.capability] ?? 0) + 1;
  }
  return out;
}

/** ستونِ «منتظر مانده»: برای منتظرها مدتِ انتظار، برای در حال اجرا مدتِ اجرا تا الان، برای پایان‌یافته‌ها مدتِ اجرا. */
export function waitView(
  j: Pick<QueueJob, "group" | "wait_reason" | "waiting_text" | "waiting_s" | "waited_s" | "run_s" | "claimed">,
  nowMs: number = Date.now(),
): { main: string; sub: string } {
  const waited = humanDuration(j.waited_s);
  if (j.group === "waiting") {
    // کارِ زمان‌بندی‌شده «منتظر» نیست؛ هنوز وقتش نرسیده
    if (j.wait_reason === "scheduled" || j.wait_reason === "window") return { main: "—", sub: "" };
    return { main: j.waiting_text || humanDuration(j.waiting_s) || "—", sub: "" };
  }
  if (j.group === "running") {
    const t = j.claimed ? Date.parse(j.claimed) : NaN;
    const run = Number.isFinite(t) ? humanDuration((nowMs - t) / 1000) : "";
    return { main: run ? `اجرا: ${run}` : "—", sub: waited ? `انتظار: ${waited}` : "" };
  }
  const run = humanDuration(j.run_s);
  return { main: run ? `اجرا: ${run}` : "—", sub: waited ? `انتظار: ${waited}` : "" };
}

const ORIGINS: Record<string, string> = {
  panel: "پنل",
  park: "کارِ منتظرِ صفحه",
  photoedit: "ویرایشِ عکس",
  photoexact: "ویرایشِ دقیقِ عکس",
  photogenfill: "پرکردنِ هوشمندِ عکس",
  photosubject: "انتخابِ سوژهٔ عکس",
  regen: "ساختِ دوبارهٔ ویدیو",
  voice_clone_test: "آزمونِ صدای کلون‌شده",
  voice_models: "مدل‌های صدا",
  ai_models: "مدل‌های هوش مصنوعی",
  downloads: "دانلودها",
};

export function originLabel(origin: string | null | undefined): string {
  if (!origin) return "";
  return ORIGINS[origin] ?? origin;
}

/** هشت حرفِ اولِ شناسه — برای ارجاع به پشتیبانی کافی است */
export function shortUid(uid: string): string {
  return uid.slice(0, 8);
}

export function progressPercent(p: number | null | undefined): number {
  if (typeof p !== "number" || !Number.isFinite(p)) return 0;
  return Math.max(0, Math.min(100, Math.round(p * 100)));
}

// ───────────────────────────────────────────────────────────── نشانِ بالای صفحه

/** پاسخِ خراب یا ناقص ⇒ null (نشان فقط ساکت می‌ماند). */
export function parseSummary(raw: unknown): QueueSummary | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  if (typeof r.waiting !== "number" || typeof r.running !== "number") return null;
  const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : 0);
  return {
    waiting: Math.max(0, r.waiting),
    parked: num(r.parked),
    running: Math.max(0, r.running),
    scheduled: num(r.scheduled),
    failed_24h: num(r.failed_24h),
    nodes_total: num(r.nodes_total),
    nodes_online: num(r.nodes_online),
    oldest_wait_s: typeof r.oldest_wait_s === "number" ? r.oldest_wait_s : null,
    oldest_wait_text: typeof r.oldest_wait_text === "string" ? r.oldest_wait_text : "",
    text: typeof r.text === "string" ? r.text : "",
  };
}

export type BadgeView = {
  tone: "warn" | "neutral";
  waiting: number;
  running: number;
  title: string;
};

/**
 * نشانِ کنارِ ساعتِ هدر: پنهان وقتی نه منتظری هست نه در حال اجرایی؛
 * زردِ هشدار وقتی کار منتظر است و هیچ سروری روشن نیست؛ وگرنه خنثی.
 */
export function badgeView(s: QueueSummary | null | undefined): BadgeView | null {
  if (!s || (s.waiting <= 0 && s.running <= 0)) return null;
  const parts: string[] = [s.text || (s.waiting > 0 ? `${toFa(s.waiting)} کار در صف` : "صف خالی است")];
  if (s.waiting > 0 && s.oldest_wait_text) parts.push(`قدیمی‌ترینِ آن‌ها ${s.oldest_wait_text} منتظر مانده`);
  if (s.running > 0) parts.push(`${toFa(s.running)} کار در حال پردازش`);
  return {
    tone: s.waiting > 0 && s.nodes_online === 0 ? "warn" : "neutral",
    waiting: s.waiting,
    running: s.running,
    title: parts.join(" — "),
  };
}

/** نمایشِ شمارنده: بالای ۹۹ ⇒ «۹۹+» تا نشان روی گوشی پهن نشود */
export function badgeCount(n: number): string {
  return n > 99 ? "۹۹+" : toFa(n);
}
