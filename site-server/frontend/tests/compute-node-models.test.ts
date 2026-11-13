/**
 * آزمونِ منطقِ خالصِ «مدل‌های سرورِ پردازش» و «پردازشِ دوباره» در صفِ پردازش (بدونِ مرورگر).
 *
 *   cd frontend && node_modules/.bin/esbuild tests/compute-node-models.test.ts --bundle --platform=node --format=esm --outfile=/tmp/compute-node-models.test.mjs
 *   node /tmp/compute-node-models.test.mjs
 */
import assert from "node:assert/strict";

import {
  activePulls,
  autoSummary,
  autoView,
  bulkOk,
  confirmText,
  countInstalled,
  diskText,
  diskUsedPct,
  featuresText,
  fitText,
  groupAnchor,
  groupSummary,
  isOpen,
  licenseView,
  missingIn,
  needsNodeUpdate,
  needsText,
  nodeNote,
  ollamaState,
  progressView,
  restrictedPicked,
  selectable,
  selectionMb,
  selectionText,
  sizeText,
  stateView,
  vramView,
  type ModelPackage,
  type NodeModels,
  type PackageGroup,
} from "../src/features/tools/compute/nodeModels";
import {
  RETRY_NOTICE,
  bulkRetryConfirm,
  bulkRetryNotice,
  bulkRetryPlan,
  retryNotice,
  shortError,
  storeJobsTitle,
} from "../src/features/tools/compute/queue/model";

let checks = 0;
const eq = (a: unknown, b: unknown, msg?: string) => {
  assert.deepEqual(a, b, msg);
  checks += 1;
};
const ok = (v: unknown, msg?: string) => {
  assert.ok(v, msg);
  checks += 1;
};

// ── اندازه
eq(sizeText(4), "۴ مگابایت");
eq(sizeText(170), "۱۷۰ مگابایت");
eq(sizeText(1740), "۱٫۷ گیگابایت");
eq(sizeText(33930), "۳۳ گیگابایت");
eq(sizeText(0), "");
eq(sizeText(null), "");

// ── وضعیت
eq(stateView({ state: "installed", queued_text: "" }).tone, "ok");
eq(stateView({ state: "missing", queued_text: "" }).label, "نصب نیست");
eq(stateView({ state: "queued", queued_text: "منتظرِ بازهٔ شبانه" }).label, "در صفِ دانلود — منتظرِ بازهٔ شبانه");
eq(stateView({ state: "downloading", queued_text: "" }).tone, "brand");
eq(stateView({ state: "unknown", queued_text: "" }).tone, "neutral");
ok(selectable({ state: "missing" }) && selectable({ state: "unknown" }));
ok(!selectable({ state: "installed" }) && !selectable({ state: "queued" }) && !selectable({ state: "downloading" }));

const pkg = (key: string, state: string, total_mb: number, missing_mb: number | null) => ({
  key, title: key, title_en: "", note: "", optional: true, installed: state === "installed", state: state as never,
  queued_text: "", total_mb, missing_mb, in_comfyui: 0,
});
const groups: PackageGroup[] = [
  { key: "matting", title: "حذفِ پس‌زمینه", note: "", packages: [
    pkg("photo-background", "installed", 213, 0), pkg("matting-isnet", "missing", 170, 170),
    pkg("matting-u2netp", "missing", 4, 4), pkg("matting-runtime", "queued", 60, 60)] },
  { key: "video", title: "ویدیو", note: "", packages: [pkg("fun-inp", "unknown", 4189, null)] },
];
eq(missingIn(groups[0]), ["matting-isnet", "matting-u2netp"]);
eq(selectionMb(groups, ["matting-isnet", "matting-u2netp", "fun-inp"]), 170 + 4 + 4189);
eq(selectionText(groups, []), "هیچ بسته‌ای انتخاب نشده.");
eq(selectionText(groups, ["matting-isnet", "matting-u2netp"]), "۲ بسته، حدودِ ۱۷۴ مگابایت");
eq(countInstalled(groups), { installed: 1, total: 5 });

// ── پیشرفت و جملهٔ سرور
eq(progressView({ running: false, progress: null }), null);
eq(progressView({ running: true, progress: { bytes_done: 50, bytes_total: 200, items_done: 1, items_total: 3 } }),
  { pct: 25, text: "دانلود در جریان است — ۲۵٪ — ۱ از ۳ فایل" });
eq(progressView({ running: true, progress: null })?.pct, null);
const base = (online: boolean, reported: boolean): NodeModels => ({
  node: { id: 1, name: "DESKTOP", online, enabled: true, agent: "2.7", last_seen: null }, reported, running: false,
  progress: null, waiting: null, error: "", groups: [],
});
eq(nodeNote(base(true, true)), "");
ok(nodeNote(base(true, false)).includes("Update.bat"));
ok(nodeNote(base(false, true)).includes("خاموش"));
ok(nodeNote(base(false, false)).includes("هنوز"));

// ── «پردازشِ دوباره» در صف
eq(retryNotice({ notice: "کارِ اصلی («تولید کپشن») دوباره فرستاده شد" }), "کارِ اصلی («تولید کپشن») دوباره فرستاده شد");
eq(retryNotice({}), RETRY_NOTICE);
eq(retryNotice(null), RETRY_NOTICE);
eq(bulkRetryPlan("waiting", "", "").allowed, false);
eq(bulkRetryPlan("failed", "", ""), { allowed: true, state: "FAILED", kind: "", hint: "" });
eq(bulkRetryPlan("cancelled", "ollama", ""), { allowed: true, state: "CANCELLED", kind: "ollama", hint: "" });
eq(bulkRetryPlan("failed", "", "comfy").allowed, false);
eq(bulkRetryPlan("failed", "downloads", "").allowed, false);
ok(bulkRetryConfirm(3, "failed", "ollama").includes("۳ کار"));
ok(bulkRetryConfirm(3, "failed", "ollama").includes("هوش مصنوعی (متن)"));
ok(bulkRetryConfirm(2, "cancelled", "").includes("لغوشده"));
eq(bulkRetryNotice({ retried: 2, skipped: 0, errors: [] }), "۲ کار دوباره فرستاده شد.");
ok(bulkRetryNotice({ retried: 0, skipped: 3, errors: ["صف خاموش است"] }).includes("صف خاموش است"));
eq(storeJobsTitle({ counts: { FAILED: 0, CANCELLED: 0 } }), "هیچ کارِ ناموفق یا لغوشده‌ای در فروشگاه‌ها نیست (۷ روزِ اخیر).");
eq(storeJobsTitle({ counts: { FAILED: 6, CANCELLED: 2 } }), "کارهای فروشگاه‌ها در ۷ روزِ اخیر: ۶ ناموفق و ۲ لغوشده");
eq(shortError("Traceback\nRuntimeError: boom"), "RuntimeError: boom");
eq(shortError("x".repeat(200), 10).length, 10);

// ── کاتالوگِ تازه: مجوز، VRAM، دیسک، «به چه نیاز دارد»، دانلودِ خودکار
const full = (key: string, over: Partial<ModelPackage>): ModelPackage => ({
  ...pkg(key, "missing", 1000, 1000), license_class: "open", license: "Apache-2.0", vram_fit: "full", features: [], needs: [], fits: true,
  download_mb: 1000, auto: { mode: "manual", state: "", text: "" }, ...over,
});
eq(licenseView({ license_class: "open", license: "Apache-2.0" }), { label: "تجاری مجاز", tone: "ok", name: "Apache-2.0" });
eq(licenseView({ license_class: "noncommercial", license: "CC BY-NC-SA 4.0" })?.tone, "bad");
eq(licenseView({ license_class: "restricted", license: "LTXV Open Weights License 0.X" })?.label, "با شرط");
eq(licenseView({ license_class: "noncommercial", license: "unverified" })?.name, "نامشخص");
eq(licenseView({ license_class: undefined, license: "" }), null);
ok(isOpen({ license_class: "open" }) && isOpen({ license_class: undefined }) && !isOpen({ license_class: "restricted" }));
eq(vramView({ vram_fit: "full", vram_gb: 8 })?.tone, "ok");
eq(vramView({ vram_fit: "offload", vram_gb: 12 })?.label, "۱۲ گیگابایت: با کمی کندی");
eq(vramView({ vram_fit: "tight", vram_gb: 14 })?.tone, "warn");
eq(vramView({ vram_fit: "", vram_gb: null }), null);

// دیسک
eq(diskText({ disk_free_mb: 95000, disk_total_gb: 511 }), "۹۳ گیگابایت خالی از ۵۱۱ گیگابایت");
eq(diskText({ disk_free_mb: null, disk_total_gb: 511 }), "");
eq(diskUsedPct({ disk_free_mb: 102400, disk_total_gb: 500 }), 80);
eq(diskUsedPct({ disk_free_mb: null, disk_total_gb: 500 }), null);
eq(fitText({ fits: true, download_mb: 500 })?.tone, "ok");
eq(fitText({ fits: false, download_mb: 500 })?.label, "جای دیسک کافی نیست");
eq(fitText({ fits: true, download_mb: 0 }), null);

// «دانلودِ همهٔ نصب‌نشده‌ها» فقط مجوزِ باز و جای دیسکِ کافی
const nc = full("flux-dev", { license_class: "noncommercial", title: "FLUX dev" });
const big = full("zimage-turbo", { fits: false });
const fine = full("esrgan-x4plus", {});
ok(bulkOk(fine) && !bulkOk(nc) && !bulkOk(big));
eq(missingIn({ key: "image", title: "تصویر", note: "", packages: [fine, nc, big] }), ["esrgan-x4plus"]);
eq(restrictedPicked([{ key: "image", title: "تصویر", note: "", packages: [fine, nc] }], ["esrgan-x4plus", "flux-dev"]).map((p) => p.key), ["flux-dev"]);
ok(confirmText([{ key: "image", title: "تصویر", note: "", packages: [fine, nc] }], ["flux-dev"], "DESKTOP", false).includes("غیرتجاری"));
ok(confirmText([{ key: "image", title: "تصویر", note: "", packages: [fine] }], ["esrgan-x4plus"], "DESKTOP", true).includes("شروع شود؟"));
ok(confirmText([{ key: "image", title: "تصویر", note: "", packages: [fine] }], ["esrgan-x4plus"], "DESKTOP", false).includes("خاموش"));

// نیازها: یک بستهٔ مشترک در انتخابِ چند بسته فقط یک بار شمرده می‌شود
const common = { key: "flux-common", title: "رمزگذارها و VAE", installed: false, mb: 5000 };
const schnell = full("flux-schnell", { needs: [common], missing_mb: 11000, total_mb: 11000 });
const ltx = full("ltx-video-distilled", { needs: [common], missing_mb: 4500, total_mb: 4500 });
const commonPkg = full("flux-common", { missing_mb: 5000, total_mb: 5000 });
const imgGroups: PackageGroup[] = [{ key: "image", title: "تصویر", note: "", packages: [schnell, ltx, commonPkg] }];
eq(selectionMb(imgGroups, ["flux-schnell"]), 16000);
eq(selectionMb(imgGroups, ["flux-schnell", "ltx-video-distilled"]), 11000 + 4500 + 5000);
eq(selectionMb(imgGroups, ["flux-schnell", "flux-common"]), 11000 + 5000);
eq(needsText(schnell), "رمزگذارها و VAE");
eq(needsText(full("a", { needs: [{ ...common, installed: true }] })), "");
eq(featuresText(full("a", { features: [{ key: "image_studio", label: "ساختِ تصویر", switch: true }, { key: "thumbnails", label: "بندانگشتی", switch: false }] })), "ساختِ تصویر، بندانگشتی");
eq(groupSummary({ key: "image", title: "", note: "", packages: [{ ...fine, state: "installed" }, nc] }), "۱ از ۲ نصب");
eq(groupAnchor("upscale"), "models-group-upscale");

// دانلودِ خودکار
const au = (mode: "default" | "on" | "off" | "never" | "manual", state = "") => ({ mode, state, text: "" });
eq(autoView({ auto: au("on", "waiting_window"), state: "missing" })?.label, "خودکار — منتظرِ بازهٔ شبانه");
eq(autoView({ auto: au("on", "no_disk"), state: "missing" })?.tone, "warn");
eq(autoView({ auto: au("on", "pending"), state: "installed" })?.label, "خودکار — نصب شد");
eq(autoView({ auto: au("on", ""), state: "missing" })?.label, "خودکار — در انتظارِ سرور");
eq(autoView({ auto: au("off"), state: "missing" })?.label, "خودکار نیست");
eq(autoView({ auto: au("never"), state: "missing" })?.label, "هرگز خودکار (مجوز)");
eq(autoView({ auto: au("manual"), state: "missing" }), null);
eq(autoView({ auto: undefined, state: "missing" }), null);
const withAuto = (a: NodeModels["auto"]): Pick<NodeModels, "auto"> => ({ auto: a });
eq(autoSummary(withAuto(undefined)), "");
ok(autoSummary(withAuto({ enabled: false, reserve_gb: 25, wanted: 3, pending_mb: 0, reported: true, states: {}, why: {} })).includes("خاموش"));
ok(autoSummary(withAuto({ enabled: true, reserve_gb: 25, wanted: 0, pending_mb: 0, reported: true, states: {}, why: {} })).includes("هیچ قابلیتی"));
ok(autoSummary(withAuto({ enabled: true, reserve_gb: 25, wanted: 4, pending_mb: 17000, reported: true, states: {}, why: {} })).includes("۱۷ گیگابایت"));
ok(autoSummary(withAuto({ enabled: true, reserve_gb: 25, wanted: 4, pending_mb: 0, reported: true, states: {}, why: {} })).includes("نصب است"));

// سرورِ قدیمی: بعضی بسته‌ها را گزارش داده، بسته‌های تازه را نه
const oldNode: NodeModels = { ...base(true, true), groups: [{ key: "image", title: "تصویر", note: "", packages: [{ ...fine, state: "installed" }, { ...schnell, state: "unknown" }] }] };
ok(needsNodeUpdate(oldNode));
ok(!needsNodeUpdate({ ...oldNode, reported: false }));
ok(!needsNodeUpdate({ ...oldNode, groups: [{ key: "image", title: "تصویر", note: "", packages: [{ ...fine, state: "installed" }] }] }));

// Ollama
const pull = (over: Record<string, unknown>) => ({ uid: "u1", tag: "qwen3:8b", label: "Qwen3 8B", state: "RUNNING", final: false, percent: 42.4, text: "", error: "", waiting_for_node: false, ...over });
eq(activePulls({ pulls: [pull({}), pull({ uid: "u2", final: true })] }).length, 1);
eq(activePulls(undefined), []);
const om = { tag: "qwen3:8b", label: "Qwen3", size_mb: 5225, purpose: "", vision: false, installed: false };
eq(ollamaState(om, undefined).label, "نصب نیست");
eq(ollamaState({ ...om, installed: true }, undefined).tone, "ok");
eq(ollamaState({ ...om, installed: null }, undefined).tone, "neutral");
eq(ollamaState(om, pull({})).label, "در حالِ دانلود ۴۲٪");
eq(ollamaState(om, pull({ state: "QUEUED", scheduled_text: "شروع فردا ۰۲:۰۰" })).label, "شروع فردا ۰۲:۰۰");
eq(ollamaState(om, pull({ waiting_for_node: true })).tone, "warn");

console.log(`compute-node-models: همهٔ ${checks} بررسی درست`);
