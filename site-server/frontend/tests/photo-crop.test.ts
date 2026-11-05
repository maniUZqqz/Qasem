/**
 * آزمونِ منطقِ برشِ ادیتورِ عکس (بدونِ مرورگر): اندازهٔ عددی با نسبتِ قفل، تشخیصِ خودکارِ کجیِ افق.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/photo-crop.test.ts --bundle --platform=node --format=esm --outfile=/tmp/photo-crop.test.mjs
 *   node /tmp/photo-crop.test.mjs
 */
import assert from "node:assert/strict";

import { ASPECTS, aspectRect } from "../src/features/content/photo/manual/model";
import { resizeCrop } from "../src/features/content/photo/pro/cropMath";
import { detectTilt } from "../src/features/content/photo/pro/autostraighten";

const results: { name: string; ok: boolean; err?: string }[] = [];
function check(name: string, fn: () => void) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, err: e instanceof Error ? e.message : String(e) });
  }
}

const near = (a: number, b: number, eps = 1e-6) => Math.abs(a - b) <= eps;

/** عکسِ خاکستری با لبه‌های (نواری) که deg درجه (ساعتگرد) کج‌اند؛ لبه‌ها مثلِ عکسِ واقعی ضدِ پله (۳ پیکسل شیب) */
function edgeImage(w: number, h: number, deg: number, lines = 1) {
  const data = new Uint8ClampedArray(w * h * 4);
  const a = (deg * Math.PI) / 180;
  const t = Math.tan(a);
  const cos = Math.cos(a);
  const period = h / lines;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const yy = (y - h / 2 - t * (x - w / 2)) * cos;               // فاصلهٔ عمودی از خطِ مرکزی
      const v = 128 + 87 * Math.sin((2 * Math.PI * yy) / period);   // موجِ هموار: جهتِ گرادیان = کجیِ واقعی
      const i = (y * w + x) * 4;
      data[i] = data[i + 1] = data[i + 2] = v;
      data[i + 3] = 255;
    }
  }
  return { data, width: w, height: h };
}

check("resizeCrop: پهنای عددی حولِ مرکز و آزاد", () => {
  const r = resizeCrop({ x: 0.25, y: 0.25, w: 0.5, h: 0.5 }, 1200, 900, 600, null, null);
  assert.ok(near(r.w, 0.5) && near(r.h, 0.5));
  const r2 = resizeCrop({ x: 0.25, y: 0.25, w: 0.5, h: 0.5 }, 1200, 900, 300, null, null);
  assert.ok(near(r2.w, 0.25) && near(r2.h, 0.5));
  assert.ok(near(r2.x + r2.w / 2, 0.5), "مرکز می‌ماند");
});

check("resizeCrop: نسبتِ قفل (۱:۱) پیکسلی می‌ماند", () => {
  const r = resizeCrop({ x: 0.2, y: 0.2, w: 0.5, h: 0.5 }, 1200, 900, 500, null, 1);
  assert.ok(near(r.w * 1200, 500, 0.5) && near(r.h * 900, 500, 0.5));
  const r2 = resizeCrop({ x: 0.2, y: 0.2, w: 0.5, h: 0.5 }, 1200, 900, null, 300, 1);
  assert.ok(near(r2.w * 1200, 300, 0.5) && near(r2.h * 900, 300, 0.5));
});

check("resizeCrop: از عکس بیرون نمی‌زند و نسبت را نگه می‌دارد", () => {
  const r = resizeCrop({ x: 0.1, y: 0.1, w: 0.5, h: 0.5 }, 1200, 900, 5000, null, 1);
  assert.ok(r.x >= 0 && r.y >= 0 && r.x + r.w <= 1 + 1e-9 && r.y + r.h <= 1 + 1e-9);
  assert.ok(near(r.w * 1200, r.h * 900, 0.5), "هنوز مربع");
  assert.ok(near(r.h, 1, 1e-6), "ارتفاع به سقف رسید و پهنا هم‌نسبت کوچک شد");
  const tiny = resizeCrop({ x: 0.1, y: 0.1, w: 0.5, h: 0.5 }, 1200, 900, 1, null, null);
  assert.ok(tiny.w >= 0.02);
});

check("resizeCrop: نسبتِ ۱۶:۹ و ۴:۵", () => {
  const r = resizeCrop({ x: 0, y: 0, w: 1, h: 1 }, 1600, 1200, 800, null, 16 / 9);
  assert.ok(near((r.w * 1600) / (r.h * 1200), 16 / 9, 1e-3));
  const p = resizeCrop({ x: 0, y: 0, w: 1, h: 1 }, 1600, 1200, null, 600, 4 / 5);
  assert.ok(near((p.w * 1600) / (p.h * 1200), 4 / 5, 1e-3));
});

check("aspectRect: همهٔ نسبت‌ها داخلِ عکس و هم‌نسبت", () => {
  for (const a of ASPECTS) {
    if (a.ratio === null) continue;
    const ratio = a.ratio === 0 ? 1200 / 900 : a.ratio;
    const r = aspectRect(ratio, 1200, 900);
    assert.ok(r.x >= -1e-9 && r.y >= -1e-9 && r.x + r.w <= 1 + 1e-9 && r.y + r.h <= 1 + 1e-9, a.key);
    assert.ok(near((r.w * 1200) / (r.h * 900), ratio, 1e-3), a.key);
  }
});

check("detectTilt: لبهٔ ۳ درجه ساعتگرد", () => {
  const t = detectTilt(edgeImage(400, 300, 3));
  assert.ok(Math.abs(t.angle - 3) < 0.8, `زاویه ${t.angle}`);
  assert.ok(t.confidence > 0.3, `اطمینان ${t.confidence}`);
});

check("detectTilt: لبهٔ ۴ درجه پادساعتگرد (علامت)", () => {
  const t = detectTilt(edgeImage(400, 300, -4, 3));
  assert.ok(t.angle < -2.8 && t.angle > -5.2, `زاویه ${t.angle}`);
});

/** لبه‌های «سخت» (بی‌ضدِ پله) مثلِ افقِ ساختمان/دریا در JPEG: یک افقِ بلند + چند خطِ عمودی که deg درجه ساعتگرد کج‌اند */
function hardScene(w: number, h: number, deg: number) {
  const data = new Uint8ClampedArray(w * h * 4);
  const a = (deg * Math.PI) / 180;
  const cos = Math.cos(a);
  const sin = Math.sin(a);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      // مختصاتِ «صحنهٔ صاف»: چرخشِ معکوس حولِ مرکز
      const dx = x - w / 2;
      const dy = y - h / 2;
      const u = dx * cos + dy * sin; // محورِ افقیِ صحنه
      const v = -dx * sin + dy * cos; // محورِ عمودیِ صحنه
      let val = v < h * 0.1 ? 200 : 70; // افق
      if (v > h * 0.1 && Math.abs(((u + w * 2) % 60) - 30) < 2) val = 140; // خطوطِ عمودیِ نازک (نرده)
      if (u > w * 0.1 && u < w * 0.3 && v > -h * 0.2 && v <= h * 0.1) val = 110; // خانه
      const i = (y * w + x) * 4;
      data[i] = data[i + 1] = data[i + 2] = val;
      data[i + 3] = 255;
    }
  }
  return { data, width: w, height: h };
}

check("detectTilt: صحنهٔ لبه‌سخت (افق + نرده + خانه) ⇒ خطا زیرِ ۰٫۸°", () => {
  for (const deg of [2, 4, -3, 6]) {
    const t = detectTilt(hardScene(640, 480, deg));
    assert.ok(Math.abs(t.angle - deg) < 0.8, `کجیِ واقعی ${deg}، تشخیص ${t.angle}`);
    assert.ok(t.confidence > 0.5, `اطمینان ${t.confidence}`);
  }
});

check("detectTilt: عکسِ صاف ⇒ زاویهٔ نزدیکِ صفر و بی‌اعتمادیِ کم", () => {
  const t = detectTilt(edgeImage(400, 300, 0, 2));
  assert.ok(Math.abs(t.angle) < 0.6, `زاویه ${t.angle}`);
});

check("detectTilt: عکسِ تخت (بی‌لبه) ⇒ اطمینانِ صفر", () => {
  const d = new Uint8ClampedArray(200 * 200 * 4).fill(128);
  const t = detectTilt({ data: d, width: 200, height: 200 });
  assert.equal(t.confidence, 0);
});

check("detectTilt: نویزِ تصادفی ⇒ اطمینانِ پایین", () => {
  const n = 300 * 300;
  const d = new Uint8ClampedArray(n * 4);
  let a = 0x9e3779b9; // mulberry32 (یک PRNGِ درست؛ LCGِ ساده با ضربِ بزرگ در JS الگوی راه‌راه می‌داد)
  for (let i = 0; i < n; i++) {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    const v = ((t ^ (t >>> 14)) >>> 0) & 255;
    d[i * 4] = d[i * 4 + 1] = d[i * 4 + 2] = v;
    d[i * 4 + 3] = 255;
  }
  const t = detectTilt({ data: d, width: 300, height: 300 });
  assert.ok(t.confidence < 0.18, `اطمینان ${t.confidence}`);
});

const bad = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "OK  " : "FAIL"} ${r.name}${r.err ? " — " + r.err : ""}`);
console.log(`\n${results.length - bad.length}/${results.length} passed`);
process.exit(bad.length ? 1 : 0);
