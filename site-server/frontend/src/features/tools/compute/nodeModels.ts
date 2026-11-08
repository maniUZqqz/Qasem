/**
 * منطقِ خالصِ کارتِ «مدل‌های سرورِ پردازش» (بدونِ React، تا بی مرورگر آزمون شود).
 *
 * داده از GET /compute/models/ (apps.compute.model_packages): برای هر سرور، همهٔ بسته‌های دانلودیِ آن — حذفِ پس‌زمینه
 * (عکس و ویدیو)، صدا، ویدیوی Wan — با وضعیتِ نصب از گزارشِ خودِ سرور. دانلود: POST /compute/nodes/<id>/models/download/.
 * آزمون: frontend/tests/compute-node-models.test.ts
 */

export type PackageState = "installed" | "missing" | "downloading" | "waiting_window" | "queued" | "unknown";

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
};

export type PackageGroup = { key: string; title: string; note: string; packages: ModelPackage[] };

export type NodeModels = {
  node: { id: number; name: string; online: boolean; enabled: boolean; agent: string | null; last_seen: string | null };
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
  groups: PackageGroup[];
};

export type ModelsListing = { nodes: NodeModels[]; ollama_page: string };

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

export type StateView = { label: string; tone: "ok" | "warn" | "info" | "brand" | "neutral" };

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

export function missingIn(group: PackageGroup): string[] {
  return group.packages.filter((p) => selectable(p)).map((p) => p.key);
}

/** حجمِ دانلودِ انتخاب‌شده‌ها (آنچه مانده؛ اگر سرور نگفته، کلِ بسته) */
export function selectionMb(groups: PackageGroup[], keys: string[]): number {
  const want = new Set(keys);
  let mb = 0;
  for (const g of groups) {
    for (const p of g.packages) {
      if (want.has(p.key)) mb += p.missing_mb ?? p.total_mb ?? 0;
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
