/**
 * آزمونِ منطقِ خالصِ «مدل‌های سرورِ پردازش» و «پردازشِ دوباره» در صفِ پردازش (بدونِ مرورگر).
 *
 *   cd frontend && node_modules/.bin/esbuild tests/compute-node-models.test.ts --bundle --platform=node --format=esm --outfile=/tmp/compute-node-models.test.mjs
 *   node /tmp/compute-node-models.test.mjs
 */
import assert from "node:assert/strict";

import {
  countInstalled,
  missingIn,
  nodeNote,
  progressView,
  selectable,
  selectionMb,
  selectionText,
  sizeText,
  stateView,
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

console.log(`compute-node-models: همهٔ ${checks} بررسی درست`);
