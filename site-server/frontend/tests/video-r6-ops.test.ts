/**
 * آزمونِ ویرایش‌های دورِ ششم: برچسب و یادداشت، تفسیرِ فیلم، رسانهٔ گم‌شده، Replace edit، بلندیِ ترک، گذارِ پیش‌فرض، هم‌اندازه‌کردنِ موسیقی،
 * غلتشِ متن، نویزگیر و ترکیبِ فریم‌ها.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/video-r6-ops.test.ts --bundle --platform=node --format=esm --outfile=/tmp/video-r6-ops.test.mjs
 *   node /tmp/video-r6-ops.test.mjs
 */
import assert from "node:assert/strict";

import type { MediaItem } from "../src/features/content/video/api";
import { AnyClip, MediaClip, Project, TextClip, clipLength, emptyProject, findClip } from "../src/features/content/video/manual/model";
import { filterBin } from "../src/features/content/video/manual/r5ops";
import {
  INTERPRET_FPS, TEXT_MOTIONS, applyDefaultTransition, clearInterpretFps, interpretFps, interpretSpeed, isSlowed, metaHay, metaOf, motionPath, offlineClips, pictureEnd,
  removeAllTransitions, replaceEdit, retimeToLength, setAllTrackSizes, setDenoise, setFrames, setInterpret, setMediaMeta, setTextMotion, setTrackSize, stepTrackSize, tagsFromText, trackRow,
} from "../src/features/content/video/manual/r6ops";

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
const text = (id: string, at: number, duration: number, t: string, over: Partial<TextClip> = {}): TextClip => ({ id, type: "text", text: t, at, duration, position: "bottom", size: 6, color: "#fff", box: false, opacity: 1, label: t, ...over });
function proj(video: AnyClip[], audio: AnyClip[] = [], texts: AnyClip[] = []): Project {
  const p = emptyProject();
  let v = false, a = false, t = false;
  return { ...p, tracks: p.tracks.map((tr) => (tr.kind === "video" && !v ? ((v = true), { ...tr, clips: video }) : tr.kind === "audio" && !a ? ((a = true), { ...tr, clips: audio }) : tr.kind === "text" && !t ? ((t = true), { ...tr, clips: texts }) : tr)) };
}
const item = (over: Partial<MediaItem> = {}): MediaItem => ({ ref: "video:2", title: "فیلمِ تازه", kind: "video", source: "upload", duration: 20, has_audio: true, width: 1080, height: 1920, url: "/x", auth: false, proxy: "not_needed", proxy_url: null, ...over });

// ───────────── برچسب و یادداشت
check("برچسب‌ها از متن: جداکننده‌های فارسی و انگلیسی، بدون تکرار و با سقف", () => {
  assert.deepEqual(tagsFromText("محصول، بیرونی; نظرِ مشتری\nمحصول , b-roll"), ["محصول", "بیرونی", "نظرِ مشتری", "b-roll"]);
  assert.deepEqual(tagsFromText("   "), []);
  assert.equal(tagsFromText(Array.from({ length: 30 }, (_, i) => `t${i}`).join(",")).length, 12);
  assert.equal(tagsFromText("x".repeat(60))[0].length, 24);
});
check("برچسب و یادداشت ذخیره می‌شود، خالی شد حذف می‌شود، و در جستجوی رسانه‌ها پیدا می‌شود", () => {
  let p = proj([]);
  p = setMediaMeta(p, "video:1", { tags: ["محصول", "بیرونی"], note: "نمای افتتاحیه، نورِ خوب" });
  assert.deepEqual(metaOf(p, "video:1").tags, ["محصول", "بیرونی"]);
  assert.equal(metaOf(p, "video:9").note, "");
  const bin = [item({ ref: "video:1", title: "IMG_0042" }), item({ ref: "video:3", title: "IMG_0043" })];
  const found = filterBin(bin, "بیرونی", null, p.media_meta);
  assert.deepEqual(found.map((i) => i.ref), ["video:1"], "جستجو برچسب را هم می‌بیند");
  assert.deepEqual(filterBin(bin, "نورِ خوب", null, p.media_meta).map((i) => i.ref), ["video:1"], "و یادداشت را");
  assert.equal(filterBin(bin, "IMG", null).length, 2, "بدونِ meta مثلِ قبل");
  p = setMediaMeta(p, "video:1", { note: "x".repeat(900) });
  assert.equal(metaOf(p, "video:1").note.length, 300);
  p = setMediaMeta(setMediaMeta(p, "video:1", { tags: [] }), "video:1", { note: "" });
  assert.equal(p.media_meta, undefined);
  assert.equal(metaHay(undefined), "");
});

// ───────────── تفسیرِ فیلم
check("تفسیرِ فریم‌بر‌ثانیه: ۶۰ ← ۳۰ نیمه‌سرعت و بعدی‌ها جلو می‌روند؛ دوباره زدن از پایه حساب می‌شود؛ پاک‌کردن برمی‌گرداند", () => {
  assert.equal(interpretSpeed(60, 30), 0.5);
  assert.ok(INTERPRET_FPS.includes(24));
  const p0 = proj([clip("a", 0, 4), clip("b", 4, 2)]);
  const r = interpretFps(p0, "a", 60, 30);
  assert.ok(!("error" in r));
  if ("error" in r) return;
  const a = findClip(r.project, "a")!.clip as MediaClip;
  assert.equal(a.speed, 0.5);
  assert.equal(clipLength(a), 8);
  assert.equal(findClip(r.project, "b")!.clip.at, 8, "قطعهٔ بعدی به اندازهٔ کش‌آمدن جلو رفت");
  const again = interpretFps(r.project, "a", 60, 24);
  assert.ok(!("error" in again));
  if ("error" in again) return;
  assert.equal((findClip(again.project, "a")!.clip as MediaClip).speed, 0.4, "از سرعتِ پایهٔ ۱ حساب شد نه از ۰٫۵");
  const back = clearInterpretFps(again.project, "a");
  assert.equal((findClip(back, "a")!.clip as MediaClip).speed, 1);
  assert.equal(findClip(back, "b")!.clip.at, 4, "و بعدی‌ها برگشتند");
  assert.equal((findClip(back, "a")!.clip as MediaClip).interpret, undefined);
});
check("تفسیر: سرعت در بازهٔ ۰٫۲۵ تا ۴ می‌ماند و خبر می‌دهد؛ خطاهای فارسی", () => {
  const r = interpretFps(proj([clip("a", 0, 4)]), "a", 120, 12);
  assert.ok(!("error" in r));
  if (!("error" in r)) assert.deepEqual([r.speed, r.clamped], [0.25, true]);
  assert.ok("error" in interpretFps(proj([]), "zzz", 30, 24));
  assert.ok("error" in interpretFps(proj([clip("a", 0, 4)]), "a", 0, 24));
});
check("نسبتِ پیکسل و خط‌های درهم: محدود، خنثی حذف، و تفسیرِ fps را خراب نمی‌کند", () => {
  let p = proj([clip("a", 0, 4)]);
  p = setInterpret(p, "a", { par: 1.333, deinterlace: true });
  assert.deepEqual((findClip(p, "a")!.clip as MediaClip).interpret, { par: 1.333, deinterlace: true });
  p = setInterpret(p, "a", { par: 9 });
  assert.equal((findClip(p, "a")!.clip as MediaClip).interpret?.par, 2);
  const withFps = interpretFps(p, "a", 50, 25);
  assert.ok(!("error" in withFps));
  if ("error" in withFps) return;
  const q = setInterpret(withFps.project, "a", { par: 1, deinterlace: false });
  const it = (findClip(q, "a")!.clip as MediaClip).interpret!;
  assert.equal(it.par, undefined);
  assert.equal(it.deinterlace, undefined);
  assert.ok(it.fps, "فریم‌بر‌ثانیه می‌ماند");
  const clean = setInterpret(proj([clip("a", 0, 2, { interpret: { par: 1.5 } })]), "a", { par: 1 });
  assert.equal((findClip(clean, "a")!.clip as MediaClip).interpret, undefined);
});

// ───────────── نویزگیر و ترکیبِ فریم‌ها
check("نویزگیر: روشن با مقدار، حالتِ قوی، صفر/null = حذف", () => {
  let p = proj([clip("a", 0, 4)]);
  p = setDenoise(p, "a", { amount: 0.6 });
  assert.deepEqual((findClip(p, "a")!.clip as MediaClip).denoise, { amount: 0.6, mode: "fast" });
  p = setDenoise(p, "a", { mode: "strong" });
  assert.deepEqual((findClip(p, "a")!.clip as MediaClip).denoise, { amount: 0.6, mode: "strong" });
  assert.equal((findClip(setDenoise(p, "a", { amount: 0 }), "a")!.clip as MediaClip).denoise, undefined);
  assert.equal((findClip(setDenoise(p, "a", null), "a")!.clip as MediaClip).denoise, undefined);
  assert.equal((findClip(setDenoise(p, "a", { amount: 7 }), "a")!.clip as MediaClip).denoise?.amount, 1);
});
check("ترکیبِ فریم‌ها فقط برای قطعهٔ کندشده اثر دارد (isSlowed)", () => {
  assert.equal(isSlowed(clip("a", 0, 2, { speed: 0.5 })), true);
  assert.equal(isSlowed(clip("a", 0, 2, { speed: 1 })), false);
  assert.equal(isSlowed(clip("a", 0, 2, { speed: 0.5, freeze: true })), false);
  assert.equal(isSlowed(clip("a", 0, 2, { ramp: [{ t: 0, v: 1 }, { t: 1, v: 0.4 }] as never })), true);
  const p = setFrames(proj([clip("a", 0, 4)]), "a", "flow");
  assert.equal((findClip(p, "a")!.clip as MediaClip).frames, "flow");
  assert.equal((findClip(setFrames(p, "a", null), "a")!.clip as MediaClip).frames, undefined);
});

// ───────────── رسانهٔ گم‌شده
check("رسانهٔ گم‌شده: فقط قطعه‌هایی که ref شان در رسانه‌ها نیست؛ شکل، لایهٔ تنظیم، توالی و استیکر نه", () => {
  const p = proj([clip("ok", 0, 2, { ref: "video:1" }), clip("gone", 2, 2, { ref: "video:777", label: "فیلمِ پاک‌شده" }), clip("sh", 4, 2, { ref: "shape" }), clip("adj", 6, 2, { ref: "adjust" }), clip("sq", 8, 2, { ref: "seq:abc" })]);
  const off = offlineClips(p, new Set(["video:1"]));
  assert.deepEqual(off.map((o) => o.id), ["gone"]);
  assert.equal(off[0].label, "فیلمِ پاک‌شده");
  const nested: Project = { ...p, sequences: { s: { name: "تودرتو", tracks: [{ id: "tt", kind: "video", name: "ت", muted: false, locked: false, clips: [clip("deep", 0, 1, { ref: "video:555" })] }] } } };
  assert.deepEqual(offlineClips(nested, new Set(["video:1"])).map((o) => o.id).sort(), ["deep", "gone"]);
  assert.deepEqual(offlineClips(p, new Set(["video:1", "video:777"])), []);
});

// ───────────── Replace edit
check("Replace edit: همان جا و همان طول، از نقطهٔ ورودیِ منبع؛ جلوه‌ها می‌ماند", () => {
  const p = proj([clip("a", 5, 4, { speed: 2, effects: [{ tool: "vignette", params: {} }] as never, color: { exposure: 0.2 } as never })]);
  const r = replaceEdit(p, "a", item({ duration: 30 }), 10);
  assert.ok(!("error" in r));
  if ("error" in r) return;
  const c = findClip(r.project, "a")!.clip as MediaClip;
  assert.equal(c.ref, "video:2");
  assert.equal(c.start, 10);
  assert.equal(c.end, 14, "طولِ تایم‌لاین ۲ ثانیه × سرعتِ ۲ = ۴ ثانیه از منبع");
  assert.equal(c.at, 5);
  assert.equal(clipLength(c), 2);
  assert.equal(c.effects.length, 1);
  assert.deepEqual(c.color, { exposure: 0.2 });
});
check("Replace edit: خطاها و کوتاه‌بودنِ منبع", () => {
  const p = proj([clip("a", 0, 4)], [clip("m", 0, 4, { kind: "audio", ref: "audio:1" })]);
  assert.ok("error" in replaceEdit(p, "nope", item(), 0));
  assert.ok("error" in replaceEdit(p, "a", item({ kind: "audio", ref: "audio:9" }), 0), "نوعِ رسانه با قطعه نمی‌خواند");
  assert.ok("error" in replaceEdit(p, "a", item({ duration: 20 }), 19.9), "از این نقطه چیزی نمانده");
  const tail = replaceEdit(p, "a", item({ duration: 6 }), 4);
  assert.ok(!("error" in tail));
  if (!("error" in tail)) assert.equal((findClip(tail.project, "a")!.clip as MediaClip).end, 6, "منبع کوتاه بود: تا آخرِ منبع");
  const img = replaceEdit(p, "a", item({ kind: "image", ref: "pimg:3", duration: 0 }), 0);
  assert.ok(!("error" in img));
  if (!("error" in img)) assert.equal((findClip(img.project, "a")!.clip as MediaClip).kind, "image");
});

// ───────────── بلندیِ ترک
check("بلندیِ ترک: چهار اندازه، پله‌ای، معمولی ذخیره نمی‌شود، همه‌یکجا", () => {
  let p = proj([clip("a", 0, 2)]);
  const id = p.tracks[0].id;
  assert.equal(trackRow(p.tracks[0]), 52);
  p = setTrackSize(p, id, "l");
  assert.equal(trackRow(p.tracks[0]), 88);
  p = stepTrackSize(p, id, 1);
  assert.equal(p.tracks[0].size, "l", "بالاتر از بلند نمی‌رود");
  p = stepTrackSize(stepTrackSize(stepTrackSize(p, id, -1), id, -1), id, -1);
  assert.equal(p.tracks[0].size, "c");
  assert.equal(stepTrackSize(p, id, -1).tracks[0].size, "c");
  assert.equal(setTrackSize(p, id, "m").tracks[0].size, undefined);
  assert.ok(setAllTrackSizes(p, "s").tracks.every((t) => t.size === "s"));
  assert.equal(stepTrackSize(p, "nope", 1), p);
});

// ───────────── گذارِ پیش‌فرض
check("گذارِ پیش‌فرض روی برش‌های چسبیده می‌نشیند؛ دارای گذار دست نمی‌خورد مگر replace؛ ترکِ قفل و صدا نه", () => {
  const p = proj([clip("a", 0, 2), clip("b", 2, 2), clip("c", 4.05, 2, { transition: { kind: "wipeleft", duration: 0.5 } }), clip("d", 9, 2)]);
  const r = applyDefaultTransition(p, { kind: "fade", duration: 0.4 });
  assert.equal(r.count, 1, "فقط برشِ a|b؛ c از قبل گذار دارد و d چسبیده نیست");
  assert.deepEqual((findClip(r.project, "b")!.clip as MediaClip).transition, { kind: "fade", duration: 0.4 });
  assert.equal((findClip(r.project, "c")!.clip as MediaClip).transition?.kind, "wipeleft");
  assert.deepEqual(r.project.default_transition, { kind: "fade", duration: 0.4 });
  const all = applyDefaultTransition(p, { kind: "fade", duration: 5, replace: true });
  assert.equal(all.count, 2);
  assert.equal((findClip(all.project, "c")!.clip as MediaClip).transition?.duration, 2, "مدت محدود می‌شود");
  const locked = { ...p, tracks: p.tracks.map((t, i) => (i === 0 ? { ...t, locked: true } : t)) };
  assert.equal(applyDefaultTransition(locked, { kind: "fade", duration: 0.4 }).count, 0);
  const cleared = removeAllTransitions(all.project);
  assert.equal(cleared.count, 2);
  assert.equal((findClip(cleared.project, "b")!.clip as MediaClip).transition, null);
});

// ───────────── هم‌اندازه‌کردنِ موسیقی
check("موسیقی با ویدیو هم‌اندازه می‌شود: سرعتِ ۰٫۵ تا ۲، بریدن اگر خیلی بلند است، هشدار اگر خیلی کوتاه است", () => {
  const music = (len: number) => clip("m", 0, len, { kind: "audio", ref: "audio:1", has_audio: true });
  const base = (len: number) => proj([clip("v", 0, 30)], [music(len)]);
  assert.equal(pictureEnd(base(40)), 30);
  const a = retimeToLength(base(40), "m", 30);
  assert.ok(!("error" in a));
  if ("error" in a) return;
  assert.ok(Math.abs(clipLength(findClip(a.project, "m")!.clip) - 30) < 0.05, "۴۰ ثانیه ← ۳۰ ثانیه با سرعتِ ۱٫۳۳");
  assert.equal(a.note, "");
  const long = retimeToLength(base(100), "m", 30);
  assert.ok(!("error" in long));
  if (!("error" in long)) {
    assert.equal(long.speed, 2);
    assert.ok(Math.abs(clipLength(findClip(long.project, "m")!.clip) - 30) < 0.05);
    assert.match(long.note, /بریده/);
    assert.ok((findClip(long.project, "m")!.clip as MediaClip).fade_out >= 1.5);
  }
  const short = retimeToLength(base(10), "m", 30);
  assert.ok(!("error" in short));
  if (!("error" in short)) {
    assert.equal(short.speed, 0.5);
    assert.match(short.note, /کوتاه/);
  }
  assert.ok("error" in retimeToLength(base(10), "v", 30), "قطعهٔ تصویر موسیقی نیست");
  assert.ok("error" in retimeToLength(base(10), "m", 0));
});

// ───────────── غلتش و مسیرِ متن
check("غلتشِ متن: تیتراژ از پایین به بالا با مدتِ متناسب با خط‌ها؛ نوارِ خبر افقی؛ پاک‌کردن", () => {
  const lines = Array.from({ length: 10 }, (_, i) => `خط ${i + 1}`).join("\n");
  let p = proj([], [], [text("t", 1, 4, lines)]);
  p = setTextMotion(p, "t", "roll-up");
  const t = findClip(p, "t")!.clip as TextClip;
  assert.equal(t.duration, 15, "۳ + ۱٫۲ × ۱۰ خط");
  assert.deepEqual(t.path, [{ t: 0, dx: 0, dy: 0.75 }, { t: 15, dx: 0, dy: -0.75 }]);
  assert.equal(t.align, "center");
  assert.equal(t.anim_in, "none");
  const crawl = setTextMotion(proj([], [], [text("t", 0, 6, "خبر فوری")]), "t", "crawl-left");
  const c = findClip(crawl, "t")!.clip as TextClip;
  assert.equal(c.duration, 6, "نوارِ خبر مدت را عوض نمی‌کند");
  assert.deepEqual([c.path![0].dx, c.path![1].dx], [1.1, -1.1]);
  assert.equal(c.position, "bottom");
  assert.equal((findClip(setTextMotion(p, "t", null), "t")!.clip as TextClip).path, undefined);
  assert.equal(setTextMotion(proj([clip("a", 0, 2)]), "a", "roll-up").tracks[0].clips[0].id, "a", "روی قطعهٔ رسانه‌ای هیچ نمی‌کند");
});
check("مسیرِ قوس و موج: نقطه‌های هموار، در بازهٔ مجازِ سرور، و زمان‌ها صعودی", () => {
  for (const m of TEXT_MOTIONS) {
    const pts = motionPath(m.key, 5);
    assert.ok(pts.length >= 2 && pts.length <= 80, m.key);
    for (let i = 1; i < pts.length; i++) assert.ok(pts[i].t > pts[i - 1].t, `${m.key}: زمان صعودی`);
    for (const q of pts) assert.ok(Math.abs(q.dx) <= 2 && Math.abs(q.dy) <= 2, `${m.key}: در بازهٔ مجاز`);
    assert.ok(Math.abs(pts[pts.length - 1].t - 5) < 1e-6, `${m.key}: تا پایانِ متن`);
  }
  const arc = motionPath("arc", 4);
  assert.ok(arc[4].dy < arc[0].dy && arc[4].dy < arc[8].dy, "وسطِ کمان بالاتر است");
  assert.ok(Math.abs(arc[0].dx + 0.4) < 1e-9 && Math.abs(arc[8].dx - 0.4) < 1e-9);
});

const bad = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "✓" : "✗"} ${r.name}${r.err ? `\n    ${r.err}` : ""}`);
console.log(`\n${results.length - bad.length}/${results.length} passed`);
if (bad.length) process.exit(1);
