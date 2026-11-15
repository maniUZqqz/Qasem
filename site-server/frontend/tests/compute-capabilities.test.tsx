/**
 * «توانایی‌های سرورِ پردازش» در ردیفِ سرورها: فقط برچسب‌های فارسیِ مجاز؛ کلیدهای فنیِ عامل (data_dir، commands، disk_free_gb، gpu_util_pct،
 * preflight …) هرگز برچسب نمی‌شوند و فقط پشتِ «جزئیات فنی» (بسته) می‌مانند؛ کلیدِ ناشناخته‌ٔ تازه هم برچسب نمی‌آورد. + کاشیِ فضای فایل‌های کارها.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/compute-capabilities.test.tsx --bundle --platform=node --format=cjs --jsx=automatic --outfile=/tmp/compute-capabilities.test.cjs
 *   node /tmp/compute-capabilities.test.cjs
 */
import assert from "node:assert/strict";

import { renderToStaticMarkup } from "react-dom/server";

import CapabilityPills from "../src/features/tools/compute/CapabilityPills";
import { capabilityPills, summaryLabel, technicalRows } from "../src/features/tools/compute/capabilities";
import { storageView } from "../src/features/tools/compute/report/model";

let checks = 0;
const has = (html: string, text: string, msg?: string) => {
  assert.ok(html.includes(text), `${msg ?? "در HTML نیست"}: «${text}»`);
  checks += 1;
};
const hasNot = (html: string, text: string, msg?: string) => {
  assert.ok(!html.includes(text), `${msg ?? "نباید در HTML باشد"}: «${text}»`);
  checks += 1;
};

// همان کلیدهایی که عاملِ ۲٫۱۰ روی گرهٔ واقعی فرستاده بود (۱۴۰۵/۰۸/۲۲)
const caps: Record<string, unknown> = {
  agent: "2.10", audio: { moss: true, sfx: true, music: true }, auto_switch: true, blender: true, code: { version: "2.10", id: "1f328a" },
  comfy_bridge: false, comfyui: true, commands: ["status", "update", "restart", "build", "logs"], data_dir: "C:\\Users\\QQz\\NMarketing-data",
  disk_free_gb: 93.4, disk_total_gb: 511, edit: { v: 1, render: true, ffmpeg: "99.0", nvenc: { h264: true, h265: true } }, ffmpeg: true,
  gpu: "NVIDIA GeForce RTX 3060", gpu_temp_c: 53, gpu_util_pct: 1, hostname: "DESKTOP-EAFBTGQ", lipsync: false,
  matting_runtime: { ok: true }, models: { packages: {} }, moss: false, ollama: true, ollama_models: ["qwen3:8b", "qwq:32b"], photo: true,
  photo_matting: true, preflight: [{ key: "python", ok: true }], slots: 1, startable: { ollama: true }, voice: false, voice_clone: false,
  vram_total_mb: 12288, worker3d: true, brand_new_agent_field: true,
};

// ۱) فهرستِ مجاز
const pills = capabilityPills(caps).map((p) => p.label);
for (const want of ["ffmpeg", "ویرایشگرِ ویدیو", "حذفِ پس‌زمینهٔ عکس", "گفتارِ فارسیِ MOSS", "افکتِ صدا", "موسیقیِ زمینه"]) {
  assert.ok(pills.includes(want), `برچسبِ «${want}» باید باشد: ${pills.join("، ")}`);
  checks += 1;
}
assert.ok(pills.some((l) => l.includes("NVENC")));
assert.ok(!pills.includes("هم‌گام‌سازیِ لب"), "پرچمِ خاموش برچسب نمی‌آورد");
assert.ok(!pills.includes("کلونِ صدا"));
checks += 3;
assert.deepEqual(capabilityPills(null), []);
assert.deepEqual(capabilityPills({}), []);
checks += 2;

// ۲) رندر: هیچ کلیدِ فنیِ انگلیسی به‌صورتِ برچسب نیست؛ همه پشتِ «جزئیات فنی»
const html = renderToStaticMarkup(<CapabilityPills caps={caps} />);
const outside = html.replace(/<details[\s\S]*?<\/details>/, "");
for (const raw of ["data_dir", "commands", "disk_free_gb", "gpu_util_pct", "preflight", "matting_runtime", "comfy_models", "brand_new_agent_field"]) {
  hasNot(outside, raw, `کلیدِ فنیِ «${raw}» بیرون از «جزئیات فنی» چاپ شده`);
}
has(html, "جزئیات فنی");
has(html, 'data-testid="tech-details"');
assert.ok(!/<details[^>]*\sopen/.test(html), "«جزئیات فنی» باید پیش‌فرض بسته باشد");
checks += 1;
has(html, "data_dir", "در جزئیات فنی باید باشد");
hasNot(html, "disk_free_gb", "اندازه‌گیریِ لحظه‌ای هرگز در جزئیات فنی هم نیست");
hasNot(html, "gpu_util_pct");
hasNot(html, "ram_free_mb");

// ۳) فقط برچسب‌های مجاز مثلِ Badge (تعدادشان محدود است، نه ۱۸ تا)
const badgeCount = (outside.match(/class="u-badge /g) ?? []).length;
assert.ok(badgeCount <= 8, `باید فقط چند برچسبِ مجاز باشد، نه ${badgeCount}`);
checks += 1;

// ۴) technicalRows: کلیدِ پنهان و اندازه‌گیری حذف، فهرست خلاصه می‌شود
const rows = technicalRows(caps, new Set(["hostname", "gpu"]));
const keys = rows.map((r) => r.key);
assert.ok(keys.includes("data_dir") && keys.includes("commands"));
assert.ok(!keys.includes("hostname") && !keys.includes("gpu") && !keys.includes("disk_free_gb") && !keys.includes("gpu_temp_c"));
assert.ok(!keys.includes("lipsync"), "مقدارِ false در جزئیات نمی‌آید");
const cmd = rows.find((r) => r.key === "commands")!;
assert.ok(cmd.value.startsWith("[5] status, update"), cmd.value);
checks += 5;
const long = technicalRows({ list: Array.from({ length: 40 }, (_, i) => `x${i}`) })[0];
assert.ok(long.value.length < 80 && long.value.startsWith("[40]"), long.value);
checks += 1;

// ۵) برچسبِ کارتِ «توانایی‌های آنلاین»
assert.equal(summaryLabel("comfyui"), "ComfyUI");
assert.equal(summaryLabel("photo_matting"), "حذفِ پس‌زمینهٔ عکس");
assert.equal(summaryLabel("worker3d"), "رندرِ سه‌بعدی");
assert.equal(summaryLabel("auto_switch"), null);
assert.equal(summaryLabel("some_new_key"), null);
checks += 5;

// ۶) کاشیِ فضای فایل‌های کارها
assert.equal(storageView(null), null);
assert.equal(storageView({ dirs: 5 }), null, "تا اولین دورِ نگه‌داری نشان داده نمی‌شود");
const view = storageView({ dirs: 120, size_mb: 135, freed_mb: 2048, freed_last_mb: 12, last_run: "2026-11-14T10:00:00Z", rules: { output_days: 7, failed_days: 14, grace_minutes: 60 } })!;
assert.equal(view.items.length, 4);
assert.ok(view.items.some((i) => i.label === "آزادشده تا امروز" && i.value.includes("گیگابایت")), JSON.stringify(view.items));
assert.ok(view.items.some((i) => i.label === "پوشهٔ کار" && i.value === "۱۲۰"));
assert.ok(view.note.includes("۷ روز") && view.note.includes("۱۴ روز") && view.note.includes("۶۰ دقیقه"), view.note);
checks += 5;

console.log(`ok — ${checks} بررسی گذشت`);
