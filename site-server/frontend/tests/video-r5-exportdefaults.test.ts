/**
 * آزمونِ «تنظیماتِ خروجیِ نهایی همیشه کامل و درست است».
 *
 *   cd frontend && node_modules/.bin/esbuild tests/video-r5-exportdefaults.test.ts --bundle --platform=node --format=esm --outfile=/tmp/video-r5-exportdefaults.test.mjs
 *   node /tmp/video-r5-exportdefaults.test.mjs
 */
import assert from "node:assert/strict";

import { finalExport } from "../src/features/content/video/manual/exportDefaults";

const results: { name: string; ok: boolean; err?: string }[] = [];
function check(name: string, fn: () => void) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, err: e instanceof Error ? `${e.message}\n${e.stack?.split("\n").slice(1, 4).join("\n")}` : String(e) });
  }
}

check("بدونِ هیچ تنظیمی: یک شیءِ درست با format = mp4 (نه undefined)", () => {
  assert.deepEqual(finalExport(undefined, undefined), { format: "mp4" });
  assert.deepEqual(finalExport(null, null), { format: "mp4" });
  assert.deepEqual(finalExport({}, {}), { format: "mp4" });
});
check("نیمه‌پر: همان چیزی که هست می‌ماند و چیزی اضافه نمی‌شود جز format", () => {
  assert.deepEqual(finalExport({ fps: 24 }), { fps: 24, format: "mp4" });
  assert.deepEqual(finalExport({ preset: "reels" }), { preset: "reels", format: "mp4" });
  assert.deepEqual(finalExport({ quality: "small", where: "server" }), { quality: "small", where: "server", format: "mp4" });
});
check("تنظیمِ یک‌باره روی بلوکِ پروژه می‌نشیند", () => {
  assert.deepEqual(finalExport({ preset: "reels", fps: 30 }, { preset: "telegram" }), { preset: "telegram", fps: 30, format: "mp4" });
  assert.deepEqual(finalExport({ preset: "reels" }, { format: "gif" }), { preset: "reels", format: "gif" });
  assert.deepEqual(finalExport({}, { format: "frame", frame_t: 2.5 }), { format: "frame", frame_t: 2.5 });
  assert.deepEqual(finalExport({}, { range: "inout", format: "audio" }), { range: "inout", format: "audio" });
  assert.deepEqual(finalExport({}, { replace: true, range: "inout" }), { replace: true, range: "inout", format: "mp4" });
});
check("مقدارهای خراب کنار گذاشته می‌شوند، نه فرستاده", () => {
  const bad = finalExport({ preset: "  ", codec: "vp9" as never, fps: NaN, height: -5, quality: "ultra" as never, audio_kbps: Infinity, where: "node" as never, target_mb: 0 },
    { format: "exe", range: "weird", frame_t: -1, replace: "yes" });
  assert.deepEqual(bad, { format: "mp4" });
});
check("عددها در بازهٔ مجاز بریده و گرد می‌شوند", () => {
  assert.deepEqual(finalExport({ fps: 240.4, height: 100, audio_kbps: 9999 }), { fps: 60, height: 240, audio_kbps: 320, format: "mp4" });
  assert.deepEqual(finalExport({ fps: 3 }), { fps: 12, format: "mp4" });
  assert.deepEqual(finalExport({ fps: 29.6 }), { fps: 30, format: "mp4" });
});
check("ورودی را دست نمی‌زند و کلیدِ ناشناخته را نمی‌فرستد", () => {
  const block = { preset: "reels", secret: 1 } as never;
  const before = JSON.stringify(block);
  const out = finalExport(block, { evil: "x" });
  assert.equal(JSON.stringify(block), before);
  assert.deepEqual(out, { preset: "reels", format: "mp4" });
});

const bad = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "✓" : "✗"} ${r.name}${r.err ? `\n    ${r.err}` : ""}`);
console.log(`\n${results.length - bad.length}/${results.length} passed`);
if (bad.length) process.exit(1);
