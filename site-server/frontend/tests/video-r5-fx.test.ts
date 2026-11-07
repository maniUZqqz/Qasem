/**
 * آزمونِ ابزارهای قطعهٔ دورِ پنجم: لایهٔ تنظیم، کلیدِ روشنایی، اصلاحِ لنز، نقطهٔ لنگر.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/video-r5-fx.test.ts --bundle --platform=node --format=esm --outfile=/tmp/video-r5-fx.test.mjs
 *   node /tmp/video-r5-fx.test.mjs
 */
import assert from "node:assert/strict";

import { MediaClip, Project, clipEnd, emptyProject, findClip } from "../src/features/content/video/manual/model";
import {
  ADJUST_REF, ANCHOR_PRESETS, DEFAULT_LUMA, addAdjustment, adjustmentSpan, anchorIsCentre, isAdjust, lensIsFlat, matteSourceFor, newAdjustment, planMattes, setAnchor, setLens, setLuma, setTrackMatte,
} from "../src/features/content/video/manual/r5fx";
import { lensCorrect, lensSource, lumaKey, matteMultiply } from "../src/features/content/video/manual/Compositor";

const results: { name: string; ok: boolean; err?: string }[] = [];
function check(name: string, fn: () => void) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, err: e instanceof Error ? `${e.message}\n${e.stack?.split("\n").slice(1, 4).join("\n")}` : String(e) });
  }
}

const clip = (id: string, at: number, len: number, over: Partial<MediaClip> = {}): MediaClip => ({
  id, type: "media", ref: "video:1", label: id, kind: "video", at, start: 0, end: len, src: 30, opacity: 1, x: 0, y: 0, width: 1, height: 1, volume: 1, speed: 1, fit: "cover",
  fade_in: 0, fade_out: 0, audio_on: true, has_audio: true, effects: [], transition: null, ...over,
});
function proj(video: MediaClip[]): Project {
  const p = emptyProject();
  let v = false;
  return { ...p, tracks: p.tracks.map((t) => (t.kind === "video" && !v ? ((v = true), { ...t, clips: video }) : t)) };
}

// ───────────── لایهٔ تنظیم
check("لایهٔ تنظیم مثلِ یک عکسِ بی‌منبع است و علامتِ adjust دارد", () => {
  const a = newAdjustment(2, 4, "a1");
  assert.equal(a.adjust, true);
  assert.equal(a.ref, ADJUST_REF);
  assert.equal(a.kind, "image");
  assert.equal(a.start, 0);
  assert.equal(a.end, 4);
  assert.equal(a.has_audio, false);
  assert.ok(isAdjust(a));
  assert.ok(!isAdjust(clip("x", 0, 1)));
});
check("لایهٔ تنظیم روی بالاترین ترکِ تصویر می‌نشیند؛ اگر آن‌جا جا نبود ترکِ تازه می‌سازد", () => {
  const p = proj([clip("v", 0, 10)]);
  const before = p.tracks.filter((t) => t.kind === "video").length;
  const r = addAdjustment(p, 1, 3, "adj");
  assert.equal(r.id, "adj");
  const vt = r.project.tracks.filter((t) => t.kind === "video");
  assert.ok(vt[vt.length - 1].clips.some((c) => c.id === "adj"), "روی ترکِ بالایی");
  assert.ok(!vt[0].clips.some((c) => c.id === "adj"), "روی ترکِ فیلم نه");
  assert.equal(p.tracks.filter((t) => t.kind === "video").length, before, "پروژهٔ اصلی دست نخورده");
  // بالاترین ترک پر است ⇒ ترکِ تازه بالاتر از همه
  const full = { ...p, tracks: p.tracks.map((t, i, all) => (t.kind === "video" && all.slice(i + 1).every((x) => x.kind !== "video") ? { ...t, clips: [clip("top", 0, 10)] } : t)) };
  const r2 = addAdjustment(full, 1, 3, "adj2");
  const vt2 = r2.project.tracks.filter((t) => t.kind === "video");
  assert.equal(vt2.length, before + 1);
  assert.ok(vt2[vt2.length - 1].clips.some((c) => c.id === "adj2"));
});
check("لایهٔ دوم، اگر ترکِ بالایی آزاد باشد، همان‌جا می‌نشیند؛ هم‌پوشان باشد ترکِ تازه", () => {
  let p = proj([clip("v", 0, 10)]);
  p = addAdjustment(p, 0, 2, "a1").project;
  const n = p.tracks.filter((t) => t.kind === "video").length;
  const q = addAdjustment(p, 5, 2, "a2").project;
  assert.equal(q.tracks.filter((t) => t.kind === "video").length, n, "ترکِ تازه ساخته نشد");
  const q2 = addAdjustment(q, 1, 3, "a3").project;                         // با a1 هم‌پوشانی دارد ⇒ ترکِ تازه
  assert.equal(q2.tracks.filter((t) => t.kind === "video").length, n + 1);
});
check("مدتِ پیش‌فرض: تا انتهای قطعهٔ زیرِ سرِ پخش، وگرنه ۵ ثانیه", () => {
  const p = proj([clip("v", 0, 10)]);
  assert.equal(adjustmentSpan(p, 4), 6);
  assert.equal(adjustmentSpan(p, 10.05), 5);
  assert.equal(adjustmentSpan(proj([]), 0), 5);
  const withAdj = addAdjustment(p, 0, 20, "a").project;
  assert.equal(adjustmentSpan(withAdj, 4), 6, "خودِ لایهٔ تنظیم مدتِ پیش‌فرض را دراز نمی‌کند");
});

// ───────────── کلیدِ روشنایی
check("کلیدِ روشنایی: روشن با پیش‌فرض، محدود، و خاموش = حذف", () => {
  let p = proj([clip("v", 0, 5)]);
  p = setLuma(p, "v", { on: true });
  assert.deepEqual((findClip(p, "v")!.clip as MediaClip).luma, DEFAULT_LUMA);
  p = setLuma(p, "v", { mode: "bright", tolerance: 5, softness: -2 });
  assert.deepEqual((findClip(p, "v")!.clip as MediaClip).luma, { on: true, mode: "bright", tolerance: 1, softness: 0 });
  p = setLuma(p, "v", null);
  assert.equal((findClip(p, "v")!.clip as MediaClip).luma, undefined);
  assert.equal(setLuma(p, "nope", { on: true }), p);
});

// ───────────── لنز
check("لنز: مقدارها محدود می‌شوند و لنزِ تخت حذف می‌شود", () => {
  let p = proj([clip("v", 0, 5)]);
  p = setLens(p, "v", { k1: -9 });
  assert.deepEqual((findClip(p, "v")!.clip as MediaClip).lens, { k1: -1, k2: 0 });
  p = setLens(p, "v", { k2: 0.3 });
  assert.deepEqual((findClip(p, "v")!.clip as MediaClip).lens, { k1: -1, k2: 0.3 });
  p = setLens(p, "v", { k1: 0, k2: 0.001 });
  assert.equal((findClip(p, "v")!.clip as MediaClip).lens, undefined, "تخت = حذف");
  assert.ok(lensIsFlat(undefined) && lensIsFlat({ k1: 0.001, k2: 0 }) && !lensIsFlat({ k1: 0.2, k2: 0 }));
});

// ───────────── نقطهٔ لنگر
check("نقطهٔ لنگر: نُه نقطهٔ آماده، مرکز = حذف، محدود", () => {
  assert.equal(ANCHOR_PRESETS.length, 9);
  assert.equal(new Set(ANCHOR_PRESETS.map((a) => a.key)).size, 9);
  let p = proj([clip("v", 0, 5)]);
  p = setAnchor(p, "v", { x: -0.5, y: -0.5 });
  assert.deepEqual((findClip(p, "v")!.clip as MediaClip).anchor, { x: -0.5, y: -0.5 });
  p = setAnchor(p, "v", { x: 7, y: -7 });
  assert.deepEqual((findClip(p, "v")!.clip as MediaClip).anchor, { x: 1, y: -1 });
  p = setAnchor(p, "v", { x: 0, y: 0.001 });
  assert.equal((findClip(p, "v")!.clip as MediaClip).anchor, undefined);
  assert.ok(anchorIsCentre(undefined) && anchorIsCentre({ x: 0, y: 0 }) && !anchorIsCentre({ x: 0.3, y: 0 }));
});
check("ابزارها فقط روی قطعهٔ رسانه‌ای کار می‌کنند و بقیهٔ پروژه را عوض نمی‌کنند", () => {
  const p = proj([clip("a", 0, 5), clip("b", 5, 5)]);
  const q = setLuma(setLens(setAnchor(p, "a", { x: 0.5, y: 0 }), "a", { k1: 0.3 }), "a", { on: true });
  assert.deepEqual(findClip(q, "b")!.clip, findClip(p, "b")!.clip);
  assert.equal(clipEnd(findClip(q, "a")!.clip), 5);
});

// ───────────── پیش‌نمایشِ کلیدِ روشنایی (مثلِ ffmpeg lumakey)
function img(px: [number, number, number][]): ImageData {
  const d = new Uint8ClampedArray(px.length * 4);
  px.forEach(([r, g, b], i) => { d[i * 4] = r; d[i * 4 + 1] = g; d[i * 4 + 2] = b; d[i * 4 + 3] = 255; });
  return { data: d, width: px.length, height: 1, colorSpace: "srgb" } as ImageData;
}
check("lumaKey: حالتِ تاریک سیاه را شفاف و سفید را نگه می‌دارد", () => {
  const im = img([[0, 0, 0], [30, 30, 30], [128, 128, 128], [255, 255, 255]]);
  lumaKey(im, { mode: "dark", tolerance: 0.2, softness: 0.05 });
  assert.equal(im.data[3], 0, "سیاه شفاف");
  assert.equal(im.data[7], 0, "۳۰/۲۵۵ ≈ ۰٫۱۲ زیرِ تلورانسِ ۰٫۲");
  assert.equal(im.data[11], 255, "خاکستریِ میانه می‌ماند");
  assert.equal(im.data[15], 255, "سفید می‌ماند");
});
check("lumaKey: حالتِ روشن سفید را شفاف می‌کند و نرمیِ لبه شیبِ تدریجی می‌دهد", () => {
  const im = img([[255, 255, 255], [0, 0, 0], [200, 200, 200]]);
  lumaKey(im, { mode: "bright", tolerance: 0.1, softness: 0.4 });
  assert.equal(im.data[3], 0);
  assert.equal(im.data[7], 255);
  assert.ok(im.data[11] > 0 && im.data[11] < 255, `شیبِ نرم، نه صفر یا کامل: ${im.data[11]}`);
});

// ───────────── Track matte
function twoTracks(lower: MediaClip[], upper: MediaClip[]): Project {
  const p = emptyProject();
  let n = 0;
  return { ...p, tracks: p.tracks.map((t) => (t.kind === "video" && n < 2 ? { ...t, clips: n++ === 0 ? lower : upper } : t)) };
}
check("ماتِ ترک: قطعهٔ بالا با بیشترین هم‌پوشانی ماتِ قطعهٔ پایین است", () => {
  const p = twoTracks([clip("a", 0, 6)], [clip("m1", 0, 1), clip("m2", 2, 3)]);
  assert.equal(matteSourceFor(p, "a")?.id, "m2");
  assert.equal(matteSourceFor(p, "m1"), null, "بالاترین ترک ماتی ندارد");
  assert.equal(matteSourceFor(twoTracks([clip("a", 0, 2)], [clip("m", 5, 2)]), "a"), null, "هم‌زمان نیستند");
  assert.equal(matteSourceFor(twoTracks([clip("a", 0, 2)], [clip("adj", 0, 2, { adjust: true, ref: "adjust", kind: "image" })]), "a"), null, "لایهٔ تنظیم مات نمی‌شود");
});
check("ماتِ ترک: برنامه‌ریزیِ پیش‌نمایش مثلِ سرور — هر مات فقط برای یک قطعه و فقط قطعه‌های مات‌خواه", () => {
  const tm = { mode: "luma" as const, invert: false };
  const p = twoTracks([clip("a", 0, 1, { track_matte: tm }), clip("b", 1, 1, { track_matte: tm }), clip("c", 2, 1)], [clip("m", 0, 3)]);
  const plan = planMattes(p);
  assert.equal(plan.of.size, 1);
  assert.equal(plan.of.get("a")?.id, "m");
  assert.ok(plan.src.has("m"));
  assert.equal(planMattes(twoTracks([clip("a", 0, 1)], [clip("m", 0, 1)])).src.size, 0, "بدونِ درخواست هیچ‌چیز مات نیست");
});
check("ماتِ ترک: روشن، حالت، برعکس، خاموش", () => {
  let p = twoTracks([clip("a", 0, 4)], [clip("m", 0, 4)]);
  p = setTrackMatte(p, "a", {});
  assert.deepEqual((findClip(p, "a")!.clip as MediaClip).track_matte, { mode: "luma", invert: false });
  p = setTrackMatte(p, "a", { mode: "alpha", invert: true });
  assert.deepEqual((findClip(p, "a")!.clip as MediaClip).track_matte, { mode: "alpha", invert: true });
  p = setTrackMatte(p, "a", { invert: false });
  assert.deepEqual((findClip(p, "a")!.clip as MediaClip).track_matte, { mode: "alpha", invert: false }, "فقط همان فیلد عوض می‌شود");
  p = setTrackMatte(p, "a", null);
  assert.equal((findClip(p, "a")!.clip as MediaClip).track_matte, undefined);
});
check("matteMultiply: روشنایی (سفید = دیده)، شفافیت، و برعکس", () => {
  const target = () => img([[200, 10, 10], [200, 10, 10], [200, 10, 10]]);
  const matte = img([[255, 255, 255], [0, 0, 0], [128, 128, 128]]);
  const t = target();
  matteMultiply(t, matte, "luma", false);
  assert.equal(t.data[3], 255);
  assert.equal(t.data[7], 0);
  assert.ok(t.data[11] > 100 && t.data[11] < 160, String(t.data[11]));
  const inv = target();
  matteMultiply(inv, matte, "luma", true);
  assert.deepEqual([inv.data[3], inv.data[7]], [0, 255]);
  const alphaMatte = img([[0, 0, 0], [0, 0, 0], [0, 0, 0]]);
  alphaMatte.data[3] = 255; alphaMatte.data[7] = 0; alphaMatte.data[11] = 128;
  const al = target();
  matteMultiply(al, alphaMatte, "alpha", false);
  assert.deepEqual([al.data[3], al.data[7]], [255, 0]);
  assert.ok(al.data[11] > 100 && al.data[11] < 160);
});

// ───────────── اصلاحِ لنز در پیش‌نمایش (همان نگاشتِ ffmpeg)
check("lensSource: مرکز ثابت، k=۰ هویت، k۱ مثبت نقطه‌ها را از مرکز دور می‌خواند", () => {
  assert.deepEqual(lensSource(160, 90, 320, 180, 0.3, 0), [160, 90]);
  assert.deepEqual(lensSource(10, 20, 320, 180, 0, 0), [10, 20]);
  const [sx] = lensSource(300, 90, 320, 180, 0.3, 0);
  assert.ok(sx > 300, `منبع دورتر از مرکز: ${sx}`);
  const [nx] = lensSource(300, 90, 320, 180, -0.3, 0);
  assert.ok(nx < 300);
  // مقدارِ مرجع: x=320 (لبهٔ راست) ، y=90 ⇒ r² = 160² / (160² + 90²) ؛ c = 1 + r²·k1
  const r2 = 160 ** 2 / (160 ** 2 + 90 ** 2);
  assert.ok(Math.abs(lensSource(320, 90, 320, 180, 0.3, 0)[0] - (160 + 160 * (1 + r2 * 0.3))) < 1e-9);
});
check("lensCorrect: k=۰ تصویر را عوض نمی‌کند؛ مرکز می‌ماند؛ بیرونِ منبع سیاهِ کدر", () => {
  const w = 33, h = 21;
  const px: [number, number, number][] = Array.from({ length: w * h }, (_, i) => [(i % w) * 7, Math.floor(i / w) * 11, 50]);
  const a = img(px); a.width = w; a.height = h;
  const before = Array.from(a.data);
  lensCorrect(a, 0, 0);
  assert.deepEqual(Array.from(a.data), before);
  const b = img(px); b.width = w; b.height = h;
  lensCorrect(b, 0.5, 0);
  const mid = (Math.floor(h / 2) * w + Math.floor(w / 2)) * 4;
  assert.deepEqual([b.data[mid], b.data[mid + 1]], [before[mid], before[mid + 1]], "مرکز ثابت");
  const corner = b.data;
  assert.equal(corner[3], 255);
  const c = img(px); c.width = w; c.height = h;
  lensCorrect(c, 0.9, 0.5);
  assert.deepEqual([c.data[0], c.data[1], c.data[2], c.data[3]], [0, 0, 0, 255], "گوشه از منبع بیرون زد ⇒ سیاه");
});

const bad = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "✓" : "✗"} ${r.name}${r.err ? `\n    ${r.err}` : ""}`);
console.log(`\n${results.length - bad.length}/${results.length} passed`);
if (bad.length) process.exit(1);
