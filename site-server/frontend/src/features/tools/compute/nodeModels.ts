/**
 * منطقِ خالصِ صفحهٔ «دانلودِ مدل‌ها» و کارتِ «مدل‌های سرورِ پردازش» (بدونِ React، تا بی مرورگر آزمون شود).
 *
 * داده از GET /compute/models/ (apps.compute.model_packages): برای هر سرور، همهٔ بسته‌های دانلودیِ آن — تصویر (FLUX/SDXL)، ویدیو،
 * بزرگ‌کردن و ترمیم، کنترل و ثبات، عمق، صدا، حذفِ پس‌زمینه — با مجوز، جای‌گیریِ VRAM، «به چه کاری می‌آید»، «به چه نیاز دارد»،
 * وضعیتِ نصب و «دانلودِ خودکار»؛ و مدل‌های Ollama کنارشان. دانلودِ بسته: POST /compute/nodes/<id>/models/download/ ؛ تنظیمِ دانلودِ
 * خودکار: POST /compute/models/auto/.
 * آزمون: frontend/tests/compute-node-models.test.ts
 */

export type PackageState = "installed" | "missing" | "downloading" | "waiting_window" | "queued" | "unknown";
export type LicenseClass = "open" | "restricted" | "noncommercial";
export type VramFit = "" | "full" | "offload" | "tight";
export type AutoMode = "default" | "on" | "off" | "never" | "manual";

export type FeatureRef = { key: string; label: string; switch: boolean };
export type NeedRef = { key: string; title: string; installed: boolean | null; mb: number };

export type ModelPackage = {
  key: string;
  title: string;
  title_en: string;
  note: string;
  optional: boolean;
  installed: boolean | null;
  state: PackageState;
  queued_text: string;
  total_mb: number;
  missing_mb: number | null;
  in_comfyui: number;
  license?: string;
  license_class?: LicenseClass;
  license_text?: string;
  commercial?: boolean;
  vram_fit?: VramFit;
  vram_text?: string;
  vram_note?: string;
  vram_gb?: number | null;
  features?: FeatureRef[];
  needs?: NeedRef[];
  download_mb?: number;
  fits?: boolean | null;
  needs_restart?: boolean;
  kind?: "files" | "node";
  sources?: string[];
  provenance?: string;
  auto?: { mode: AutoMode; state: string; text: string };
};

export type PackageGroup = { key: string; title: string; note: string; packages: ModelPackage[] };

export type NodeAuto = {
  enabled: boolean;
  reserve_gb: number;
  wanted: number;
  pending_mb: number;
  reported: boolean;
  states: Record<string, string>;
  why: Record<string, string>;
};

export type NodeModels = {
  node: {
    id: number;
    name: string;
    online: boolean;
    enabled: boolean;
    agent: string | null;
    last_seen: string | null;
    disk_free_mb?: number | null;
    disk_total_gb?: number | null;
  };
  reported: boolean;
  running: boolean;
  progress: {
    packages?: string[];
    bytes_done?: number;
    bytes_total?: number;
    items_done?: number;
    items_total?: number;
    current?: string;
  } | null;
  waiting: { until?: string; packages?: string[] } | null;
  error: string;
  auto?: NodeAuto;
  groups: PackageGroup[];
};

export type OllamaModel = { tag: string; label: string; size_mb: number; purpose: string; vision: boolean; installed: boolean | null };
export type OllamaPull = {
  uid: string;
  tag: string;
  label: string;
  state: string;
  final: boolean;
  percent: number;
  text: string;
  error: string;
  waiting_for_node: boolean;
  scheduled_text?: string;
};
export type OllamaView = {
  models: OllamaModel[];
  extra: OllamaModel[];
  pulls: OllamaPull[];
  pull_nodes: { id: number; name: string; online: boolean; agent: string; pull_ready: boolean }[];
  known: boolean;
  error?: string;
};

export type AutoFeature = { key: string; label: string; on: boolean; packages: { key: string; title: string }[]; size_mb: number };
export type AutoSettings = { enabled: boolean; reserve_gb: number; big_mb: number; features: AutoFeature[]; wanted: string[] };

export type ModelsListing = { nodes: NodeModels[]; ollama?: OllamaView; auto?: AutoSettings; ollama_page: string };

const FA = "۰۱۲۳۴۵۶۷۸۹";
export function toFa(v: number | string): string {
  return String(v).replace(/[0-9]/g, (d) => FA[Number(d)]);
}

/** ۴ ⇒ «۴ مگابایت»، ۱۷۰۰ ⇒ «۱٫۷ گیگابایت» */
export function sizeText(mb: number | null | undefined): string {
  if (mb === null || mb === undefined || !Number.isFinite(mb) || mb <= 0) return "";
  if (mb < 1000) return `${toFa(Math.max(1, Math.round(mb)))} مگابایت`;
  const gb = mb / 1024;
  return `${toFa(gb >= 10 ? Math.round(gb) : Math.round(gb * 10) / 10).replace(".", "٫")} گیگابایت`;
}

export type Tone = "ok" | "warn" | "info" | "brand" | "neutral" | "bad";
export type StateView = { label: string; tone: Tone };

export function stateView(p: Pick<ModelPackage, "state" | "queued_text">): StateView {
  switch (p.state) {
    case "installed":
      return { label: "نصب است", tone: "ok" };
    case "downloading":
      return { label: "در حالِ دانلود", tone: "brand" };
    case "waiting_window":
      return { label: "منتظرِ بازهٔ شبانه", tone: "info" };
    case "queued":
      return { label: p.queued_text ? `در صفِ دانلود — ${p.queued_text}` : "در صفِ دانلود", tone: "info" };
    case "missing":
      return { label: "نصب نیست", tone: "warn" };
    default:
      return { label: "سرور هنوز گزارش نداده", tone: "neutral" };
  }
}

/** بسته‌ای که می‌شود برای دانلود انتخاب کرد: نصب نیست و همین حالا در راه هم نیست. */
export function selectable(p: Pick<ModelPackage, "state">): boolean {
  return p.state === "missing" || p.state === "unknown";
}

// ───────────────────────────────────────────────────────────── مجوز، VRAM، دیسک، خودکار

/** «تجاری مجاز» / «با شرط» / «فقط غیرتجاری»؛ بسته‌ای که مجوزش گفته نشده (بستهٔ قدیمی) بی نشان می‌ماند. */
export function licenseView(p: Pick<ModelPackage, "license_class" | "license">): { label: string; tone: Tone; name: string } | null {
  const raw = (p.license ?? "").trim();
  const name = raw === "unverified" ? "نامشخص" : raw;
  switch (p.license_class) {
    case "open":
      return { label: "تجاری مجاز", tone: "ok", name };
    case "restricted":
      return { label: "با شرط", tone: "warn", name };
    case "noncommercial":
      return { label: "فقط غیرتجاری", tone: "bad", name };
    default:
      return null;
  }
}

export function isOpen(p: Pick<ModelPackage, "license_class">): boolean {
  return (p.license_class ?? "open") === "open";
}

export function vramView(p: Pick<ModelPackage, "vram_fit" | "vram_gb">): { label: string; tone: Tone } | null {
  switch (p.vram_fit) {
    case "full":
      return { label: "در ۱۲ گیگابایت جا می‌شود", tone: "ok" };
    case "offload":
      return { label: "۱۲ گیگابایت: با کمی کندی", tone: "info" };
    case "tight":
      return { label: "۱۲ گیگابایت: سنگین و کند", tone: "warn" };
    default:
      return null;
  }
}

const AUTO_STATE: Record<string, StateView> = {
  installed: { label: "خودکار — نصب شد", tone: "ok" },
  pending: { label: "خودکار — به‌زودی شروع می‌شود", tone: "brand" },
  active: { label: "خودکار — در راه", tone: "brand" },
  downloading: { label: "خودکار — در حالِ دانلود", tone: "brand" },
  waiting_window: { label: "خودکار — منتظرِ بازهٔ شبانه", tone: "info" },
  queued: { label: "خودکار — در صف", tone: "info" },
  no_disk: { label: "خودکار — جای دیسک کافی نیست", tone: "warn" },
  failed: { label: "خودکار — چند بار شکست خورد؛ فردا دوباره", tone: "warn" },
  blocked_license: { label: "فقط با دکمه (مجوز)", tone: "neutral" },
  unknown_package: { label: "خودکار — سرور هنوز این بسته را نمی‌شناسد؛ به‌روزرسانی", tone: "warn" },
};

/** نشانِ «دانلودِ خودکار» کنارِ هر بسته؛ بسته‌ای که فقط با دکمه می‌آید نشانی ندارد. */
export function autoView(p: Pick<ModelPackage, "auto" | "state">): StateView | null {
  const a = p.auto;
  if (!a) return null;
  switch (a.mode) {
    case "on":
      if (p.state === "installed") return { label: "خودکار — نصب شد", tone: "ok" };
      return AUTO_STATE[a.state] ?? { label: "خودکار — در انتظارِ سرور", tone: "brand" };
    case "off":
      return { label: "خودکار نیست", tone: "neutral" };
    case "never":
      return { label: "هرگز خودکار (مجوز)", tone: "neutral" };
    case "default":
      return { label: "پیش‌فرضِ سرور", tone: "neutral" };
    default:
      return null;
  }
}

/** «۹۳ گیگابایت خالی از ۵۱۱» */
export function diskText(n: Pick<NodeModels["node"], "disk_free_mb" | "disk_total_gb">): string {
  if (n.disk_free_mb === null || n.disk_free_mb === undefined) return "";
  const free = sizeText(n.disk_free_mb);
  return n.disk_total_gb ? `${free} خالی از ${toFa(Math.round(n.disk_total_gb))} گیگابایت` : `${free} خالی`;
}

/** درصدِ پُر بودنِ دیسک (برای نوار)؛ نامعلوم ⇒ null */
export function diskUsedPct(n: Pick<NodeModels["node"], "disk_free_mb" | "disk_total_gb">): number | null {
  if (n.disk_free_mb === null || n.disk_free_mb === undefined || !n.disk_total_gb) return null;
  const total = n.disk_total_gb * 1024;
  return Math.max(0, Math.min(100, Math.round(((total - n.disk_free_mb) / total) * 100)));
}

export function fitText(p: Pick<ModelPackage, "fits" | "download_mb">): { label: string; tone: Tone } | null {
  if (p.fits === null || p.fits === undefined || !p.download_mb) return null;
  return p.fits ? { label: "جای دیسک هست", tone: "ok" } : { label: "جای دیسک کافی نیست", tone: "warn" };
}

/** برچسب‌های «به کارِ این‌ها می‌آید» */
export function featuresText(p: Pick<ModelPackage, "features">): string {
  return (p.features ?? []).map((f) => f.label).join("، ");
}

/** «همراهش دانلود می‌شود: …» (فقط آنچه هنوز نصب نیست) */
export function needsText(p: Pick<ModelPackage, "needs">): string {
  const open = (p.needs ?? []).filter((n) => n.installed !== true);
  return open.length ? open.map((n) => n.title).join("، ") : "";
}

/** بسته‌ای که با «دانلودِ همهٔ نصب‌نشده‌ها» می‌آید: انتخاب‌شدنی، مجوزِ باز و جای دیسک کافی (غیرتجاری و باشرط هرگز دسته‌ای نیست) */
export function bulkOk(p: ModelPackage): boolean {
  return selectable(p) && isOpen(p) && p.fits !== false;
}

export function missingIn(group: PackageGroup): string[] {
  return group.packages.filter((p) => bulkOk(p)).map((p) => p.key);
}

/** حجمِ دانلودِ انتخاب‌شده‌ها (آنچه مانده؛ اگر سرور نگفته، کلِ بسته) با نیازهایشان؛ بستهٔ مشترک یک بار شمرده می‌شود */
export function selectionMb(groups: PackageGroup[], keys: string[]): number {
  const want = new Set(keys);
  const counted = new Set<string>();
  let mb = 0;
  for (const g of groups) {
    for (const p of g.packages) {
      if (!want.has(p.key) || counted.has(p.key)) continue;
      counted.add(p.key);
      mb += p.missing_mb ?? p.total_mb ?? 0;
      for (const n of p.needs ?? []) {
        if (n.installed !== true && !counted.has(n.key) && !want.has(n.key)) {
          counted.add(n.key);
          mb += n.mb || 0;
        }
      }
    }
  }
  return mb;
}

/** «۳ بسته، حدودِ ۱٫۲ گیگابایت» */
export function selectionText(groups: PackageGroup[], keys: string[]): string {
  if (keys.length === 0) return "هیچ بسته‌ای انتخاب نشده.";
  const size = sizeText(selectionMb(groups, keys));
  return `${toFa(keys.length)} بسته${size ? `، حدودِ ${size}` : ""}`;
}

/** انتخاب‌شده‌هایی که مجوزشان باز نیست (برای هشدارِ پیش از دانلود) */
export function restrictedPicked(groups: PackageGroup[], keys: string[]): ModelPackage[] {
  const want = new Set(keys);
  return groups.flatMap((g) => g.packages).filter((p) => want.has(p.key) && !isOpen(p));
}

/** جملهٔ تأییدِ دانلود: حجم، نیازها، هشدارِ مجوز، خاموش بودنِ سرور */
export function confirmText(groups: PackageGroup[], keys: string[], nodeName: string, online: boolean): string {
  const lines = [`${selectionText(groups, keys)} روی «${nodeName}» دانلود می‌شود.`];
  const bad = restrictedPicked(groups, keys);
  if (bad.length) {
    lines.push(
      `توجه: ${bad.map((p) => p.title).join("، ")} مجوزِ غیرتجاری یا شرط‌دار دارد؛ پیش از استفاده در کارِ تجاری مجوزش را ببینید.`,
    );
  }
  if (!online) lines.push("سرور الان خاموش است؛ اگر نرم‌افزارش تازه باشد دانلود در صف می‌ماند و با روشن‌شدنش شروع می‌شود. اگر قدیمی باشد سایت درخواست را نمی‌پذیرد؛ سرور خودش به‌روز می‌شود و بعدش دوباره بزنید (یا بگذارید «دانلودِ خودکار» کارش را بکند).");
  lines.push("شروع شود؟");
  return lines.join("\n");
}

/** نوارِ پیشرفتِ دانلودِ در جریان: درصد (یا null اگر معلوم نیست) و جملهٔ فارسی */
export function progressView(m: Pick<NodeModels, "running" | "progress">): { pct: number | null; text: string } | null {
  if (!m.running) return null;
  const p = m.progress ?? {};
  const done = Number(p.bytes_done ?? 0);
  const total = Number(p.bytes_total ?? 0);
  const pct = total > 0 ? Math.max(0, Math.min(100, Math.round((done / total) * 100))) : null;
  const parts = ["دانلود در جریان است"];
  if (pct !== null) parts.push(`${toFa(pct)}٪`);
  if (p.items_total) parts.push(`${toFa(p.items_done ?? 0)} از ${toFa(p.items_total)} فایل`);
  return { pct, text: parts.join(" — ") };
}

/** جملهٔ بالای کارت دربارهٔ خودِ سرور */
export function nodeNote(m: NodeModels): string {
  if (!m.node.online && !m.reported) return "این سرور خاموش است و هنوز فهرستِ مدل‌هایش را نفرستاده؛ دانلود در صف می‌ماند تا روشن شود.";
  if (!m.node.online) return "این سرور خاموش است؛ وضعیت‌ها مالِ آخرین گزارشِ خودش است و دانلود در صف می‌ماند تا روشن شود.";
  if (!m.reported) return "نرم‌افزارِ این سرور فهرستِ مدل‌ها را نمی‌فرستد؛ یک بار Update.bat را روی آن بزنید.";
  return "";
}

/** سرور گزارش داده ولی بسته‌های تازهٔ کاتالوگ را هنوز نمی‌شناسد ⇒ باید به‌روز شود */
export function needsNodeUpdate(m: NodeModels): boolean {
  if (!m.reported) return false;
  const all = m.groups.flatMap((g) => g.packages);
  return all.length > 0 && all.some((p) => p.state === "unknown") && all.some((p) => p.state !== "unknown");
}

export function countInstalled(groups: PackageGroup[]): { installed: number; total: number } {
  let installed = 0;
  let total = 0;
  for (const g of groups) {
    for (const p of g.packages) {
      total += 1;
      if (p.state === "installed") installed += 1;
    }
  }
  return { installed, total };
}

/** «۳ از ۸ نصب» برای سرتیترِ هر گروه */
export function groupSummary(g: PackageGroup): string {
  const { installed, total } = countInstalled([g]);
  return `${toFa(installed)} از ${toFa(total)} نصب`;
}

/** شناسهٔ لنگرِ هر گروه (برای پرش از نوارِ بالای صفحه) */
export function groupAnchor(key: string): string {
  return `models-group-${key}`;
}

/** خلاصهٔ «دانلودِ خودکار» برای بالای صفحه */
export function autoSummary(m: Pick<NodeModels, "auto">): string {
  const a = m.auto;
  if (!a) return "";
  if (!a.enabled) return "دانلودِ خودکار خاموش است؛ هر مدل را با دکمه بگیرید.";
  if (!a.wanted) return "دانلودِ خودکار روشن است ولی هیچ قابلیتی روشن نیست.";
  // سرور هنوز چیزی گزارش نداده (خاموش است یا نرم‌افزارش قدیمی است): «همه‌چیز نصب است» دروغ می‌شد (بازبینیِ ۱۱/۱۳)
  if (!a.reported) return "دانلودِ خودکار روشن است؛ سرورِ پردازش هنوز گزارشِ مدل‌هایش را نفرستاده، پس هنوز معلوم نیست چه چیزی روی آن هست. با روشن‌شدنِ سرور خودکار بررسی می‌شود و هرچه قابلیت‌های روشن لازم دارند گرفته می‌شود.";
  const left = sizeText(a.pending_mb);
  return left
    ? `دانلودِ خودکار روشن است: ${left} برای قابلیت‌های روشن مانده و خودش (بزرگ‌ها شب) گرفته می‌شود.`
    : "دانلودِ خودکار روشن است و هر چه قابلیت‌های روشن لازم دارند نصب است.";
}

// ───────────────────────────────────────────────────────────── Ollama

/** دانلودهای Ollama که هنوز تمام نشده‌اند */
export function activePulls(o: Pick<OllamaView, "pulls"> | undefined): OllamaPull[] {
  return (o?.pulls ?? []).filter((p) => !p.final);
}

export function ollamaState(m: OllamaModel, active: OllamaPull | undefined): StateView {
  if (active) {
    if (active.state === "QUEUED") return { label: active.scheduled_text || "در صفِ دانلود", tone: "info" };
    if (active.waiting_for_node) return { label: "متوقف (سرور خاموش)", tone: "warn" };
    return { label: `در حالِ دانلود ${toFa(Math.round(active.percent))}٪`, tone: "brand" };
  }
  if (m.installed === true) return { label: "نصب است", tone: "ok" };
  if (m.installed === false) return { label: "نصب نیست", tone: "warn" };
  return { label: "نامعلوم", tone: "neutral" };
}
